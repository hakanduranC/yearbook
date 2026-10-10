"""`cluster_event`: faces → persons per SDD §8.2 and docs/CONVENTIONS.md.

Incremental run: unassigned faces join the nearest person centroid when cosine ≥ 0.52 with a
margin ≥ 0.05 to the runner-up (low-quality faces, quality < 0.4, only at ≥ 0.6); the remainder
is clustered with HDBSCAN (min_cluster_size 2) into new persons. A full recluster (more than
25 % of the event's faces are new since `events.clustered_at`, no previous run, or `--force`)
clusters every decent face from scratch and maps clusters back to existing person ids by maximum
overlap so ids survive. `person_constraints` (must_link / cannot_link) are applied on top, then
persons get face_count, a quality-weighted centroid, the best frontal cover face, and unnamed
persons with ≥ 3 faces sharing one Takeout name hint receive that name.
"""

from __future__ import annotations

import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import numpy as np
import psycopg
from psycopg_pool import ConnectionPool

from yearbook_worker import ids
from yearbook_worker.config import Settings
from yearbook_worker.log import get_logger
from yearbook_worker.notify import notify_people_updated
from yearbook_worker.vectors import as_array

log = get_logger(__name__)

ASSIGN_COS = 0.52
ASSIGN_MARGIN = 0.05
LOW_QUALITY = 0.4
LOW_QUALITY_COS = 0.60
FULL_RECLUSTER_RATIO = 0.25
MIN_CLUSTER_SIZE = 2
MEMBER_MIN_COS = 0.45  # HDBSCAN members further from their cluster centroid become noise
SINGLE_CLUSTER_MIN_COS = 0.55  # all faces of a run may be one person; HDBSCAN cannot say so
HINT_MIN_FACES = 3

LOAD_EVENT_SQL = "select id, clustered_at, faces_enabled from events where id = %(id)s"
LOAD_FACES_SQL = """
select f.id, f.media_id, f.person_id, f.embedding, coalesce(f.quality, 0) as quality,
       f.landmarks, f.created_at
from faces f join media m on m.id = f.media_id
where f.event_id = %(id)s and m.state <> 'removed'
order by f.created_at, f.id
"""
LOAD_PERSONS_SQL = """
select p.id, p.display_name, p.centroid, p.face_count,
       exists (select 1 from person_links l where l.person_id = p.id) as linked
from persons p where p.event_id = %(id)s
"""
LOAD_CONSTRAINTS_SQL = "select face_a, face_b, kind from person_constraints where event_id = %(id)s"
INSERT_PERSON_SQL = "insert into persons (id, event_id) values (%(id)s, %(event_id)s)"
SET_FACE_PERSON_SQL = "update faces set person_id = %(person_id)s where id = %(id)s"
UPDATE_PERSON_SQL = """
update persons
set face_count = %(face_count)s, centroid = %(centroid)s, cover_face = %(cover_face)s,
    cover_face_quality = %(cover_face_quality)s, updated_at = now()
where id = %(id)s
"""
DELETE_EMPTY_SQL = """
delete from persons p
where p.event_id = %(id)s and p.face_count = 0 and p.display_name is null
  and not exists (select 1 from person_links l where l.person_id = p.id)
"""
APPLY_HINTS_SQL = """
with cand as (
  select f.person_id, h.name, count(distinct f.id) as n
  from faces f
  join media_person_hints h on h.media_id = f.media_id
  join persons p on p.id = f.person_id
  where f.event_id = %(id)s and p.display_name is null
  group by f.person_id, h.name
  having count(distinct f.id) >= %(min_faces)s
), ranked as (
  select person_id, name, n,
         row_number() over (partition by name order by n desc, person_id) as rn_name,
         row_number() over (partition by person_id order by n desc, name) as rn_person
  from cand
)
update persons p
set display_name = r.name, updated_at = now()
from ranked r
where r.person_id = p.id and r.rn_name = 1 and r.rn_person = 1
  and not exists (select 1 from persons q where q.event_id = p.event_id and q.display_name = r.name)
returning p.id
"""
SET_CLUSTERED_SQL = "update events set clustered_at = now() where id = %(id)s"


@dataclass(slots=True)
class FaceVec:
    id: bytes
    media_id: bytes
    person_id: bytes | None
    embedding: np.ndarray
    quality: float
    kps: np.ndarray | None
    created_at: datetime


@dataclass(slots=True)
class PersonRow:
    id: bytes
    display_name: str | None
    centroid: np.ndarray | None
    face_count: int
    linked: bool


@dataclass(slots=True)
class ClusterStats:
    event_id: bytes
    mode: str
    faces: int
    assigned: int
    persons: int
    new_persons: int
    named_from_hints: int
    duration_ms: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "event_id": ids.encode(self.event_id),
            "mode": self.mode,
            "faces": self.faces,
            "assigned": self.assigned,
            "persons": self.persons,
            "new_persons": self.new_persons,
            "named_from_hints": self.named_from_hints,
            "duration_ms": self.duration_ms,
        }


# --- pure numpy pieces (unit tested on synthetic vectors) --------------------------------------


def normalize(vectors: np.ndarray) -> np.ndarray:
    v = np.asarray(vectors, dtype=np.float32)
    if v.ndim == 1:
        return v / max(float(np.linalg.norm(v)), 1e-6)
    return v / np.maximum(np.linalg.norm(v, axis=1, keepdims=True), 1e-6)


def weighted_centroid(vectors: np.ndarray, qualities: np.ndarray) -> np.ndarray:
    weights = np.maximum(np.asarray(qualities, dtype=np.float32), 0.05)
    return normalize((np.asarray(vectors, dtype=np.float32) * weights[:, None]).sum(axis=0))


def assign_to_centroids(
    vectors: np.ndarray,
    qualities: np.ndarray,
    centroids: np.ndarray,
    *,
    cos: float = ASSIGN_COS,
    margin: float = ASSIGN_MARGIN,
    low_quality: float = LOW_QUALITY,
    low_quality_cos: float = LOW_QUALITY_COS,
) -> list[int | None]:
    """Index of the centroid each vector joins, or None. Vectors and centroids are unit length."""
    if len(vectors) == 0 or len(centroids) == 0:
        return [None] * len(vectors)
    sims = np.asarray(vectors, dtype=np.float32) @ np.asarray(centroids, dtype=np.float32).T
    out: list[int | None] = []
    for row, quality in zip(sims, qualities, strict=True):
        order = np.argsort(-row)
        best = int(order[0])
        best_sim = float(row[best])
        runner_up = float(row[order[1]]) if len(order) > 1 else -1.0
        threshold = low_quality_cos if quality < low_quality else cos
        if best_sim >= threshold and best_sim - runner_up >= margin:
            out.append(best)
        else:
            out.append(None)
    return out


def cluster_vectors(
    vectors: np.ndarray, *, min_cluster_size: int = MIN_CLUSTER_SIZE
) -> np.ndarray:
    """HDBSCAN labels (-1 = noise) over unit vectors (euclidean there orders like cosine)."""
    n = len(vectors)
    if n < min_cluster_size:
        return np.full(n, -1, dtype=int)
    from sklearn.cluster import HDBSCAN

    data = np.asarray(vectors, dtype=np.float64)
    labels = HDBSCAN(
        min_cluster_size=min_cluster_size,
        min_samples=1,
        metric="euclidean",
        cluster_selection_method="eom",
        copy=True,
    ).fit_predict(data)
    if labels.max(initial=-1) < 0:
        # HDBSCAN cannot return a single cluster; accept one when everything is close.
        centroid = normalize(data.mean(axis=0))
        if float((data @ centroid).min()) >= SINGLE_CLUSTER_MIN_COS:
            labels = np.zeros(n, dtype=int)
    return _tighten(data, labels, min_cluster_size)


def _tighten(data: np.ndarray, labels: np.ndarray, min_cluster_size: int) -> np.ndarray:
    """Drop members that sit far from their cluster centroid, then dissolve too-small clusters."""
    labels = labels.copy()
    for label in sorted(set(labels) - {-1}):
        idx = np.flatnonzero(labels == label)
        centroid = normalize(data[idx].mean(axis=0))
        sims = data[idx] @ centroid
        labels[idx[sims < MEMBER_MIN_COS]] = -1
        if int((labels == label).sum()) < min_cluster_size:
            labels[labels == label] = -1
    # relabel 0..k-1
    mapping = {old: new for new, old in enumerate(sorted(set(labels) - {-1}))}
    return np.array([mapping.get(int(v), -1) for v in labels], dtype=int)


def map_clusters_to_persons(
    labels: np.ndarray, prior: list[bytes | None]
) -> dict[int, bytes | None]:
    """Cluster label → existing person id by maximum overlap, each person used at most once."""
    overlap: Counter[tuple[int, bytes]] = Counter()
    for label, pid in zip(labels, prior, strict=True):
        if label >= 0 and pid is not None:
            overlap[(int(label), pid)] += 1
    mapping: dict[int, bytes | None] = {int(label): None for label in set(labels) if label >= 0}
    used: set[bytes] = set()
    for (label, pid), _count in sorted(overlap.items(), key=lambda kv: (-kv[1], kv[0][0])):
        if mapping.get(label) is None and pid not in used:
            mapping[label] = pid
            used.add(pid)
    return mapping


def purity_completeness(
    truth: dict[bytes, str], predicted: dict[bytes, bytes | None]
) -> tuple[float, float, int]:
    """Purity and completeness of `predicted` person ids against hand labels.

    Unassigned faces count as singleton clusters. Returns (purity, completeness, clusters).
    """
    keys = [k for k in truth if k in predicted]
    if not keys:
        return 0.0, 0.0, 0
    clusters: dict[Any, Counter[str]] = defaultdict(Counter)
    for key in keys:
        cluster = predicted[key] if predicted[key] is not None else ("noise", key)
        clusters[cluster][truth[key]] += 1
    n = len(keys)
    purity = sum(max(c.values()) for c in clusters.values()) / n
    per_label: dict[str, Counter[Any]] = defaultdict(Counter)
    for cluster, counter in clusters.items():
        for label, count in counter.items():
            per_label[label][cluster] += count
    completeness = sum(max(c.values()) for c in per_label.values()) / n
    real_clusters = sum(1 for c in clusters if not (isinstance(c, tuple) and c[0] == "noise"))
    return purity, completeness, real_clusters


# --- the job --------------------------------------------------------------------------------------


def run_cluster_event(
    pool: ConnectionPool, settings: Settings, event_id: bytes, *, force_full: bool = False
) -> ClusterStats | None:
    started = time.perf_counter()
    with pool.connection() as conn:
        event = conn.execute(LOAD_EVENT_SQL, {"id": event_id}).fetchone()
        if event is None:
            log.info("cluster.skip_missing_event", event_id=ids.encode(event_id))
            return None
        faces = _load_faces(conn, event_id)
        persons = _load_persons(conn, event_id)
        constraints = conn.execute(LOAD_CONSTRAINTS_SQL, {"id": event_id}).fetchall()

        clustered_at = event["clustered_at"]
        recent = sum(1 for f in faces if clustered_at is None or f.created_at > clustered_at)
        full = force_full or clustered_at is None or (
            faces and recent / len(faces) > FULL_RECLUSTER_RATIO
        )
        existing = {p.id for p in persons}
        assignment = full_recluster(faces, persons) if full else incremental(faces, persons)
        assignment = apply_constraints(
            assignment,
            {f.id: f for f in faces},
            [(bytes(c["face_a"]), bytes(c["face_b"]), c["kind"]) for c in constraints],
        )

        with conn.transaction():
            new_persons = {pid for pid in assignment.values() if pid and pid not in existing}
            for pid in new_persons:
                conn.execute(INSERT_PERSON_SQL, {"id": pid, "event_id": event_id})
            for face in faces:
                target = assignment.get(face.id)
                if target != face.person_id:
                    conn.execute(SET_FACE_PERSON_SQL, {"id": face.id, "person_id": target})
            touched = _update_persons(conn, faces, assignment, persons)
            conn.execute(DELETE_EMPTY_SQL, {"id": event_id})
            named = conn.execute(
                APPLY_HINTS_SQL, {"id": event_id, "min_faces": HINT_MIN_FACES}
            ).fetchall()
            conn.execute(SET_CLUSTERED_SQL, {"id": event_id})
            notify_people_updated(conn, event_id)

    stats = ClusterStats(
        event_id=event_id,
        mode="full" if full else "incremental",
        faces=len(faces),
        assigned=sum(1 for v in assignment.values() if v is not None),
        persons=touched,
        new_persons=len(new_persons),
        named_from_hints=len(named),
        duration_ms=int((time.perf_counter() - started) * 1000),
    )
    log.info("cluster.done", **stats.as_dict())
    return stats


def _load_faces(conn: psycopg.Connection, event_id: bytes) -> list[FaceVec]:
    rows = conn.execute(LOAD_FACES_SQL, {"id": event_id}).fetchall()
    out = []
    for r in rows:
        lm = r["landmarks"]
        out.append(
            FaceVec(
                id=bytes(r["id"]),
                media_id=bytes(r["media_id"]),
                person_id=bytes(r["person_id"]) if r["person_id"] is not None else None,
                embedding=normalize(as_array(r["embedding"])),
                quality=float(r["quality"]),
                kps=(
                    np.asarray(lm[:10], dtype=np.float32).reshape(5, 2)
                    if lm and len(lm) >= 10
                    else None
                ),
                created_at=r["created_at"],
            )
        )
    return out


def _load_persons(conn: psycopg.Connection, event_id: bytes) -> list[PersonRow]:
    rows = conn.execute(LOAD_PERSONS_SQL, {"id": event_id}).fetchall()
    return [
        PersonRow(
            id=bytes(r["id"]),
            display_name=r["display_name"],
            centroid=normalize(as_array(r["centroid"])) if r["centroid"] is not None else None,
            face_count=int(r["face_count"]),
            linked=bool(r["linked"]),
        )
        for r in rows
    ]


def incremental(faces: list[FaceVec], persons: list[PersonRow]) -> dict[bytes, bytes | None]:
    """Keep existing assignments; place new faces by centroid, cluster what is left."""
    assignment: dict[bytes, bytes | None] = {f.id: f.person_id for f in faces}
    pending = [f for f in faces if f.person_id is None]
    if not pending:
        return assignment
    with_centroid = [p for p in persons if p.centroid is not None]
    if with_centroid:
        centroids = np.stack([p.centroid for p in with_centroid])  # type: ignore[misc]
        picks = assign_to_centroids(
            np.stack([f.embedding for f in pending]),
            np.array([f.quality for f in pending]),
            centroids,
        )
        still = []
        for face, pick in zip(pending, picks, strict=True):
            if pick is None:
                still.append(face)
            else:
                assignment[face.id] = with_centroid[pick].id
        pending = still
    _cluster_into_new_persons(pending, assignment, prior=None)
    return assignment


def full_recluster(faces: list[FaceVec], persons: list[PersonRow]) -> dict[bytes, bytes | None]:
    """Cluster every decent face from scratch; keep person ids by overlap."""
    assignment: dict[bytes, bytes | None] = {f.id: None for f in faces}
    good = [f for f in faces if f.quality >= LOW_QUALITY]
    if len(good) < MIN_CLUSTER_SIZE:
        good = list(faces)
    low = [f for f in faces if f not in good]
    labels = cluster_vectors(np.stack([f.embedding for f in good])) if good else np.zeros(0, int)
    mapping = map_clusters_to_persons(labels, [f.person_id for f in good])
    label_ids: dict[int, bytes] = {
        label: (pid or ids.new_id()) for label, pid in mapping.items()
    }
    kept_persons = {p.id for p in persons if p.display_name or p.linked}
    for face, label in zip(good, labels, strict=True):
        if label >= 0:
            assignment[face.id] = label_ids[int(label)]
        elif face.person_id in kept_persons:
            assignment[face.id] = face.person_id  # noise now, but a human named that person
    if low:
        centroids, centroid_ids = _centroids_from(good, assignment)
        if centroid_ids:
            picks = assign_to_centroids(
                np.stack([f.embedding for f in low]), np.array([f.quality for f in low]), centroids
            )
            for face, pick in zip(low, picks, strict=True):
                if pick is not None:
                    assignment[face.id] = centroid_ids[pick]
    return assignment


def _centroids_from(
    faces: list[FaceVec], assignment: dict[bytes, bytes | None]
) -> tuple[np.ndarray, list[bytes]]:
    groups: dict[bytes, list[FaceVec]] = defaultdict(list)
    for f in faces:
        pid = assignment.get(f.id)
        if pid is not None:
            groups[pid].append(f)
    if not groups:
        return np.zeros((0, 512), np.float32), []
    pids = list(groups)
    cents = np.stack(
        [
            weighted_centroid(
                np.stack([f.embedding for f in groups[p]]), np.array([f.quality for f in groups[p]])
            )
            for p in pids
        ]
    )
    return cents, pids


def _cluster_into_new_persons(
    pending: list[FaceVec], assignment: dict[bytes, bytes | None], prior: Any
) -> None:
    if len(pending) < MIN_CLUSTER_SIZE:
        return
    labels = cluster_vectors(np.stack([f.embedding for f in pending]))
    new_ids: dict[int, bytes] = {}
    for face, label in zip(pending, labels, strict=True):
        if label >= 0:
            assignment[face.id] = new_ids.setdefault(int(label), ids.new_id())


def apply_constraints(
    assignment: dict[bytes, bytes | None],
    faces: dict[bytes, FaceVec],
    constraints: list[tuple[bytes, bytes, str]],
) -> dict[bytes, bytes | None]:
    """must_link merges (or creates) persons; cannot_link splits the weaker face away."""
    assignment = dict(assignment)
    for a, b, kind in constraints:
        if kind != "must_link" or a not in assignment or b not in assignment:
            continue
        pa, pb = assignment[a], assignment[b]
        if pa == pb and pa is not None:
            continue
        if pa is None and pb is None:
            pid = ids.new_id()
            assignment[a] = assignment[b] = pid
        elif pa is None:
            assignment[a] = pb
        elif pb is None:
            assignment[b] = pa
        else:  # merge the smaller group into the larger one
            size = Counter(v for v in assignment.values() if v is not None)
            keep, drop = (pa, pb) if size[pa] >= size[pb] else (pb, pa)
            for fid, pid in assignment.items():
                if pid == drop:
                    assignment[fid] = keep
    for a, b, kind in constraints:
        if kind != "cannot_link" or a not in assignment or b not in assignment:
            continue
        pa, pb = assignment[a], assignment[b]
        if pa is None or pa != pb:
            continue
        members = [faces[fid] for fid, pid in assignment.items() if pid == pa and fid in faces]
        centroid = weighted_centroid(
            np.stack([m.embedding for m in members]), np.array([m.quality for m in members])
        )
        sim_a = float(faces[a].embedding @ centroid) if a in faces else 0.0
        sim_b = float(faces[b].embedding @ centroid) if b in faces else 0.0
        assignment[a if sim_a < sim_b else b] = ids.new_id()
    return assignment


def _frontal(face: FaceVec) -> float:
    from yearbook_worker.stages.faces import frontalness

    return frontalness(face.kps) if face.kps is not None else 0.5


def _update_persons(
    conn: psycopg.Connection,
    faces: list[FaceVec],
    assignment: dict[bytes, bytes | None],
    persons: list[PersonRow],
) -> int:
    groups: dict[bytes, list[FaceVec]] = defaultdict(list)
    for f in faces:
        pid = assignment.get(f.id)
        if pid is not None:
            groups[pid].append(f)
    touched = set(groups) | {p.id for p in persons}
    for pid in touched:
        members = groups.get(pid, [])
        if members:
            centroid = weighted_centroid(
                np.stack([m.embedding for m in members]), np.array([m.quality for m in members])
            )
            cover = max(members, key=lambda m: m.quality * (0.5 + 0.5 * _frontal(m)))
            params = {
                "id": pid,
                "face_count": len(members),
                "centroid": centroid.astype(np.float32),
                "cover_face": cover.id,
                "cover_face_quality": cover.quality,
            }
        else:
            params = {
                "id": pid,
                "face_count": 0,
                "centroid": None,
                "cover_face": None,
                "cover_face_quality": None,
            }
        conn.execute(UPDATE_PERSON_SQL, params)
    return len(groups)


# --- evaluation ------------------------------------------------------------------------------

EVAL_SQL = """
select f.id, f.person_id, m.original_filename,
       row_number() over (
         partition by f.media_id
         order by (f.bbox[3] - f.bbox[1]) * (f.bbox[4] - f.bbox[2]) desc
       ) as rank
from faces f join media m on m.id = f.media_id
where f.event_id = %(id)s
"""


def evaluate(conn: psycopg.Connection, event_id: bytes, labels: dict[str, str]) -> dict[str, Any]:
    """Purity / completeness of the current assignment against `labels`.

    Keys are face ids (22 chars) or media file names (then the largest face of that media).
    """
    rows = conn.execute(EVAL_SQL, {"id": event_id}).fetchall()
    truth: dict[bytes, str] = {}
    predicted: dict[bytes, bytes | None] = {}
    for r in rows:
        fid = bytes(r["id"])
        key = ids.encode(fid)
        label = labels.get(key)
        if label is None and r["rank"] == 1 and r["original_filename"]:
            label = labels.get(r["original_filename"])
        if label is None:
            continue
        truth[fid] = label
        predicted[fid] = bytes(r["person_id"]) if r["person_id"] is not None else None
    purity, completeness, clusters = purity_completeness(truth, predicted)
    return {
        "labeled_faces": len(truth),
        "labels": len(set(truth.values())),
        "clusters": clusters,
        "unassigned": sum(1 for v in predicted.values() if v is None),
        "purity": round(purity, 4),
        "completeness": round(completeness, 4),
    }
