"""embed: SigLIP 2 so400m image embedding (1152-d, L2-normalised) → `media_embeddings`."""

from __future__ import annotations

import numpy as np
import psycopg

from yearbook_worker.analysis import AnalysisContext
from yearbook_worker.models import EMBED_DIM
from yearbook_worker.stages.variants import resize_long_edge

UPSERT_SQL = """
insert into media_embeddings (media_id, model, embedding)
values (%(media_id)s, %(model)s, %(embedding)s)
on conflict (media_id) do update set model = excluded.model, embedding = excluded.embedding
"""


def run(ctx: AnalysisContext, conn: psycopg.Connection) -> None:
    # The processor squashes to 384x384; feeding a 768 px copy keeps the resample cheap.
    image = resize_long_edge(ctx.image, 768)
    vector = ctx.hub.embed_images([image])[0].astype(np.float32)
    if vector.shape != (EMBED_DIM,):
        raise RuntimeError(f"embedding has {vector.shape}, expected ({EMBED_DIM},)")
    ctx.embedding = vector
    conn.execute(
        UPSERT_SQL,
        {"media_id": ctx.media.id, "model": ctx.hub.siglip_vision().name, "embedding": vector},
    )
