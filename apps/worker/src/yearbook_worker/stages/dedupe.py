"""dedupe: exact (sha256) and near (pHash ≤ 6 bits within ±120 s) duplicates in one event."""

from __future__ import annotations

import psycopg

from yearbook_worker import ids
from yearbook_worker.context import StageContext

PHASH_MAX_DISTANCE = 6
NEAR_WINDOW_S = 120

FIND_SQL = """
with me as (
  select id, event_id, owner_id, content_sha256, phash, captured_at from media where id = %(id)s
)
select m.id, m.dup_group_id,
       (m.content_sha256 = me.content_sha256) as exact
from media m
join me on m.id <> me.id
where m.state <> 'removed'
  and ((me.event_id is not null and m.event_id = me.event_id)
       or (me.event_id is null and m.event_id is null and m.owner_id = me.owner_id))
  and (
    (m.content_sha256 is not null and m.content_sha256 = me.content_sha256)
    or (
      m.phash is not null and me.phash is not null
      and bit_count(m.phash # me.phash) <= %(max_distance)s
      and m.captured_at is not null and me.captured_at is not null
      and abs(extract(epoch from (m.captured_at - me.captured_at))) <= %(window_s)s
    )
  )
order by exact desc, (m.dup_group_id is not null) desc, m.created_at, m.id
limit 1
"""

LOCK_SQL = "select id, dup_group_id from media where id = any(%(ids)s) order by id for update"

INSERT_GROUP_SQL = """
insert into duplicate_groups (id, event_id, kind) values (%(id)s, %(event_id)s, %(kind)s)
"""

ASSIGN_SQL = "update media set dup_group_id = %(gid)s where id = any(%(ids)s)"
MERGE_SQL = "update media set dup_group_id = %(gid)s where dup_group_id = any(%(old)s)"
DROP_GROUPS_SQL = "delete from duplicate_groups where id = any(%(old)s)"

RANK_SQL = """
update media
set is_best_of_dup = (id = (
  select id from media
  where dup_group_id = %(gid)s and state <> 'removed'
  order by original_bytes desc nulls last, created_at, id
  limit 1
))
where dup_group_id = %(gid)s
"""


def run(ctx: StageContext, conn: psycopg.Connection) -> None:
    found = conn.execute(
        FIND_SQL,
        {"id": ctx.media.id, "max_distance": PHASH_MAX_DISTANCE, "window_s": NEAR_WINDOW_S},
    ).fetchone()
    if found is None:
        return
    other_id = bytes(found["id"])
    kind = "exact" if found["exact"] else "near"

    # Lock both rows (ordered by id to avoid deadlocks) and re-read group membership.
    locked = conn.execute(LOCK_SQL, {"ids": [ctx.media.id, other_id]}).fetchall()
    existing = sorted({bytes(r["dup_group_id"]) for r in locked if r["dup_group_id"] is not None})
    gid = existing[0] if existing else ids.new_id()
    if not existing:
        conn.execute(INSERT_GROUP_SQL, {"id": gid, "event_id": ctx.media.event_id, "kind": kind})
    elif len(existing) > 1:  # both already grouped separately: merge into the first group
        conn.execute(MERGE_SQL, {"gid": gid, "old": existing[1:]})
        conn.execute(DROP_GROUPS_SQL, {"old": existing[1:]})
    conn.execute(ASSIGN_SQL, {"gid": gid, "ids": [ctx.media.id, other_id]})
    conn.execute(RANK_SQL, {"gid": gid})
