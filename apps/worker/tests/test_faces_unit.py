"""Eye / smile / quality heuristics on synthetic landmark geometry (no models)."""

from __future__ import annotations

import numpy as np

from yearbook_worker.stages.faces import (
    LEFT_EYE,
    MOUTH,
    RIGHT_EYE,
    eye_aspect_ratio,
    eyes_open_score,
    face_quality,
    frontalness,
    padded_box,
    smile_score,
)


def _ellipse(cx: float, cy: float, rx: float, ry: float, n: int) -> np.ndarray:
    t = np.linspace(0, 2 * np.pi, n, endpoint=False)
    return np.stack([cx + rx * np.cos(t), cy + ry * np.sin(t)], axis=1)


def _landmarks(eye_ry: float, mouth_w: float, corner_lift: float) -> tuple[np.ndarray, np.ndarray]:
    lm = np.zeros((106, 2), dtype=np.float32)
    lm[LEFT_EYE[0] : LEFT_EYE[1] + 1] = _ellipse(100, 100, 20, eye_ry, 10)
    lm[RIGHT_EYE[0] : RIGHT_EYE[1] + 1] = _ellipse(200, 100, 20, eye_ry, 10)
    mouth = _ellipse(150, 200, mouth_w / 2, 10, MOUTH[1] - MOUTH[0] + 1)
    lm[MOUTH[0] : MOUTH[1] + 1] = mouth
    lm[52] = (150 - mouth_w / 2, 200 - corner_lift)
    lm[61] = (150 + mouth_w / 2, 200 - corner_lift)
    lm[71] = (150, 192)
    lm[53] = (150, 208)
    kps = np.array([[100, 100], [200, 100], [150, 150], [120, 200], [180, 200]], dtype=np.float32)
    return lm, kps


def test_eye_aspect_ratio_is_rotation_invariant() -> None:
    pts = _ellipse(0, 0, 20, 6, 10)
    theta = 0.7
    rot = np.array([[np.cos(theta), -np.sin(theta)], [np.sin(theta), np.cos(theta)]])
    assert abs(eye_aspect_ratio(pts) - eye_aspect_ratio(pts @ rot.T)) < 1e-6
    assert eye_aspect_ratio(np.zeros((10, 2))) == 0.0


def test_eyes_open_score_orders_open_over_closed() -> None:
    open_lm, _ = _landmarks(eye_ry=7, mouth_w=140, corner_lift=0)
    closed_lm, _ = _landmarks(eye_ry=1.5, mouth_w=140, corner_lift=0)
    assert eyes_open_score(open_lm) > 0.8
    assert eyes_open_score(closed_lm) < 0.1


def test_smile_score_orders_smile_over_neutral() -> None:
    neutral, kps = _landmarks(eye_ry=6, mouth_w=80, corner_lift=0)
    smile, _ = _landmarks(eye_ry=6, mouth_w=110, corner_lift=22)
    assert smile_score(neutral, kps) < 0.25
    assert smile_score(smile, kps) > 0.7


def test_face_quality_and_frontalness() -> None:
    assert face_quality(0.95, 200, 800) > 0.9
    assert face_quality(0.6, 32, 5) < 0.2
    frontal = np.array([[100, 100], [200, 100], [150, 150], [120, 200], [180, 200]], float)
    profile = frontal.copy()
    profile[2, 0] = 215
    assert frontalness(frontal) == 1.0
    assert frontalness(profile) < 0.1


def test_padded_box_clips_to_image() -> None:
    assert padded_box((10, 10, 110, 110), 200, 200) == (0, 0, 130, 130)
    assert padded_box((150, 150, 199, 199), 200, 200) == (140, 140, 200, 200)
