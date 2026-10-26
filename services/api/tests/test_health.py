"""Task 3 — health endpoint and request-scoped observability."""

from __future__ import annotations

import httpx
import pytest

from app.main import create_app


@pytest.fixture
async def client():
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_healthz_returns_200(client: httpx.AsyncClient) -> None:
    r = await client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


async def test_healthz_echoes_supplied_request_id(client: httpx.AsyncClient) -> None:
    r = await client.get("/healthz", headers={"X-Request-ID": "abc-123"})
    assert r.status_code == 200
    assert r.headers["X-Request-ID"] == "abc-123"


async def test_request_id_is_generated_when_absent(client: httpx.AsyncClient) -> None:
    r = await client.get("/healthz")
    assert r.headers.get("X-Request-ID")
    assert len(r.headers["X-Request-ID"]) >= 8


async def test_request_id_is_not_echoed_unvalidated(client: httpx.AsyncClient) -> None:
    """A header is attacker-controlled; it must not be able to inject log/HTTP junk."""
    r = await client.get("/healthz", headers={"X-Request-ID": "a" * 500 + " drop table"})
    assert r.status_code == 200
    assert r.headers["X-Request-ID"] != "a" * 500 + " drop table"
    assert len(r.headers["X-Request-ID"]) <= 64
