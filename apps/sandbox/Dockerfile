# The sandbox SERVICE (not the sandbox image; that is image/Dockerfile).
#
# !!! This container needs the Docker socket mounted at run time:
# !!!     -v /var/run/docker.sock:/var/run/docker.sock
# !!! Whoever holds that socket is root on the host. In Compose this is the ONLY service with it.
# !!! It also needs the run directory bind-mounted from the host at the SAME path
# !!! (see SANDBOX_WORK_DIR below), because the paths it hands to Docker are host paths.
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /uvx /bin/

WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# Runs as its own user. Give it the host's docker group at run time so it may use the socket:
#   group_add: ["${DOCKER_GID}"]   (DOCKER_GID from `getent group docker | cut -d: -f3`)
RUN useradd --system --uid 10003 --home /app --shell /usr/sbin/nologin sandbox \
 && mkdir -p /var/lib/yearbook-sandbox && chown sandbox:sandbox /app /var/lib/yearbook-sandbox
USER sandbox
ENV PATH="/app/.venv/bin:$PATH" SANDBOX_WORK_DIR=/var/lib/yearbook-sandbox
EXPOSE 8092
ENTRYPOINT ["yearbook-sandbox"]
CMD ["serve", "--port", "8092"]
