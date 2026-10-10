"""`media_quality.score` per docs/CONVENTIONS.md, in one UPDATE per media, event or library.

score = 0.35*aesthetic_norm + 0.25*sharpness + 0.15*faces_term + 0.15*eyes_smile + 0.10*likes_norm
aesthetic_norm = clamp((aesthetic-3)/5); faces_term = 1 for 1-6 faces, 0.6 for 0, 0.4 for > 6;
eyes_smile = mean(eyes_open, smile) (0.5 when there are no faces); likes_norm = likes / max likes
in the same event (or the same owner's library for items without an event).
"""

from __future__ import annotations

import psycopg

SCORE_SQL = """
with scope as (
  select m.id
  from media m
  where m.state <> 'removed'
    and ((%(event_id)s::bytea is not null and m.event_id = %(event_id)s::bytea)
      or (%(event_id)s::bytea is null and m.event_id is null and m.owner_id = %(owner_id)s::bytea))
),
counts as (
  select s.id, (select count(*) from likes l where l.media_id = s.id)::float8 as likes
  from scope s
),
mx as (select max(likes) as max_likes from counts)
update media_quality q
set score = (
    0.35 * least(1.0, greatest(0.0, (coalesce(q.aesthetic, 3.0) - 3.0) / 5.0))
  + 0.25 * least(1.0, greatest(0.0, coalesce(q.sharpness, 0.0)))
  + 0.15 * (case when coalesce(q.face_count, 0) = 0 then 0.6
                 when q.face_count <= 6 then 1.0 else 0.4 end)
  + 0.15 * (case when coalesce(q.face_count, 0) = 0 then 0.5
                 else (coalesce(q.eyes_open, 0.5) + coalesce(q.smile, 0.5)) / 2.0 end)
  + 0.10 * coalesce(c.likes / nullif(mx.max_likes, 0), 0.0)
)::real
from counts c, mx
where q.media_id = c.id
  and (%(media_id)s::bytea is null or q.media_id = %(media_id)s::bytea)
"""


def update_scores(
    conn: psycopg.Connection,
    *,
    event_id: bytes | None,
    owner_id: bytes | None,
    media_id: bytes | None = None,
) -> int:
    """Recompute `score` for one media (`media_id`) or every item of the scope. Returns rows."""
    cur = conn.execute(
        SCORE_SQL, {"event_id": event_id, "owner_id": owner_id, "media_id": media_id}
    )
    return cur.rowcount


def recompute_event(conn: psycopg.Connection, event_id: bytes) -> int:
    """The `recompute_scores {event_id}` job: likes changed, refresh the whole event."""
    return update_scores(conn, event_id=event_id, owner_id=None)
