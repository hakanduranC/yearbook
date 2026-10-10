FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg \
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
 && mkdir -p /tmp/yearbook && chown -R worker:worker /app /tmp/yearbook
USER worker
ENV PATH="/app/.venv/bin:$PATH" WORKER_TMP_DIR=/tmp/yearbook
ENTRYPOINT ["yearbook-worker"]
CMD ["run"]
