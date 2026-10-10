"""No API key or internet needed: Groq Vision request and routing regressions."""
import asyncio
import io
import json

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import ai, main, vision
from app.main import app


def make_image(kind="PNG") -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (320, 120), "white").save(buf, format=kind)
    return buf.getvalue()


def test_vision_payload_uses_separate_vision_model_and_real_image(monkeypatch):
    captured = []
    def handler(request):
        body = json.loads(request.content)
        captured.append(body)
        assert request.url.path == "/openai/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer fake-key"
        assert body["model"] == "qwen/qwen3.8-27b"
        assert body["response_format"]["type"] == "json_object"
        assert body["messages"][0]["content"][1]["type"] == "image_url"
        assert body["messages"][0]["content"][1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
        return httpx.Response(200, json={
            "choices": [{"finish_reason": "stop", "message": {"content": json.dumps({"text": "Total change order cost: USD 3,000."})}}]
        })
    async_client = httpx.AsyncClient
    monkeypatch.setattr(vision.httpx, "AsyncClient", lambda **kwargs: async_client(transport=httpx.MockTransport(handler), **kwargs))
    monkeypatch.setattr(vision.settings, "groq_api_key", "fake-key")
    monkeypatch.setattr(vision.settings, "groq_vision_model", "qwen/qwen3.8-27b")
    assert asyncio.run(vision.transcribe_image(make_image("WEBP"))) == "Total change order cost: USD 3,000."
    assert len(captured) == 1


@pytest.mark.parametrize("extension,fmt", [("png", "PNG"), ("jpg", "JPEG"), ("webp", "WEBP"), ("tiff", "TIFF")])
def test_image_formats_use_vision_and_no_tesseract(monkeypatch, extension, fmt):
    called = []
    async def transcript(_content):
        called.append("vision")
        return "Total change order cost: USD 3,000."
    async def extract_model(_client, _prompt):
        return {}
    monkeypatch.setattr(main, "transcribe_image", transcript)
    monkeypatch.setattr(ai, "_ask_groq", extract_model)
    monkeypatch.setattr(ai.settings, "groq_api_key", "fake-key")
    monkeypatch.setattr(ai.settings, "enable_recovery_pass", False)
    from app import extract
    def no_local_ocr(*_a, **_kw):
        raise AssertionError("Direct images should not require Tesseract")
    monkeypatch.setattr(extract, "ocr_image", no_local_ocr)
    with TestClient(app) as client:
        response = client.post("/api/v1/extract", files={"file": (f"photo.{extension}", make_image(fmt), "application/octet-stream")})
    assert response.status_code == 200, response.text
    assert response.json()["ocr_text"].startswith("Total change order")
    assert response.json()["fields"]["cost_impact"]["status"] == "supported"
    assert called == ["vision"]


def test_text_files_never_use_vision(monkeypatch):
    async def should_not_call_vision(_content):
        raise AssertionError("Vision must not be used for TXT")
    async def extract_model(_client, _prompt):
        return {}
    monkeypatch.setattr(main, "transcribe_image", should_not_call_vision)
    monkeypatch.setattr(ai, "_ask_groq", extract_model)
    monkeypatch.setattr(ai.settings, "groq_api_key", "fake-key")
    monkeypatch.setattr(ai.settings, "enable_recovery_pass", False)
    with TestClient(app) as client:
        response = client.post("/api/v1/extract", files={"file": ("co.txt", b"Total change order cost: USD 3,000.", "text/plain")})
    assert response.status_code == 200
    assert response.json()["fields"]["cost_impact"]["value"] == 3000


def test_image_without_text_returns_422(monkeypatch):
    async def no_text(_content):
        return ""
    monkeypatch.setattr(main, "transcribe_image", no_text)
    monkeypatch.setattr(ai.settings, "groq_api_key", "fake-key")
    with TestClient(app) as client:
        response = client.post("/api/v1/extract", files={"file": ("image.png", make_image(), "image/png")})
    assert response.status_code == 422


def test_vision_rate_limit_reported_without_leaking_key(monkeypatch):
    def handler(_request):
        return httpx.Response(429, json={"error": "rate_limit"})
    async_client = httpx.AsyncClient
    monkeypatch.setattr(vision.httpx, "AsyncClient", lambda **kwargs: async_client(transport=httpx.MockTransport(handler), **kwargs))
    monkeypatch.setattr(vision.settings, "groq_api_key", "secret-key")
    monkeypatch.setattr(vision, "_MAX_ATTEMPTS", 1)
    with pytest.raises(Exception) as error:
        asyncio.run(vision.transcribe_image(make_image()))
    assert getattr(error.value, "status_code", None) == 429
    assert "secret-key" not in str(error.value)


def test_invalid_image_rejected_before_network(monkeypatch):
    async def should_not_call_vision(_content):
        raise AssertionError("Invalid images never go to Groq")
    monkeypatch.setattr(main, "transcribe_image", should_not_call_vision)
    with TestClient(app) as client:
        response = client.post("/api/v1/extract", files={"file": ("invalid.png", b"not an image", "image/png")})
    assert response.status_code == 422
