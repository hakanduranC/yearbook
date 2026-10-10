# One image, three roles (pick the command):
#   yearbook-worker run --kinds ingest,import,recompute_scores        light worker
#   yearbook-worker run --kinds analyze,cluster_event --concurrency 1  ML worker (models resident)
#   yearbook-worker serve --port 8090                                  ML server (text embeddings)
# Models are not baked in: they download on first use into WORKER_MODELS_DIR (/models), mount a
# volume there and share it between the ML worker and the ML server.
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg libgomp1 \
 && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /uvx /bin/

WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

RUN useradd --system --uid 10001 --home /app --shell /usr/sbin/nologin worker \
 && mkdir -p /tmp/yearbook /models && chown -R worker:worker /app /tmp/yearbook /models
USER worker
VOLUME ["/models"]
ENV PATH="/app/.venv/bin:$PATH" WORKER_TMP_DIR=/tmp/yearbook WORKER_MODELS_DIR=/models \
    HF_HUB_DISABLE_TELEMETRY=1 OMP_NUM_THREADS=4
EXPOSE 8090
ENTRYPOINT ["yearbook-worker"]
CMD ["run"]
