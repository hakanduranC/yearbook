FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /uvx /bin/

WORKDIR /app
RUN groupadd --system agent && useradd --system --gid agent --home /app agent

# Dependencies first, so source edits do not invalidate the layer.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
COPY evals ./evals
COPY README.md ./
RUN uv sync --frozen --no-dev && chown -R agent:agent /app

USER agent
ENV PATH="/app/.venv/bin:$PATH" AGENT_PORT=8091
EXPOSE 8091
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8091/health', timeout=2).status == 200 else 1)"
CMD ["yearbook-agent", "serve"]
