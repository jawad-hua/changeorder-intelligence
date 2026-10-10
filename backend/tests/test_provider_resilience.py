"""Provider resilience checks run offline; no real API secrets or network access."""
import asyncio
import json

import httpx
import pytest
from fastapi import HTTPException

from app import ai


def _call(responder):
    async def run():
        transport = httpx.MockTransport(responder)
        async with httpx.AsyncClient(transport=transport) as client:
            return await ai._ask_groq(client, "non-sensitive test document")
    return asyncio.run(run())


def test_temporary_provider_failure_retries_and_succeeds(monkeypatch):
    attempts = []
    async def no_delay(_seconds):
        return None
    monkeypatch.setattr(ai.asyncio, "sleep", no_delay)

    def respond(request):
        attempts.append(request)
        if len(attempts) < 3:
            return httpx.Response(503, json={"error": {"message": "unavailable"}})
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps({"fields": {"reason": {"value": "test"}}})}}]})

    result = _call(respond)
    assert len(attempts) == 3
    assert result["reason"]["value"] == "test"


@pytest.mark.parametrize("status,expected_api_status", [(401, 503), (403, 503), (400, 502), (404, 502), (413, 413)])
def test_nonretryable_provider_errors_are_descriptive(status, expected_api_status):
    attempts = []

    def respond(request):
        attempts.append(request)
        return httpx.Response(status, json={"error": {"message": "hidden by design"}})

    with pytest.raises(HTTPException) as exc:
        _call(respond)
    assert len(attempts) == 1
    assert exc.value.status_code == expected_api_status
    assert str(status) in exc.value.detail
    assert "hidden by design" not in exc.value.detail


def test_rate_limit_retries_then_returns_429(monkeypatch):
    async def no_delay(_seconds):
        return None
    monkeypatch.setattr(ai.asyncio, "sleep", no_delay)
    attempts = []

    def respond(request):
        attempts.append(request)
        return httpx.Response(429)

    with pytest.raises(HTTPException) as exc:
        _call(respond)
    assert len(attempts) == 3
    assert exc.value.status_code == 429
    assert "rate limit" in exc.value.detail


def test_invalid_json_structure_reports_specific_failure():
    with pytest.raises(HTTPException) as exc:
        _call(lambda _: httpx.Response(200, json={"choices": [{"message": {"content": "nonsense"}}]}))
    assert exc.value.status_code == 502
    assert "invalid JSON" in exc.value.detail
