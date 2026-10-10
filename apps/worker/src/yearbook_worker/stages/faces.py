"""faces: detect, align, embed (ArcFace 512-d), eyes/smile/quality heuristics, private crops.

Runs on the `large` variant; boxes and the 5 key points are stored in original pixels. Skipped
(no rows, stage still recorded) when the event has `faces_enabled = false`; library items of a
user are always processed. Videos are analysed on their poster frame (the `large` variant).
"""

from __future__ import annotations

import io
from dataclasses import dataclass

import cv2
import numpy as np
import psycopg
from PIL import Image

from yearbook_worker import ids
from yearbook_worker.analysis import AnalysisContext, FaceRecord
from yearbook_worker.models import RawFace

CROP_PADDING = 0.20
CROP_MAX_SIDE = 512
CROP_QUALITY = 88
LOW_QUALITY = 0.4

# InsightFace 2d106 landmark layout (verified on the fixture portraits):
# contour 0-32, left eye 33-42 (corners 35/39), left brow 43-51, mouth 52-71 (corners 52/61,
# top centre 71, bottom centre 53), nose 72-86, right eye 87-96 (corners 93/89), right brow 97-105.
LEFT_EYE = (33, 42)
RIGHT_EYE = (87, 96)
MOUTH = (52, 71)

INSERT_SQL = """
insert into faces (id, media_id, event_id, bbox, landmarks, det_score, quality, embedding,
                   eyes_open, smile, crop_key)
values (%(id)s, %(media_id)s, %(event_id)s, %(bbox)s, %(landmarks)s, %(det_score)s, %(quality)s,
        %(embedding)s, %(eyes_open)s, %(smile)s, %(crop_key)s)
"""


@dataclass(frozen=True, slots=True)
class FaceScores:
    eyes_open: float
    smile: float
    quality: float


# --- heuristics (pure numpy, unit tested) ---------------------------------------------------


def clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return float(min(hi, max(lo, value)))


def eye_aspect_ratio(points: np.ndarray) -> float:
    """Opening / width of one eye's landmark set, independent of point ordering.

    Width is the extent along the principal axis, opening the extent perpendicular to it.
    Open eyes sit around 0.25-0.4, closed ones below 0.12.
    """
    pts = np.asarray(points, dtype=np.float64)
    centered = pts - pts.mean(axis=0)
    _, _, vt = np.linalg.svd(centered, full_matrices=False)
    along = centered @ vt[0]
    across = centered @ vt[1]
    width = float(along.max() - along.min())
    if width <= 1e-6:
        return 0.0
    return float((across.max() - across.min()) / width)


def eyes_open_score(landmarks: np.ndarray) -> float:
    """0 closed .. 1 wide open from the mean eye aspect ratio of both eyes."""
    left = landmarks[LEFT_EYE[0] : LEFT_EYE[1] + 1]
    right = landmarks[RIGHT_EYE[0] : RIGHT_EYE[1] + 1]
    ear = (eye_aspect_ratio(left) + eye_aspect_ratio(right)) / 2
    return clamp((ear - 0.12) / (0.30 - 0.12))


def smile_score(landmarks: np.ndarray, kps: np.ndarray) -> float:
    """0 neutral .. 1 broad smile from mouth width (vs. inter-ocular distance), corner lift
    and mouth opening. Ranges come from the 2d106 geometry on the portrait fixtures: neutral
    mouths sit near 0.8 x the eye distance, broad smiles above 1.05."""
    mouth = landmarks[MOUTH[0] : MOUTH[1] + 1]
    left_corner, right_corner = landmarks[52], landmarks[61]
    width = float(np.linalg.norm(right_corner - left_corner))
    iod = float(np.linalg.norm(kps[1] - kps[0]))
    if width <= 1e-6 or iod <= 1e-6:
        return 0.0
    width_term = clamp((width / iod - 0.80) / (1.10 - 0.80))
    centre_y = float((landmarks[71][1] + landmarks[53][1]) / 2)
    corner_y = float((left_corner[1] + right_corner[1]) / 2)
    lift_term = clamp(((centre_y - corner_y) / width - 0.08) / (0.20 - 0.08))
    mouth_h = float(mouth[:, 1].max() - mouth[:, 1].min())
    open_term = clamp((mouth_h / width - 0.20) / (0.50 - 0.20))  # teeth showing
    return clamp(0.5 * width_term + 0.35 * lift_term + 0.25 * open_term)


def crop_sharpness(aligned_bgr: np.ndarray) -> float:
    """Laplacian variance of the aligned 112 px crop."""
    gray = cv2.cvtColor(aligned_bgr, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_32F).var())


def face_quality(det_score: float, min_side_px: float, sharpness: float) -> float:
    """0..1 from detector confidence, size in original pixels and crop sharpness."""
    det_term = clamp((det_score - 0.5) / 0.45)
    size_term = clamp((min_side_px - 32) / (140 - 32))
    sharp_term = clamp(np.log10(1 + sharpness) / 2.6)
    return clamp(0.4 * det_term + 0.3 * size_term + 0.3 * sharp_term)


def frontalness(kps: np.ndarray) -> float:
    """1 when the nose sits between the eyes, 0 for a full profile (5-point key points)."""
    left, right, nose = kps[0], kps[1], kps[2]
    iod = float(np.linalg.norm(right - left))
    if iod <= 1e-6:
        return 0.0
    mid_x = float((left[0] + right[0]) / 2)
    return clamp(1.0 - abs(float(nose[0]) - mid_x) / (0.5 * iod))


def score_face(face: RawFace, min_side_px: float) -> FaceScores:
    return FaceScores(
        eyes_open=eyes_open_score(face.landmarks),
        smile=smile_score(face.landmarks, face.kps),
        quality=face_quality(face.det_score, min_side_px, crop_sharpness(face.aligned)),
    )


def padded_box(
    bbox: tuple[float, float, float, float], width: int, height: int, padding: float = CROP_PADDING
) -> tuple[int, int, int, int]:
    x1, y1, x2, y2 = bbox
    pw, ph = (x2 - x1) * padding, (y2 - y1) * padding
    return (
        max(0, int(np.floor(x1 - pw))),
        max(0, int(np.floor(y1 - ph))),
        min(width, int(np.ceil(x2 + pw))),
        min(height, int(np.ceil(y2 + ph))),
    )


def encode_crop(image: Image.Image, bbox: tuple[float, float, float, float]) -> bytes:
    """20 % padded JPEG crop, longest side at most 512 px."""
    box = padded_box(bbox, image.width, image.height)
    crop = image.crop(box)
    longest = max(crop.size)
    if longest > CROP_MAX_SIDE:
        ratio = CROP_MAX_SIDE / longest
        crop = crop.resize(
            (max(1, round(crop.width * ratio)), max(1, round(crop.height * ratio))),
            Image.Resampling.LANCZOS,
        )
    buf = io.BytesIO()
    crop.save(buf, format="JPEG", quality=CROP_QUALITY, optimize=True)
    return buf.getvalue()


def crop_key(face_id: bytes) -> str:
    return f"f/{ids.encode(face_id)}.jpg"


# --- stage -----------------------------------------------------------------------------------


def restore(ctx: AnalysisContext, conn: psycopg.Connection) -> None:
    ctx.load_faces(conn)
    ctx.faces_ran = ctx.media.event_id is None or ctx.faces_enabled


def run(ctx: AnalysisContext, conn: psycopg.Connection) -> None:
    media = ctx.media
    # Idempotent: a crashed earlier attempt may have written some rows without recording.
    conn.execute("delete from faces where media_id = %s", (media.id,))
    ctx.faces = []
    if media.event_id is not None and not ctx.faces_enabled:
        ctx.faces_ran = False
        return
    ctx.faces_ran = True

    image = ctx.image
    bgr = np.ascontiguousarray(np.asarray(image)[:, :, ::-1])
    scale = ctx.scale
    orig_w = media.width or image.width
    orig_h = media.height or image.height
    settings = ctx.settings

    for raw in ctx.hub.faces().detect(bgr):
        if raw.det_score < settings.worker_face_det_thresh:
            continue
        x1, y1, x2, y2 = (float(v) for v in raw.bbox)
        ob = (
            max(0, round(x1 * scale)),
            max(0, round(y1 * scale)),
            min(orig_w, round(x2 * scale)),
            min(orig_h, round(y2 * scale)),
        )
        min_side = min(ob[2] - ob[0], ob[3] - ob[1])
        if min_side < settings.worker_face_min_side:
            continue
        scores = score_face(raw, min_side)
        face_id = ids.new_id()
        key = crop_key(face_id)
        ctx.storage.upload_bytes(
            ctx.storage.private_bucket, key, encode_crop(image, (x1, y1, x2, y2)), "image/jpeg"
        )
        kps_orig = (raw.kps * scale).astype(np.float32)
        conn.execute(
            INSERT_SQL,
            {
                "id": face_id,
                "media_id": media.id,
                "event_id": media.event_id,
                "bbox": list(ob),
                "landmarks": [float(v) for v in kps_orig.reshape(-1)],
                "det_score": raw.det_score,
                "quality": scores.quality,
                "embedding": raw.embedding.astype(np.float32),
                "eyes_open": scores.eyes_open,
                "smile": scores.smile,
                "crop_key": key,
            },
        )
        ctx.faces.append(
            FaceRecord(
                id=face_id,
                bbox=ob,
                kps=kps_orig,
                det_score=raw.det_score,
                quality=scores.quality,
                eyes_open=scores.eyes_open,
                smile=scores.smile,
            )
        )
