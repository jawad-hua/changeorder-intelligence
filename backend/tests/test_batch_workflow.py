"""Regression checks for numeric grounding and isolated batch processing."""
import io

import fitz
from docx import Document
from fastapi.testclient import TestClient

from app import ai
from app.extract import parse_document
from app.grounding import verify_field
from app.main import app
from app.schemas import Evidence, ExtractedField


def cost_check(value: float, quote: str):
    doc = parse_document("contract.txt", quote.encode())
    field = ExtractedField(value=value, status="supported", confidence=0.97,
                           evidence=Evidence(quote=quote, page=1))
    return verify_field("cost_impact", field, doc)


def test_cost_with_sentence_period_matches_correctly():
    field, warning = cost_check(3000, "Total change order cost: USD 3,000.")
    assert field.status == "supported"
    assert field.confidence == 0.95
    assert warning is None


def test_cost_multiple_line_items_matches_only_explicit_total():
    evidence = "Additional labor: USD 1,200. Additional materials: USD 1,800. Total change order cost: USD 3,000."
    good, warning = cost_check(3000, evidence)
    assert good.status == "supported" and warning is None
    bad, warning = cost_check(1200, evidence)
    assert bad.status == "review" and warning


def test_unlabelled_multiple_amounts_require_review():
    field, warning = cost_check(1200, "Labor USD 1,200 and supplies USD 1,800.")
    assert field.status == "review" and warning


def test_matching_number_with_different_magnitude_needs_review():
    field, warning = cost_check(3000, "Total change order cost: USD 13,000.")
    assert field.status == "review" and warning


def test_conflicting_total_statements_require_review():
    field, warning = cost_check(3000, "Total cost: USD 3,000. Grand total: USD 3,200.")
    assert field.status == "review" and warning


def test_money_decimal_and_negative():
    field, warning = cost_check(-1500.50, "Total cost: -1,500.50.")
    assert field.status == "supported" and warning is None


def _docx() -> bytes:
    doc = Document()
    doc.add_paragraph("Approval Status: Pending approval")
    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


def _pdf() -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((45, 60), "Total change order cost: USD 3,000.")
    data = doc.tobytes()
    doc.close()
    return data


def test_batch_mixed_valid_and_invalid(monkeypatch):
    async def offline_provider(_client, _prompt):
        return {}

    monkeypatch.setattr(ai, "_ask_groq", offline_provider)
    monkeypatch.setattr(ai.settings, "groq_api_key", "unit-test-key")
    monkeypatch.setattr(ai.settings, "enable_recovery_pass", False)
    with TestClient(app) as client:
        response = client.post("/api/v1/extract/batch", files=[
            ("files", ("a.pdf", _pdf(), "application/pdf")),
            ("files", ("bad.doc", b"not supported", "application/msword")),
            ("files", ("b.docx", _docx(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")),
        ])
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["requested"] == 3
    assert [doc["document_name"] for doc in data["results"]] == ["a.pdf", "b.docx"]
    assert data["failures"][0]["document_name"] == "bad.doc"
    assert data["failures"][0]["status_code"] == 415


def test_batch_max_file_count():
    with TestClient(app) as client:
        result = client.post("/api/v1/extract/batch", files=[
            ("files", (f"test-{n}.txt", b"data", "text/plain")) for n in range(6)
        ])
    assert result.status_code == 413


def test_batch_validates_empty_upload():
    with TestClient(app) as client:
        result = client.post("/api/v1/extract/batch", files=[
            ("files", ("empty.txt", b"", "text/plain"))
        ])
    assert result.status_code == 200
    assert not result.json()["results"]
    assert result.json()["failures"][0]["status_code"] == 422
