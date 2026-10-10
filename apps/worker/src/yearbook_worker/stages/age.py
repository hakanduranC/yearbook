"""age: MiVOLO v2 per face (face crop only; `body_bbox` stays null) → `faces.age_est(_sd)`.

`age_est_sd` is not a model output: MiVOLO v2 reports a mean absolute error around 4 years on
its benchmarks for face-only input, so the stored spread starts there and widens for small or
low-quality faces. Good enough for the `|age_est - exact_age| <= 6` rule in CONVENTIONS.
"""

from __future__ import annotations

import numpy as np
import psycopg

from yearbook_worker.analysis import AnalysisContext, FaceRecord

BASE_SD = 4.0

UPDATE_SQL = "update faces set age_est = %(age)s, age_est_sd = %(sd)s where id = %(id)s"


def age_sd(face: FaceRecord) -> float:
    min_side = min(face.bbox[2] - face.bbox[0], face.bbox[3] - face.bbox[1])
    sd = BASE_SD + 3.0 * (1.0 - face.quality)
    if min_side < 48:
        sd += 2.0
    return round(sd, 2)


def face_crop(ctx: AnalysisContext, face: FaceRecord) -> np.ndarray | None:
    scale = ctx.scale
    x1, y1, x2, y2 = (round(v / scale) for v in face.bbox)
    rgb = np.asarray(ctx.image)
    crop = rgb[max(0, y1) : max(0, y2), max(0, x1) : max(0, x2)]
    return crop if crop.size else None


def run(ctx: AnalysisContext, conn: psycopg.Connection) -> None:
    if not ctx.faces:
        return
    crops = [face_crop(ctx, f) for f in ctx.faces]
    ages = ctx.hub.age().predict_ages(crops)
    for face, age in zip(ctx.faces, ages, strict=True):
        face.age_est = float(age)
        conn.execute(UPDATE_SQL, {"id": face.id, "age": round(float(age), 1), "sd": age_sd(face)})
