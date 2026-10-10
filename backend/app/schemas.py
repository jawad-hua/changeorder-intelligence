from typing import Literal

from pydantic import BaseModel, Field


class Evidence(BaseModel):
    quote: str = Field(min_length=1)
    page: int | None = Field(default=None, ge=1)


class ExtractedField(BaseModel):
    value: str | float | int | None = None
    confidence: float = Field(ge=0, le=1)
    evidence: Evidence | None = None
    status: Literal["supported", "missing", "review"] = "missing"


class VisualPreview(BaseModel):
    source: str
    page: int | None = None
    data_uri: str


class ExtractionResult(BaseModel):
    document_name: str
    fields: dict[str, ExtractedField]
    warnings: list[str] = Field(default_factory=list)
    pages: int | None = None
    requires_review: bool
    visuals: list[VisualPreview] = Field(default_factory=list)
    ocr_text: str | None = None


FIELDS = (
    "change_order_number",
    "project_name",
    "contractor",
    "client",
    "description",
    "reason",
    "cost_impact",
    "currency",
    "schedule_impact_days",
    "request_date",
    "approval_status",
)


class BatchFailure(BaseModel):
    document_name: str
    status_code: int
    detail: str


class BatchResult(BaseModel):
    results: list[ExtractionResult]
    failures: list[BatchFailure]
    requested: int
