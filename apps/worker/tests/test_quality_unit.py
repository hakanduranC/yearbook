"""Quality terms, aesthetic proxy and faces term without models or a database."""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageFilter

from yearbook_worker.analysis import FaceRecord
from yearbook_worker.stages import quality


def _checker(size: int = 320) -> Image.Image:
    rng = np.random.default_rng(1)
    noise = rng.integers(0, 255, size=(size, size), dtype=np.uint8)
    return Image.fromarray(noise, mode="L")


def _face(q: float, eyes: float, smile: float) -> FaceRecord:
    return FaceRecord(
        id=b"\0" * 16, bbox=(0, 0, 100, 100), kps=None, det_score=0.9, quality=q,
        eyes_open=eyes, smile=smile,
    )  # fmt: skip


def test_sharpness_drops_with_blur() -> None:
    sharp = _checker()
    blurred = sharp.filter(ImageFilter.GaussianBlur(6))
    t_sharp = quality.image_terms(np.asarray(sharp))
    t_blur = quality.image_terms(np.asarray(blurred))
    assert t_sharp.sharpness_raw > t_blur.sharpness_raw * 10
    assert 0.0 <= t_blur.sharpness < t_sharp.sharpness <= 1.0


def test_exposure_penalises_clipping_and_rewards_midtones() -> None:
    black = np.zeros((64, 64), dtype=np.uint8)
    white = np.full((64, 64), 255, dtype=np.uint8)
    mid = np.full((64, 64), 115, dtype=np.uint8)
    assert quality.image_terms(mid).exposure == 1.0
    assert quality.image_terms(black).exposure < 0.2
    assert quality.image_terms(white).exposure < 0.2


def test_faces_term_matches_conventions() -> None:
    assert quality.faces_term(0) == 0.6
    assert quality.faces_term(1) == quality.faces_term(6) == 1.0
    assert quality.faces_term(7) == 0.4


def test_aesthetic_proxy_stays_on_the_predictor_scale() -> None:
    terms = quality.ImageTerms(sharpness_raw=500.0, sharpness=0.9, exposure=1.0)
    best = quality.aesthetic_proxy(terms, [_face(1.0, 1.0, 1.0)])
    worst = quality.aesthetic_proxy(
        quality.ImageTerms(sharpness_raw=1.0, sharpness=0.0, exposure=0.0), []
    )
    assert 3.0 <= worst < best <= 8.0
    # the score formula maps (aesthetic-3)/5 to 0..1
    assert 0.0 <= (worst - 3) / 5 <= (best - 3) / 5 <= 1.0


def test_compute_aggregates_face_terms() -> None:
    im = Image.merge("RGB", [_checker(200)] * 3)
    values = quality.compute(im, [_face(0.8, 1.0, 0.2), _face(0.6, 0.5, 0.6)])
    assert values["face_count"] == 2
    assert abs(values["eyes_open"] - 0.75) < 1e-6
    assert abs(values["smile"] - 0.4) < 1e-6
    assert quality.compute(im, [])["eyes_open"] is None
