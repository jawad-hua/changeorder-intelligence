from app.extract import parse_document
from app.grounding import verify_field
from app.schemas import Evidence, ExtractedField


def check(field_key, value, quote, source):
    doc = parse_document("co.txt", source.encode())
    candidate = ExtractedField(value=value, status="supported", confidence=0.93, evidence=Evidence(quote=quote, page=1))
    return verify_field(field_key, candidate, doc)


def test_dates_consistent_iso_and_worded():
    field, warning = check("request_date", "2026-10-08", "October 8, 2026", "Request Date: October 8, 2026")
    assert field.status == "supported"
    assert warning is None


def test_dates_inconsistent_needs_review():
    field, warning = check("request_date", "2026-10-10", "October 8, 2026", "Request Date: October 8, 2026")
    assert field.status == "review"
    assert warning


def test_unrelated_quote_cannot_prove_contractor():
    field, warning = check("contractor", "Fictional Builders", "Riverside Office Renovation", "Project: Riverside Office Renovation")
    assert field.status == "review"
    assert warning


def test_pending_not_mistaken_for_approved():
    field, warning = check("approval_status", "Approved", "Pending approval", "Approval status: Pending approval")
    assert field.status == "review"
    assert warning


def test_numbers_require_matching_amount():
    field, warning = check("schedule_impact_days", 30, "3 calendar days", "Adds 3 calendar days")
    assert field.status == "review"
    assert warning
