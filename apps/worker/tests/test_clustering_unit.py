"""Clustering building blocks on synthetic unit vectors (no models, no database)."""

from __future__ import annotations

import numpy as np

from yearbook_worker import ids
from yearbook_worker.clustering import (
    FaceVec,
    apply_constraints,
    assign_to_centroids,
    cluster_vectors,
    map_clusters_to_persons,
    normalize,
    purity_completeness,
    weighted_centroid,
)

rng = np.random.default_rng(7)


def _identity(dim: int = 512) -> np.ndarray:
    return normalize(rng.normal(size=dim))


def _near(center: np.ndarray, spread: float = 0.8) -> np.ndarray:
    """A unit vector at cosine ≈ 1/sqrt(1+spread²) (0.78 by default) to `center`."""
    return normalize(center + rng.normal(size=center.shape) * spread / np.sqrt(center.shape[0]))


def test_assign_to_centroids_thresholds_and_margin() -> None:
    a, b = _identity(), _identity()
    cents = np.stack([a, b])
    close_to_a = normalize(a * 0.9 + rng.normal(size=512) * 0.02)
    between = normalize(a + b)
    far = _identity()
    picks = assign_to_centroids(
        np.stack([close_to_a, between, far]), np.array([0.9, 0.9, 0.9]), cents
    )
    assert picks[0] == 0  # clear match
    assert picks[1] is None  # cos ≥ 0.52 to both but no margin
    assert picks[2] is None  # below threshold
    # low quality faces need ≥ 0.6
    mid = normalize(a * 0.56 + np.sqrt(1 - 0.56**2) * normalize(rng.normal(size=512)))
    assert assign_to_centroids(mid[None], np.array([0.9]), cents)[0] == 0
    assert assign_to_centroids(mid[None], np.array([0.2]), cents)[0] is None


def test_cluster_vectors_finds_tight_groups_and_noise() -> None:
    centers = [_identity() for _ in range(3)]
    vectors = []
    truth = []
    for i, c in enumerate(centers):
        for _ in range(4):
            vectors.append(_near(c))
            truth.append(i)
    vectors.append(_identity())  # a loner
    truth.append(-1)
    labels = cluster_vectors(np.stack(vectors))
    assert labels[-1] == -1
    found = {}
    for label, t in zip(labels[:-1], truth[:-1], strict=True):
        assert label >= 0
        found.setdefault(t, set()).add(int(label))
    assert all(len(s) == 1 for s in found.values())
    assert len({next(iter(s)) for s in found.values()}) == 3


def test_cluster_vectors_small_inputs() -> None:
    assert cluster_vectors(np.zeros((0, 512))).tolist() == []
    assert cluster_vectors(_identity()[None]).tolist() == [-1]
    pair = _identity()
    assert cluster_vectors(np.stack([pair, _near(pair)])).tolist() == [0, 0]


def test_map_clusters_to_persons_by_overlap() -> None:
    p1, p2 = ids.new_id(), ids.new_id()
    labels = np.array([0, 0, 0, 1, 1, 2, -1])
    prior = [p1, p1, p2, p2, None, None, p1]
    mapping = map_clusters_to_persons(labels, prior)
    assert mapping == {0: p1, 1: p2, 2: None}


def _face(pid: bytes | None, vec: np.ndarray, q: float = 0.9) -> FaceVec:
    from datetime import UTC, datetime

    return FaceVec(ids.new_id(), ids.new_id(), pid, vec, q, None, datetime.now(UTC))


def test_apply_constraints_must_and_cannot_link() -> None:
    a_center, b_center = _identity(), _identity()
    pa, pb = ids.new_id(), ids.new_id()
    fa1, fa2 = _face(pa, _near(a_center)), _face(pa, _near(a_center))
    fb1 = _face(pb, _near(b_center))
    loner = _face(None, _identity())
    faces = {f.id: f for f in (fa1, fa2, fb1, loner)}
    assignment = {f.id: f.person_id for f in faces.values()}

    merged = apply_constraints(assignment, faces, [(fa1.id, fb1.id, "must_link")])
    assert merged[fb1.id] == pa  # smaller group joins the larger

    attached = apply_constraints(assignment, faces, [(loner.id, fa1.id, "must_link")])
    assert attached[loner.id] == pa

    outlier = _face(pa, _near(b_center))  # sits in pa but looks like b
    faces[outlier.id] = outlier
    assignment[outlier.id] = pa
    split = apply_constraints(assignment, faces, [(fa1.id, outlier.id, "cannot_link")])
    assert split[fa1.id] == pa and split[outlier.id] not in {pa, pb, None}


def test_weighted_centroid_prefers_quality() -> None:
    a, b = _identity(), _identity()
    c = weighted_centroid(np.stack([a, b]), np.array([1.0, 0.05]))
    assert float(c @ a) > float(c @ b)
    assert abs(float(np.linalg.norm(c)) - 1.0) < 1e-5


def test_purity_completeness() -> None:
    f = [ids.new_id() for _ in range(6)]
    p1, p2 = ids.new_id(), ids.new_id()
    truth = {f[0]: "a", f[1]: "a", f[2]: "a", f[3]: "b", f[4]: "b", f[5]: "b"}
    perfect = {f[0]: p1, f[1]: p1, f[2]: p1, f[3]: p2, f[4]: p2, f[5]: p2}
    assert purity_completeness(truth, perfect) == (1.0, 1.0, 2)
    mixed = {f[0]: p1, f[1]: p1, f[2]: p2, f[3]: p2, f[4]: p2, f[5]: None}
    purity, completeness, clusters = purity_completeness(truth, mixed)
    assert clusters == 2
    assert abs(purity - 5 / 6) < 1e-9  # p1: 2 of 2 "a"; p2: 2 of 3 "b"; noise singleton: 1
    assert abs(completeness - 4 / 6) < 1e-9  # a: 2 in p1; b: 2 in p2
