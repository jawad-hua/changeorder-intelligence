"""Phase 5 regression checks: totals, batch isolation and response handling."""
import asyncio

import pytest
from fastapi.testclient import TestClient

from app import ai, main
from app.extract import parse_document
from app.main import app


def test_ai_line_item_does_not_override_explicit_total(monkeypatch):
    """A hallucinated total of 1,200 must not hide the labelled cost 3,000."""
    source = (
        "Additional labor: USD 1,200. Additional materials: USD 1,800.\n"
        "Total change order cost: USD 3,000.\n"
    )
    async def stub(_client, _prompt):
        return {
            "cost_impact": {"value": 1200, "confidence": 0.95,
                "evidence": {"quote": "Additional labor: USD 1,200.", "page": 1}, "status": "supported"},
            "currency": {"value": "USD", "confidence": 0.95,
                "evidence": {"quote": "Additional labor: USD 1,200.", "page": 1}, "status": "supported"},
        }
    monkeypatch.setattr(ai, "_ask_groq", stub)
    monkeypatch.setattr(ai.settings, "groq_api_key", "test-key")
    monkeypatch.setattr(ai.settings, "enable_recovery_pass", False)
    result = asyncio.run(ai.extract_fields("test.txt", parse_document("test.txt", source.encode())))
    assert result.fields["cost_impact"].value == 3000
    assert result.fields["cost_impact"].status == "supported"
    assert "Total change order cost" in result.fields["cost_impact"].evidence.quote
    assert result.requires_review  # AI disagreement is explicit in processing notes.
    assert any("AI value disagreed" in note for note in result.warnings)


def test_conflicting_labelled_totals_not_automatically_chosen(monkeypatch):
    source = "Total change order cost: USD 3,000.\nTotal change order cost: USD 4,000."
    async def stub(_client, _prompt):
        return {
            "cost_impact": {"value": 3000, "confidence": 0.95,
                "evidence": {"quote": "Total change order cost: USD 3,000.", "page": 1}, "status": "supported"},
            "currency": {"value": "USD", "confidence": 0.95,
                "evidence": {"quote": "Total change order cost: USD 3,000.", "page": 1}, "status": "supported"},
        }
    monkeypatch.setattr(ai, "_ask_groq", stub)
    monkeypatch.setattr(ai.settings, "groq_api_key", "test-key")
    monkeypatch.setattr(ai.settings, "enable_recovery_pass", False)
    result = asyncio.run(ai.extract_fields("conflict.txt", parse_document("conflict.txt", source.encode())))
    assert result.fields["cost_impact"].status == "review"
    assert result.fields["currency"].status == "review"
    assert result.requires_review
    assert any("conflicting" in w for w in result.warnings)


def test_no_labelled_total_keeps_explicitly_verified_cost(monkeypatch):
    async def stub(_client, _prompt):
        return {"cost_impact": {"value": 1200, "confidence": 0.95,
            "evidence": {"quote": "Cost impact: USD 1,200.", "page": 1}, "status": "supported"}}
    monkeypatch.setattr(ai, "_ask_groq", stub)
    monkeypatch.setattr(ai.settings, "groq_api_key", "test-key")
    monkeypatch.setattr(ai.settings, "enable_recovery_pass", False)
    result = asyncio.run(ai.extract_fields("x.txt", parse_document("x.txt", b"Cost impact: USD 1,200.")))
    assert result.fields["cost_impact"].value == 1200
    assert result.fields["cost_impact"].status == "supported"


def test_batch_internal_failure_is_isolated(monkeypatch):
    async def fake(file):
        if file.filename == "bad.txt":
            raise RuntimeError("should never expose this private string")
        return main.ExtractionResult(document_name=file.filename, fields={}, warnings=[], pages=1, requires_review=False)
    monkeypatch.setattr(main, "_extract_upload", fake)
    with TestClient(app) as client:
        response = client.post("/api/v1/extract/batch", files=[
            ("files", ("bad.txt", b"bad", "text/plain")),
            ("files", ("good.txt", b"good", "text/plain")),
        ])
    assert response.status_code == 200
    assert [r["document_name"] for r in response.json()["results"]] == ["good.txt"]
    assert response.json()["failures"][0]["status_code"] == 500
    assert "private string" not in response.text


@pytest.mark.parametrize("path", ["/health", "/api/v1/extract"])
def test_security_response_headers(path):
    with TestClient(app) as client:
        result = client.get(path) if path == "/health" else client.post(path, files={"file": ("empty.txt", b"", "text/plain")})
    assert result.headers["cache-control"] == "no-store"
    assert result.headers["x-content-type-options"] == "nosniff"
    assert result.headers["referrer-policy"] == "no-referrer"
