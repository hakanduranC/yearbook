"""`yearbook-worker serve`: /health and /embed/text through FastAPI's test client."""

from __future__ import annotations

import time

import numpy as np
import pytest
from fastapi.testclient import TestClient

from yearbook_worker.mlserver import create_app

pytestmark = pytest.mark.ml


@pytest.fixture(scope="module")
def client(settings, hub) -> TestClient:
    return TestClient(create_app(settings, hub))


def test_health(client: TestClient) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok" and body["dim"] == 1152 and "siglip_text" in body["models"]


def test_embed_text_multilingual_unit_vectors(client: TestClient, settings) -> None:
    texts = [
        "photos of me and Anna at the cake",
        "Fotos von mir und Anna beim Kuchen",
        "pasta ve Anna",
    ]
    started = time.perf_counter()
    r = client.post("/embed/text", json={"texts": texts})
    elapsed = time.perf_counter() - started
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["model"] == settings.worker_siglip_model
    vectors = np.asarray(body["vectors"], dtype=np.float32)
    assert vectors.shape == (3, 1152)
    assert np.allclose(np.linalg.norm(vectors, axis=1), 1.0, atol=1e-3)
    # de/en of the same sentence sit closer than the unrelated Turkish phrase
    sims = vectors @ vectors.T
    assert sims[0, 1] > sims[0, 2]
    single = time.perf_counter()
    assert client.post("/embed/text", json={"texts": ["birthday cake"]}).status_code == 200
    print(f"\n/embed/text: 3 texts {elapsed:.2f}s, 1 text {time.perf_counter() - single:.2f}s")


def test_embed_text_validation(client: TestClient) -> None:
    assert client.post("/embed/text", json={"texts": []}).status_code == 422
    assert client.post("/embed/text", json={"texts": ["  "]}).status_code == 400
    assert client.post("/embed/text", json={"texts": ["x"] * 65}).status_code == 422
