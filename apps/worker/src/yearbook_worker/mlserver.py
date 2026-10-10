"""`yearbook-worker serve`: FastAPI with `GET /health` and `POST /embed/text` (SigLIP 2 text tower).

The API calls this for hybrid search (`ML_URL`). Vectors are 1152-d, L2-normalised, in the same
space as `media_embeddings`. de/en/tr input works out of the box (multilingual Gemma tokenizer).
"""

from __future__ import annotations

import threading
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from yearbook_worker.config import Settings
from yearbook_worker.log import get_logger
from yearbook_worker.models import EMBED_DIM, ModelHub, get_hub

log = get_logger(__name__)

MAX_TEXTS = 64
MAX_CHARS = 500


class EmbedTextRequest(BaseModel):
    texts: list[str] = Field(min_length=1, max_length=MAX_TEXTS)


class EmbedTextResponse(BaseModel):
    vectors: list[list[float]]
    model: str


def create_app(settings: Settings, hub: ModelHub | None = None) -> FastAPI:
    hub = hub or get_hub(settings)
    lock = threading.Lock()
    app = FastAPI(title="Yearbook ML server", version="0.1.0", docs_url=None, redoc_url=None)

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "models": hub.loaded(),
            "text_model": settings.worker_siglip_model,
            "dim": EMBED_DIM,
        }

    @app.post("/embed/text", response_model=EmbedTextResponse)
    def embed_text(req: EmbedTextRequest) -> EmbedTextResponse:
        texts = [t.strip()[:MAX_CHARS] for t in req.texts]
        if any(not t for t in texts):
            raise HTTPException(status_code=400, detail="texts must not be empty")
        with lock:
            vectors = hub.embed_texts(texts)
        return EmbedTextResponse(
            vectors=[[float(v) for v in row] for row in vectors], model=hub.siglip_text().name
        )

    return app


def serve(settings: Settings, port: int, *, host: str = "0.0.0.0", warm: bool = True) -> None:
    import uvicorn

    hub = get_hub(settings)
    if warm:
        hub.siglip_text()
    uvicorn.run(
        create_app(settings, hub), host=host, port=port, log_level=settings.worker_log_level.lower()
    )
