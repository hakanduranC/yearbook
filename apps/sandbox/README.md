# yearbook-sandbox

Runs agent-written Python in a fresh, network-less container per request. It is the only
component of Yearbook allowed to talk to Docker; the agent service only speaks HTTP to it.
Contract and limits: `docs/CONVENTIONS.md`, section "Sandbox (agent-created tools)".

```
sh image/build.sh                       # builds yearbook-sandbox:latest (once, and after bumping pins)
uv run yearbook-sandbox serve --port 8092
uv run ruff check . && uv run pytest -q # pytest -m docker needs the socket and the image
```

`mise run sandbox` does the first two from the repo root.

## API

`POST /run`

```json
{"code": "import json; print(json.dumps(json.load(open('/work/inputs.json'))))",
 "inputs": {"people": ["Anna"]},
 "files": [{"name": "a.jpg", "url": "http://localhost:8333/yearbook-public/..."}],
 "timeout_s": 10}
```

| field | limit |
|---|---|
| `code` | 1 to 20 000 chars; refused with 400 `forbidden_token` if it contains `socket`, `subprocess`, `ctypes`, `os.system`, `importlib` or `__import__` as a whole word. This is a cheap pre-flight for the model's benefit, not the boundary |
| `inputs` | JSON object, at most 1 MB serialised; becomes `/work/inputs.json` |
| `files` | at most 20, each at most 25 MB, names `[A-Za-z0-9][A-Za-z0-9._-]{0,127}`; fetched by the service (10 s timeout, no redirects) into `/work/in/<name>`. The URL host must be one of the hosts of `PUBLIC_BASE_URL`, `S3_ENDPOINT`, `S3_PRESIGN_ENDPOINT` (or `SANDBOX_ALLOWED_HOSTS`); anything else is 400 `url_not_allowed` and no container starts |
| `timeout_s` | 1 to 20, default 10; the container is killed hard when it elapses |

Response:

```json
{"exit_code": 0, "stdout": "...", "stderr": "", "duration_ms": 412, "timed_out": false,
 "oom_killed": false,
 "files": [{"name": "plot.png", "mime": "image/png", "size": 1234, "bytes_b64": "..."}],
 "warnings": ["script.py: type '.py' not allowed, skipped"]}
```

- `stdout` and `stderr` are cut at 1 MiB each with a `[sandbox: output truncated at 1 MiB]` marker.
- `files` come from `/work/out`: regular files only (symlinks and directories are skipped, never
  followed), types png, jpeg, webp, pdf (checked by magic bytes) and csv, json, txt (must be
  UTF-8), at most 10 files and 50 MB in total; anything beyond that is listed in `warnings`.
- `exit_code` is 137 after a kill (timeout or OOM); `oom_killed` tells the two apart.

Errors use FastAPI's `{"detail": {"code", "message", ...}}` shape: 400 (`forbidden_token`,
`url_not_allowed`, `fetch_failed`, `file_too_large`), 422 (schema), 429 `busy` with `Retry-After: 5`
when all `SANDBOX_MAX_PARALLEL` slots stayed busy for 5 s, 503 `unavailable` when Docker or the
image went away.

`GET /health` returns Docker reachability, image presence and id, runtime, slots and in-flight
runs; 503 when not usable. At start-up the service refuses to run without the image (it prints
the build command) and performs one real self-check run, which also catches an unshared or
mis-mounted work directory ("mounts denied").

## What the boundary is

**In dev (Docker Desktop)** the daemon runs inside Docker Desktop's Linux VM, so even a full
container escape lands in that VM, not on the workstation. Inside the VM each run is one
container with:

- `--network none`: no interface besides loopback; `urlopen` fails in milliseconds.
- read-only root filesystem; the only writable places are the tmpfs `/work` (256 MB) and
  `/tmp` (64 MB), which vanish with the container, plus the bind-mounted `/work/out`.
- `/work/in`, `/work/main.py`, `/work/inputs.json` bind-mounted read-only.
- 512 MB memory with swap disabled (`--memory-swap` equal to `--memory`), 1 CPU, 64 pids,
  all capabilities dropped, `no-new-privileges`, Docker's default seccomp and AppArmor
  profiles, non-root uid 10002, `--init` so the kill reaches every process.
- an empty environment apart from Python and matplotlib settings; nothing of the service's
  environment is passed in.
- a hard `docker kill` at `timeout_s`, then `docker rm -f` in every code path.

The image has no shell tools worth mentioning, no pip, and the base image is pinned by digest.
`tests/test_docker.py` demonstrates each of these against the real daemon (network, read-only
root, fork bomb, infinite loop, 1 GiB allocation, 3 MB output, matplotlib/pandas output, host
allowlist). The one thing the container cannot bound is how much the program writes to
`/work/out` within its time budget on the host disk; the service refuses to return more than
50 MB and deletes the directory afterwards.

**In production** the same containers run under gVisor: install `runsc` on the VPS, register it
in `/etc/docker/daemon.json` (`{"runtimes": {"runsc": {"path": "/usr/local/bin/runsc"}}}`), and
set `SANDBOX_RUNTIME=runsc`. The service then passes `--runtime runsc`; nothing else changes.
gVisor puts a user-space kernel between the program and the host kernel, which is the layer
runc-based containers lack. `GET /health` reports the runtime in use.

**On Kubernetes** the equivalent is a `RuntimeClass` (gVisor, Kata Containers or Firecracker via
Kata) and a `runtimeClassName` on the pod; the service would then create pods or jobs through the
API server instead of containers through a socket. That is a different runner behind the same
HTTP contract and not written yet.

**Managed alternative**: E2B (or a similar sandbox-as-a-service) offers Firecracker microVMs per
run over an API. It removes the socket from our stack entirely at the cost of sending the
program and its inputs to a third party, which the privacy rules allow only if no faces,
embeddings, birthdates, emails or GPS values are in `inputs` or `files`. Today the files passed
to the sandbox are media variants, so E2B would need the agent to restrict what it forwards.

## The exact `docker run` of one execution

What `DockerRunner.container_config` sends, as a command line (`$RUN` is the per-run directory
under `SANDBOX_WORK_DIR`, `$ID` the run id). Keep this block and that method in sync.

```sh
docker run --name ybsb-$ID --detach --init \
  --user 10002:10002 --workdir /work --hostname sandbox \
  --network none --read-only \
  --tmpfs /work:size=256m,mode=1777 --tmpfs /tmp:size=64m,mode=1777 \
  --mount type=bind,src=$RUN/in,dst=/work/in,readonly \
  --mount type=bind,src=$RUN/out,dst=/work/out \
  --mount type=bind,src=$RUN/main.py,dst=/work/main.py,readonly \
  --mount type=bind,src=$RUN/inputs.json,dst=/work/inputs.json,readonly \
  --memory 512m --memory-swap 512m --cpus 1 --pids-limit 64 \
  --cap-drop ALL --security-opt no-new-privileges \
  --env PYTHONDONTWRITEBYTECODE=1 --env PYTHONUNBUFFERED=1 --env PYTHONSAFEPATH=1 \
  --env HOME=/tmp --env MPLBACKEND=Agg --env MPLCONFIGDIR=/tmp/mpl --env LANG=C.UTF-8 \
  --log-driver json-file --log-opt max-size=16m --log-opt max-file=1 \
  --label app=yearbook --label yearbook.sandbox=1 --label yearbook.run_id=$ID \
  ${SANDBOX_RUNTIME:+--runtime $SANDBOX_RUNTIME} \
  yearbook-sandbox:latest python /work/main.py
# then: docker wait (timeout_s) || docker kill; docker logs; collect $RUN/out; docker rm -f -v
```

Containers carry the label `yearbook.sandbox=1`, so `docker ps -a --filter label=yearbook.sandbox=1`
must be empty whenever the service is idle.

## Environment

| variable | default | meaning |
|---|---|---|
| `SANDBOX_IMAGE` | `yearbook-sandbox:latest` | image to run; `image/build.sh` honours it too |
| `SANDBOX_MAX_PARALLEL` | `2` | concurrent containers; more requests queue up to `SANDBOX_QUEUE_WAIT_S` (5) seconds, then 429 |
| `SANDBOX_RUNTIME` | empty (runc) | OCI runtime, `runsc` for gVisor |
| `SANDBOX_WORK_DIR` | `~/.cache/yearbook-sandbox` | per-run directories. Docker Desktop shares the home directory with its VM but not `/tmp`, so keep it under home in dev. When the service runs in a container, bind-mount the host directory at the same path (`/var/lib/yearbook-sandbox:/var/lib/yearbook-sandbox`) |
| `SANDBOX_ALLOWED_HOSTS` | empty | extra `host[:port]` entries for file URLs, comma separated |
| `PUBLIC_BASE_URL`, `S3_ENDPOINT`, `S3_PRESIGN_ENDPOINT` | from `.env` | their hosts form the file URL allowlist |
| `DOCKER_HOST`, `DOCKER_CERT_PATH`, ... | | read by the Docker SDK (`docker.from_env`) |

## Running the service itself in a container

`Dockerfile` builds the service. It must get the Docker socket (`-v /var/run/docker.sock:/var/run/docker.sock`)
and the work directory at the same host path; in `infra/compose.yaml` it is the only service with
the socket. The process runs as uid 10003, so add the host's docker group:
`group_add: ["${DOCKER_GID}"]`. Holding the socket is equivalent to root on the host, which is why
gVisor for the programs and a dedicated host (or later a Kubernetes RuntimeClass) for the service
are the production shape.

## Limitations

- The per-run directories are on the host; file names are random but the directory is
  world-traversable (`0755`) so uid 10002 can read it. Do not point `SANDBOX_WORK_DIR` at a
  shared location.
- Output floods above 16 MB rotate Docker's log file; what is returned is then the last chunk,
  cut to 1 MiB, instead of the head.
- Writes to `/work/out` are bounded only by time and host disk; the 50 MB cap is enforced
  after the run.
- On a native Linux host, directories the program creates in `/work/out` are owned by uid 10002;
  the service removes them with a root helper container on the same image when `rm -rf` fails.
- The service runs one Docker call chain per request in a worker thread; `SANDBOX_MAX_PARALLEL`
  is the only back-pressure.
