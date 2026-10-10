"""Hardening checks against real containers. `pytest -m docker` needs the Docker socket and the
yearbook-sandbox:latest image (sh image/build.sh)."""

from __future__ import annotations

import base64
import json
import time

import pytest
from fastapi.testclient import TestClient

from tests.conftest import TIMINGS
from yearbook_sandbox.runner import DockerRunner

pytestmark = pytest.mark.docker


def run(r: DockerRunner, code: str, timeout_s: int = 10, label: str = "", **kw):
    res = r.run(code, kw.get("inputs", {}), kw.get("files", []), timeout_s=timeout_s)
    TIMINGS.append((label or code.splitlines()[0][:26], res))
    return res


def test_hello_world_timing(docker_runner: DockerRunner):
    t0 = time.monotonic()
    res = run(docker_runner, "print('hi')", label="hello")
    wall = time.monotonic() - t0
    assert res.exit_code == 0 and res.stdout == "hi\n" and res.stderr == ""
    assert not res.timed_out and not res.oom_killed
    assert wall < 15, f"one trivial run took {wall:.1f}s end to end"


def test_inputs_and_in_files_are_visible_read_only(docker_runner: DockerRunner):
    code = """
import json, os
inputs = json.load(open('/work/inputs.json'))
data = open('/work/in/a.txt').read()
print(json.dumps({'inputs': inputs, 'a': data, 'uid': os.getuid(), 'cwd': os.getcwd()}))
for p in ('/work/in/a.txt', '/work/in/new', '/work/main.py', '/work/inputs.json'):
    try:
        open(p, 'a').close(); print('WRITABLE', p)
    except OSError as e:
        print('ro', p, e.errno)
"""
    res = run(docker_runner, code, inputs={"k": 1}, files=[("a.txt", b"abc")], label="inputs")
    assert res.exit_code == 0, res.stderr
    first, *rest = res.stdout.splitlines()
    assert json.loads(first) == {"inputs": {"k": 1}, "a": "abc", "uid": 10002, "cwd": "/work"}
    assert all(line.startswith("ro ") for line in rest), res.stdout


def test_no_network(docker_runner: DockerRunner):
    code = """
import time, urllib.request
for url in ('http://1.1.1.1/', 'http://example.com/'):
    t = time.monotonic()
    try:
        urllib.request.urlopen(url, timeout=5)
        print('OPEN', url)
    except Exception as e:
        print('blocked', url, type(e).__name__, round(time.monotonic() - t, 2))
"""
    res = run(docker_runner, code, label="no-network")
    assert res.exit_code == 0, res.stderr
    lines = res.stdout.splitlines()
    assert len(lines) == 2 and all(line.startswith("blocked") for line in lines), res.stdout
    for line in lines:
        assert float(line.rsplit(" ", 1)[1]) < 2.0, f"should fail fast, not hang: {line}"


def test_root_is_read_only(docker_runner: DockerRunner):
    code = """
import os, errno
bad = []
for p in ('/usr/x', '/etc/x', '/x', '/home/x', '/work/in/x', '/root/x', '/var/x'):
    try:
        open(p, 'w').close(); bad.append(p)
    except OSError as e:
        assert e.errno in (errno.EROFS, errno.EACCES, errno.ENOENT, errno.EPERM), (p, e)
# scratch space exists but is not exported
open('/work/scratch.txt', 'w').write('x'); open('/tmp/t', 'w').write('x')
print('writable-elsewhere', bad)
"""
    res = run(docker_runner, code, label="read-only-root")
    assert res.exit_code == 0, res.stderr
    assert res.stdout.strip() == "writable-elsewhere []"
    assert res.files == []


def test_fork_bomb_hits_pids_limit(docker_runner: DockerRunner):
    code = """
import os, sys, time
# each process keeps forking; the pid limit makes fork() fail with EAGAIN, nothing else breaks
deadline = time.monotonic() + 30
while time.monotonic() < deadline:
    try:
        os.fork()
    except BlockingIOError:
        pass
"""
    t0 = time.monotonic()
    res = run(docker_runner, code, timeout_s=4, label="fork-bomb")
    wall = time.monotonic() - t0
    assert res.timed_out is True
    assert wall < 20, f"fork bomb must not stall the host or the service: {wall:.1f}s"
    # and the host is still fine: another run works right after
    after = run(docker_runner, "print('alive')", label="after-fork-bomb")
    assert after.exit_code == 0 and after.stdout == "alive\n"


def test_infinite_loop_is_killed_at_timeout(docker_runner: DockerRunner):
    t0 = time.monotonic()
    res = run(
        docker_runner,
        "print('start', flush=True)\nwhile True:\n    pass\n",
        timeout_s=2,
        label="while-true",
    )
    wall = time.monotonic() - t0
    assert res.timed_out is True
    assert res.exit_code != 0
    assert res.stdout == "start\n"
    assert 2 <= wall < 10, f"killed hard at the timeout, took {wall:.1f}s"


def test_one_gb_allocation_is_oom_killed(docker_runner: DockerRunner):
    code = """
chunks = []
for i in range(1024):
    chunks.append(bytes([i % 256]) * (1 << 20))  # really touches the pages
print('allocated 1 GiB without being killed')
"""
    res = run(docker_runner, code, timeout_s=20, label="oom-1GiB")
    assert "without being killed" not in res.stdout
    assert res.exit_code == 137 or res.oom_killed, (res.exit_code, res.oom_killed, res.stderr)
    assert res.oom_killed is True
    assert res.timed_out is False


def test_output_over_1mb_is_truncated(docker_runner: DockerRunner):
    code = "import sys\nsys.stdout.write('a' * 3_000_000)\nsys.stderr.write('b' * 1_500_000)\n"
    res = run(docker_runner, code, label="3MB-stdout")
    assert res.exit_code == 0
    marker = "[sandbox: output truncated at 1 MiB]"
    assert marker in res.stdout and marker in res.stderr
    assert len(res.stdout) <= 1_048_576 + len(marker) + 2
    assert len(res.stderr) <= 1_048_576 + len(marker) + 2
    assert res.stdout.startswith("a" * 1000)


def test_matplotlib_png_and_pandas_csv_are_returned(docker_runner: DockerRunner):
    code = """
import json
import numpy as np, pandas as pd
import matplotlib
import matplotlib.pyplot as plt
from PIL import Image
inputs = json.load(open('/work/inputs.json'))
df = pd.DataFrame({'person': inputs['people'], 'photos': np.arange(len(inputs['people'])) * 3})
df.to_csv('/work/out/table.csv', index=False)
fig, ax = plt.subplots(figsize=(4, 3))
ax.bar(df['person'], df['photos'])
fig.savefig('/work/out/plot.png', dpi=72)
Image.new('RGB', (8, 8), 'red').save('/work/out/tiny.webp')
open('/work/out/notes.txt', 'w').write('fertig / done')
open('/work/out/script.py', 'w').write('print(1)')          # not whitelisted
open('/work/out/fake.png', 'w').write('not a png')           # wrong magic
import os; os.symlink('/etc/passwd', '/work/out/passwd.txt') # must not be followed
os.mkdir('/work/out/sub'); open('/work/out/sub/x.txt', 'w').write('nested')
print(json.dumps({'rows': len(df), 'backend': matplotlib.get_backend()}))
"""
    res = run(docker_runner, code, inputs={"people": ["Anna", "Ben", "Cem"]}, label="mpl+pandas")
    assert res.exit_code == 0, res.stderr
    out = json.loads(res.stdout)
    assert out["rows"] == 3 and out["backend"].lower() == "agg"
    by_name = {f.name: f for f in res.files}
    assert sorted(by_name) == ["notes.txt", "plot.png", "table.csv", "tiny.webp"]
    png = base64.b64decode(by_name["plot.png"].bytes_b64)
    assert png.startswith(b"\x89PNG") and by_name["plot.png"].mime == "image/png"
    csv = base64.b64decode(by_name["table.csv"].bytes_b64).decode()
    assert csv.splitlines()[0] == "person,photos" and "Anna,0" in csv
    assert by_name["table.csv"].mime == "text/csv"
    assert by_name["tiny.webp"].mime == "image/webp"
    joined = " | ".join(res.warnings)
    assert "script.py" in joined and "fake.png" in joined
    assert "passwd.txt: not a regular file" in joined and "sub: not a regular file" in joined


def test_output_file_total_cap(docker_runner: DockerRunner):
    code = "open('/work/out/big.txt', 'w').write('x' * (51 * 1024 * 1024))\nprint('ok')"
    res = run(docker_runner, code, label="51MB-out")
    assert res.exit_code == 0 and res.files == []
    assert any("more than" in w for w in res.warnings), res.warnings


def test_http_end_to_end_with_file_fetch(docker_client: TestClient, file_server):
    file_server.files["/img/a.txt"] = b"from storage"
    r = docker_client.post(
        "/run",
        json={
            "code": "import json; print(json.dumps({'a': open('/work/in/a.txt').read(), "
            "'n': json.load(open('/work/inputs.json'))['n']}))",
            "inputs": {"n": 7},
            "files": [{"name": "a.txt", "url": file_server.url("/img/a.txt")}],
            "timeout_s": 10,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert json.loads(body["stdout"]) == {"a": "from storage", "n": 7}
    assert body["exit_code"] == 0 and body["timed_out"] is False and body["files"] == []
    health = docker_client.get("/health").json()
    assert health["ok"] and health["image"] and health["docker"]


def test_no_containers_left_behind(docker_runner: DockerRunner):
    left = docker_runner.client.containers.list(all=True, filters={"label": "yearbook.sandbox=1"})
    assert left == [], [c.name for c in left]
    assert not any(p.name.startswith("run-") for p in docker_runner.work_dir.iterdir())
