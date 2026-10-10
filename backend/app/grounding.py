"""Evidence checks and conservative label-anchored recovery."""
from __future__ import annotations

import re
import unicodedata
from decimal import Decimal, InvalidOperation
from datetime import datetime

from .extract import ParsedDocument
from .schemas import Evidence, ExtractedField


def normalized(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).split()).casefold()


def locate_quote(document: ParsedDocument, quote: str, claimed_page: int | None = None) -> Evidence | None:
    if not quote.strip():
        return None
    target = normalized(quote)
    matches = [section for section in document.sections if target in normalized(section.text)]
    if not matches:
        return None
    if claimed_page is not None:
        matches = [section for section in matches if section.page == claimed_page]
        if not matches:
            return None
    return Evidence(quote=quote, page=matches[0].page)


# Avoid treating the period at the end of a sentence as part of the number.
# The previous boundary check rejected "USD 3,000." and wrongly flagged
# a correct cost of 3000 as unverified.
_NUMBER_RE = re.compile(
    r"(?<![\w.,])[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?![\w,])"
)
_TOTAL_RE = re.compile(r"(?i)\b(?:grand\s+total|total|net\s+change)\b")


def _decimal(value: object) -> Decimal | None:
    try:
        amount = Decimal(str(value).replace(",", "").strip())
        return amount if amount.is_finite() else None
    except (InvalidOperation, ValueError):
        return None


def _number_matches(quote: str) -> list[tuple[Decimal, int, int]]:
    amounts = []
    for item in _NUMBER_RE.finditer(quote):
        amount = _decimal(item.group())
        if amount is not None:
            amounts.append((amount, item.start(), item.end()))
    return amounts


def _number_present(value: str | int | float, quote: str) -> bool:
    desired = _decimal(value)
    return desired is not None and any(n == desired for n, _, _ in _number_matches(quote))


def _cost_consistent(value: str | int | float, quote: str) -> bool:
    """Match the labelled total, not a line-item amount within a compound quote.

    When the quote lists several monetary amounts but no explicit total, it
    cannot unambiguously support a claimed overall cost.
    """
    desired = _decimal(value)
    if desired is None:
        return False
    amounts = _number_matches(quote)
    if not amounts:
        return False
    total_amounts: list[Decimal] = []
    for label in _TOTAL_RE.finditer(quote):
        # Only numbers immediately following this total label on the same
        # statement; don't reach into a subsequent unrelated line item.
        remainder = quote[label.end():].split("\n", 1)[0].split(";", 1)[0]
        match = _number_matches(remainder[:85])
        if match:
            total_amounts.append(match[0][0])
    if total_amounts:
        return len(set(total_amounts)) == 1 and desired == total_amounts[0]
    unique_amounts = {amount for amount, _, _ in amounts}
    return len(unique_amounts) == 1 and desired in unique_amounts


def _semantic_consistency(key: str, field: ExtractedField) -> bool:
    if field.evidence is None or field.value is None:
        return False
    quote = normalized(field.evidence.quote)
    value = normalized(str(field.value))
    if key == "cost_impact":
        return _cost_consistent(field.value, field.evidence.quote)
    if key == "schedule_impact_days":
        return _number_present(field.value, field.evidence.quote)
    if key in ("change_order_number", "project_name", "contractor", "client", "description", "reason"):
        # Don't mark invented names or descriptions as supported merely because
        # the model supplied a genuine but unrelated source quote.
        return value in quote
    if key == "request_date":
        if value in quote:
            return True
        formats = (
            "%Y-%m-%d", "%d-%m-%Y", "%m/%d/%Y", "%d/%m/%Y",
            "%B %d, %Y", "%b %d, %Y", "%d %B %Y", "%d %b %Y",
        )
        def parse_date(text: str):
            for fmt in formats:
                try:
                    return datetime.strptime(text.strip(), fmt).date()
                except ValueError:
                    pass
            return None
        expected = parse_date(str(field.value))
        if expected is None:
            return False
        candidates = re.findall(
            r"\b(?:\d{4}-\d{2}-\d{2}|\d{1,2}[-/]\d{1,2}[-/]\d{4}|"
            r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
            r"jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|"
            r"dec(?:ember)?)\s+\d{1,2},?\s+\d{4})\b",
            quote, flags=re.IGNORECASE,
        )
        return any(parse_date(candidate) == expected for candidate in candidates)
    if key == "currency":
        codes = {"usd": ("usd", "us$", "$", "dollars"), "pkr": ("pkr", "rs.", "rupees"), "eur": ("eur", "€", "euros"), "gbp": ("gbp", "£", "pounds")}
        return any(x in quote for x in codes.get(value, (value,)))
    if key == "approval_status":
        if "pend" in value or "await" in value:
            return "pend" in quote or "await" in quote or "not approved" in quote
        if "reject" in value or "declin" in value:
            return "reject" in quote or "declin" in quote
        if "approv" in value:
            return "approv" in quote and not any(x in quote for x in ("pending", "awaiting", "not approved", "no approval"))
    # A date can be normalized to ISO by the model; the source quote still has to exist.
    return True


def verify_field(key: str, field: ExtractedField, document: ParsedDocument) -> tuple[ExtractedField, str | None]:
    if field.value is None or field.status == "missing":
        return ExtractedField(confidence=0), None
    if field.evidence is None:
        return ExtractedField(value=field.value, confidence=0, status="review"), f"{key}: source evidence missing"
    evidence = locate_quote(
        document, field.evidence.quote,
        None if document.kind == "docx" else field.evidence.page,
    )
    if evidence is None:
        return ExtractedField(value=field.value, confidence=0, status="review"), f"{key}: source evidence could not be verified"
    field.evidence = evidence
    if not _semantic_consistency(key, field):
        return ExtractedField(value=field.value, confidence=0, evidence=evidence, status="review"), f"{key}: value does not match quoted evidence"
    if field.status == "review":
        field.confidence = 0
        return field, f"{key}: ambiguous result needs manual review"
    field.confidence = min(field.confidence, 0.95)
    field.status = "supported"
    return field, None


def _anchored_section(text: str, label: str, next_labels: str) -> str | None:
    pattern = rf"(?im)^\s*{label}\s*[:\-]?\s*\n?([\s\S]*?)(?=^\s*(?:{next_labels})\s*[:\-]?\s*$|\Z)"
    match = re.search(pattern, text)
    return match.group(1).strip() if match else None


LABELS = (
    r"Change Order Number|Project Name|Client\s*/\s*Owner|Contractor|Request Date|"
    r"Approval Status|Description of Change|Reason for Change|Cost Impact|"
    r"Schedule Impact|Authorization|Notes|Signatures?|Total"
)


def recover_explicit_fields(document: ParsedDocument, fields: dict[str, ExtractedField]) -> dict[str, ExtractedField]:
    """Recover only visible, explicitly labelled facts; never invent missing facts."""
    result: dict[str, ExtractedField] = {}
    for section in document.sections:
        text = section.text
        candidates: dict[str, tuple[object, str]] = {}
        for key, label in (
            ("request_date", r"Request Date"),
            ("approval_status", r"Approval Status"),
            ("reason", r"Reason for Change"),
            ("schedule_impact_days", r"Schedule Impact"),
        ):
            if fields[key].status == "supported":
                continue
            excerpt = _anchored_section(text, label, LABELS)
            if not excerpt:
                continue
            if key == "schedule_impact_days":
                match = re.search(r"(?i)\b(\d{1,3})\s+(?:calendar\s+|working\s+|business\s+)?days?\b", excerpt)
                if match:
                    # Captures exact source including whitespace and line breaks.
                    start = max(0, excerpt.rfind("\n", 0, match.start()) + 1)
                    end = excerpt.find("\n", match.end())
                    evidence_text = excerpt[start:end if end != -1 else None].strip()
                    candidates[key] = (int(match.group(1)), evidence_text)
            elif key == "reason":
                candidates[key] = (normalized_space(excerpt), excerpt)
            else:
                line = excerpt.splitlines()[0].strip()
                if line and len(line) <= 160:
                    candidates[key] = (line, line)
        for key, (value, quote) in candidates.items():
            if key in result and result[key].value != value:
                result.pop(key)
                continue
            evidence = locate_quote(document, quote, section.page)
            if evidence is None:
                continue
            candidate = ExtractedField(value=value, confidence=0.85, evidence=evidence, status="supported")
            verified, issue = verify_field(key, candidate, document)
            if issue is None:
                result[key] = verified
    return result


def normalized_space(text: str) -> str:
    return " ".join(text.split())

# Financial values must be verified from a specifically labelled total. The
# model occasionally omits both amount and currency in batch runs even when an
# exact "Total change order cost" statement is visible in the source.
_EXPLICIT_TOTAL = re.compile(
    r"(?i)\b(?:grand\s+total|total\s+(?:change\s+order\s+)?cost|"
    r"change\s+order\s+total|net\s+change)\b\s*[:=\-]?\s*"
    r"(?P<currency>USD|PKR|EUR|GBP)\s*(?P<amount>[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,2})?)\b"
)


def recover_financial_fields(document: ParsedDocument, fields: dict[str, ExtractedField]) -> dict[str, ExtractedField]:
    """Conservatively recover absent cost/currency from unambiguous explicit totals.

    Never guess currencies from "$" (which may denote several currencies),
    never sum line items, and never choose between contradictory totals.
    """
    if fields["cost_impact"].status == "supported" and fields["currency"].status == "supported":
        return {}
    matches: list[tuple[Decimal, str, str, int | None]] = []
    for section in document.sections:
        for match in _EXPLICIT_TOTAL.finditer(section.text):
            amount = _decimal(match.group("amount"))
            if amount is not None:
                # Source quote remains verbatim and can be traced to original page.
                line_start = section.text.rfind("\n", 0, match.start()) + 1
                line_end = section.text.find("\n", match.end())
                quote = section.text[line_start:line_end if line_end != -1 else None].strip()
                matches.append((amount, match.group("currency").upper(), quote, section.page))
    if not matches or len({(amount, code) for amount, code, _, _ in matches}) != 1:
        return {}
    amount, code, quote, page = matches[0]
    recovered: dict[str, ExtractedField] = {}
    if fields["cost_impact"].status != "supported":
        value: int | float = int(amount) if amount == amount.to_integral_value() else float(amount)
        field = ExtractedField(value=value, confidence=0.90, status="supported", evidence=Evidence(quote=quote, page=page))
        verified, issue = verify_field("cost_impact", field, document)
        if issue is None:
            recovered["cost_impact"] = verified
    if fields["currency"].status != "supported":
        field = ExtractedField(value=code, confidence=0.90, status="supported", evidence=Evidence(quote=quote, page=page))
        verified, issue = verify_field("currency", field, document)
        if issue is None:
            recovered["currency"] = verified
    return recovered


def reconcile_labelled_totals(document: ParsedDocument, fields: dict[str, ExtractedField]) -> list[str]:
    """Resolve contradictions between AI-selected amounts and explicit source totals.

    Do not derive totals by summing line items or assuming a currency symbol.
    Conflicting *source* totals demand human review rather than a guess.
    The function mutates only financial fields and preserves auditable evidence.
    """
    totals: dict[tuple[Decimal, str], tuple[str, int | None]] = {}
    for section in document.sections:
        for match in _EXPLICIT_TOTAL.finditer(section.text):
            amount = _decimal(match.group("amount"))
            if amount is None:
                continue
            beginning = section.text.rfind("\n", 0, match.start()) + 1
            ending = section.text.find("\n", match.end())
            quote = section.text[beginning:ending if ending != -1 else None].strip()
            totals.setdefault((amount, match.group("currency").upper()), (quote, section.page))

    if not totals:
        return []
    if len(totals) != 1:
        touched = False
        for key in ("cost_impact", "currency"):
            current = fields[key]
            if current.status == "supported":
                fields[key] = ExtractedField(
                    value=current.value, confidence=0, evidence=current.evidence, status="review"
                )
                touched = True
        return (["cost_impact / currency: conflicting explicitly labelled totals; verify original document"]
                if touched else [])

    (amount, currency), (quote, page) = next(iter(totals.items()))
    corrected: list[str] = []
    for key, expected in (("cost_impact", amount), ("currency", currency)):
        current = fields[key]
        if current.status != "supported":
            continue  # Normal missing-field recovery handles these values.
        observed = _decimal(current.value) if key == "cost_impact" else str(current.value).upper()
        if observed == expected:
            continue
        value = (int(amount) if amount == amount.to_integral_value() else float(amount)) if key == "cost_impact" else currency
        candidate = ExtractedField(
            value=value, confidence=0.90, evidence=Evidence(quote=quote, page=page), status="supported"
        )
        verified, issue = verify_field(key, candidate, document)
        if issue is None:
            fields[key] = verified
            corrected.append(f"{key}: AI value disagreed with labelled source total; verified total was used. Confirm against original")
        else:
            fields[key] = ExtractedField(value=current.value, confidence=0, evidence=current.evidence, status="review")
            corrected.append(f"{key}: conflicting total needs manual review")
    return corrected
