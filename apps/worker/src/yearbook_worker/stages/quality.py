"""quality: sharpness, exposure, aesthetic (proxy), face terms → `media_quality` + score.

Aesthetic: aesthetic-predictor-v2.5 is a head trained on SigLIP (v1) so400m features; its
weights do not transfer to the SigLIP 2 feature space this worker stores, so `aesthetic` is a
documented proxy on the predictor's 1..10 scale built from sharpness, exposure and the face
terms. Swap `aesthetic_proxy` for a real head when one exists for SigLIP 2.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
import psycopg
from PIL import Image

from yearbook_worker import scoring
from yearbook_worker.analysis import AnalysisContext, FaceRecord
from yearbook_worker.stages.variants import resize_long_edge

UPSERT_SQL = """
insert into media_quality (media_id, sharpness, exposure, aesthetic, face_count, eyes_open, smile)
values (%(media_id)s, %(sharpness)s, %(exposure)s, %(aesthetic)s, %(face_count)s, %(eyes_open)s,
        %(smile)s)
on conflict (media_id) do update
set sharpness = excluded.sharpness, exposure = excluded.exposure, aesthetic = excluded.aesthetic,
    face_count = excluded.face_count, eyes_open = excluded.eyes_open, smile = excluded.smile
"""


@dataclass(frozen=True, slots=True)
class ImageTerms:
    sharpness_raw: float  # Laplacian variance of the 640 px grayscale
    sharpness: float  # log-scaled 0..1
    exposure: float  # 0 badly clipped or very dark/bright .. 1 well exposed


def clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return float(min(hi, max(lo, value)))


def image_terms(gray: np.ndarray) -> ImageTerms:
    """`gray` is a uint8 2-D array (the 640 px working copy)."""
    g = np.asarray(gray, dtype=np.uint8)
    var = float(cv2.Laplacian(g, cv2.CV_32F).var())
    sharp = clamp(np.log10(1.0 + var) / 3.0)
    dark = float(np.mean(g < 8))
    bright = float(np.mean(g > 247))
    mean = float(g.mean()) / 255.0
    clipping = clamp((dark + bright - 0.02) / 0.30)
    off_centre = clamp((abs(mean - 0.45) - 0.12) / 0.30)
    exposure = clamp(1.0 - 0.6 * clipping - 0.4 * off_centre)
    return ImageTerms(sharpness_raw=var, sharpness=sharp, exposure=exposure)


def faces_term(face_count: int) -> float:
    if face_count == 0:
        return 0.6
    return 1.0 if face_count <= 6 else 0.4


def aesthetic_proxy(terms: ImageTerms, faces: list[FaceRecord]) -> float:
    """Proxy on the 1..10 aesthetic scale (so `(aesthetic-3)/5` still maps to 0..1)."""
    if faces:
        subject = float(np.mean([f.quality for f in faces]))
        expression = float(
            np.mean([(f.eyes_open or 0.5) * 0.5 + (f.smile or 0.0) * 0.5 for f in faces])
        )
    else:
        subject, expression = 0.5, 0.5
    unit = 0.40 * terms.sharpness + 0.25 * terms.exposure + 0.20 * subject + 0.15 * expression
    return round(3.0 + 5.0 * clamp(unit), 3)


def compute(image: Image.Image, faces: list[FaceRecord]) -> dict[str, float | int | None]:
    gray = np.asarray(resize_long_edge(image, 640).convert("L"))
    terms = image_terms(gray)
    eyes = [f.eyes_open for f in faces if f.eyes_open is not None]
    smiles = [f.smile for f in faces if f.smile is not None]
    return {
        "sharpness": terms.sharpness,
        "sharpness_raw": terms.sharpness_raw,
        "exposure": terms.exposure,
        "aesthetic": aesthetic_proxy(terms, faces),
        "face_count": len(faces),
        "eyes_open": float(np.mean(eyes)) if eyes else None,
        "smile": float(np.mean(smiles)) if smiles else None,
    }


def run(ctx: AnalysisContext, conn: psycopg.Connection) -> None:
    values = compute(ctx.image, ctx.faces)
    conn.execute(UPSERT_SQL, {"media_id": ctx.media.id, **values})
    scoring.update_scores(
        conn, event_id=ctx.media.event_id, owner_id=ctx.media.owner_id, media_id=ctx.media.id
    )
