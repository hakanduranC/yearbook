"""Contract checks against the app with a fake runner: validation, pre-flight, file fetching,
the host allowlist and the 429 behaviour. No Docker."""

from __future__ import annotations

import threading

import pytest
from fastapi.testclient import TestClient

from yearbook_sandbox.app import create_app
from yearbook_sandbox.config import MAX_FILE_BYTES
from yearbook_sandbox.fetch import check_url_allowed


def test_health_reports_docker_and_image(client: TestClient):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] and body["docker"] and body["image"]
    assert body["max_parallel"] == 1 and body["in_flight"] == 0


def test_run_writes_main_and_inputs(client: TestClient, fake_runner):
    r = client.post("/run", json={"code": "print(1)", "inputs": {"a": [1, 2]}, "timeout_s": 3})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["stdout"] == "fake" and body["exit_code"] == 0 and body["timed_out"] is False
    assert body["files"] == [] and body["warnings"] == []
    call = fake_runner.calls[-1]
    assert call["timeout_s"] == 3 and call["inputs"] == {"a": [1, 2]}
    rd = fake_runner.prepared[-1]
    assert not rd.root.exists(), "run directory must be removed after the run"


@pytest.mark.parametrize(
    "body",
    [
        {"code": ""},
        {"code": "x" * 20_001},
        {"code": "print(1)", "timeout_s": 21},
        {"code": "print(1)", "timeout_s": 0},
        {"code": "print(1)", "files": [{"name": "../etc", "url": "http://localhost:8333/x"}]},
        {"code": "print(1)", "files": [{"name": "a/b", "url": "http://localhost:8333/x"}]},
        {"code": "print(1)", "files": [{"name": "main.py", "url": "http://localhost:8333/x"}]},
        {"code": "print(1)", "files": [{"name": "a", "url": "u"}, {"name": "a", "url": "u"}]},
        {
            "code": "print(1)",
            "files": [{"name": f"f{i}", "url": "http://localhost:8333/x"} for i in range(21)],
        },
        {"code": "print(1)", "inputs": {"blob": "x" * 1_000_001}},
    ],
)
def test_validation_rejects(client: TestClient, body):
    r = client.post("/run", json=body)
    assert r.status_code == 422, r.text


@pytest.mark.parametrize(
    "code,token",
    [
        ("import socket", "socket"),
        ("import subprocess; subprocess.run(['id'])", "subprocess"),
        ("__import__('os').system('id')", "__import__"),
    ],
)
def test_preflight_rejects_forbidden_tokens(client: TestClient, fake_runner, code, token):
    r = client.post("/run", json={"code": code})
    assert r.status_code == 400
    assert r.json()["detail"] == {
        "code": "forbidden_token",
        "message": f"code uses {token!r}, which the sandbox refuses",
        "token": token,
    }
    assert fake_runner.calls == []


def test_allowlist_accepts_storage_hosts_only(settings):
    hosts = settings.allowed_hosts
    assert "localhost:8333" in hosts
    assert check_url_allowed("http://localhost:8333/yearbook-public/k.jpg", hosts) is None
    assert check_url_allowed("https://example.com/k.jpg", hosts) is not None
    assert check_url_allowed("http://localhost:8333@evil.example/k.jpg", hosts) is not None
    assert check_url_allowed("http://localhost/k.jpg", hosts) is not None, (
        "port is part of the host"
    )
    assert check_url_allowed("file:///etc/passwd", hosts) is not None
    assert check_url_allowed("ftp://localhost:8333/x", hosts) is not None


def test_external_file_url_is_rejected_before_any_run(client: TestClient, fake_runner):
    r = client.post(
        "/run",
        json={
            "code": "print(1)",
            "files": [{"name": "a.jpg", "url": "https://example.com/a.jpg"}],
        },
    )
    assert r.status_code == 400, r.text
    detail = r.json()["detail"]
    assert detail["code"] == "url_not_allowed" and detail["file"] == "a.jpg"
    assert "example.com" in detail["message"]
    assert fake_runner.calls == []
    assert fake_runner.prepared and not fake_runner.prepared[-1].root.exists()


def test_files_are_fetched_into_in_dir(client: TestClient, fake_runner, file_server):
    file_server.files["/p/a.bin"] = b"\x00\x01\x02"
    file_server.files["/p/b.txt-nolength"] = b"hello"
    r = client.post(
        "/run",
        json={
            "code": "print(1)",
            "files": [
                {"name": "a.bin", "url": file_server.url("/p/a.bin")},
                {"name": "b.txt", "url": file_server.url("/p/b.txt-nolength")},
            ],
        },
    )
    assert r.status_code == 200, r.text
    assert fake_runner.calls[-1]["in"] == {"a.bin": b"\x00\x01\x02", "b.txt": b"hello"}


def test_missing_file_is_a_400(client: TestClient, fake_runner, file_server):
    r = client.post(
        "/run",
        json={"code": "print(1)", "files": [{"name": "x", "url": file_server.url("/nope")}]},
    )
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "fetch_failed"
    assert fake_runner.calls == []


def test_oversized_file_is_rejected(client: TestClient, fake_runner, file_server):
    big = b"x" * (MAX_FILE_BYTES + 1)
    file_server.files["/big"] = big
    file_server.files["/big-nolength"] = big
    for path in ("/big", "/big-nolength"):
        r = client.post(
            "/run",
            json={"code": "print(1)", "files": [{"name": "big", "url": file_server.url(path)}]},
        )
        assert r.status_code == 400, path
        assert r.json()["detail"]["code"] == "file_too_large"
    assert fake_runner.calls == []


def test_second_concurrent_run_gets_429(settings, fake_runner):
    fake_runner.delay_s = 1.0  # longer than sandbox_queue_wait_s (0.3) in the test settings
    app = create_app(settings, runner=fake_runner, selfcheck=False)
    results: dict[str, int] = {}

    def post(key: str) -> None:
        results[key] = c.post("/run", json={"code": "print(1)"}).status_code

    with TestClient(app) as c:
        t1 = threading.Thread(target=post, args=("first",))
        t1.start()
        import time

        time.sleep(0.2)
        post("second")
        t1.join()
    assert results["first"] == 200
    assert results["second"] == 429
    assert len(fake_runner.calls) == 1
