"""Bounded document extraction with Groq Vision for direct photo uploads."""
from pathlib import PurePath

from fastapi import FastAPI, File, HTTPException, UploadFile, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import Response
import logging

from .ai import extract_fields
from .config import settings
from .extract import attach_image_transcript, parse_document
from .vision import transcribe_image
from .schemas import BatchFailure, BatchResult, ExtractionResult

MAX_BATCH_FILES = 5

logger = logging.getLogger(__name__)

app = FastAPI(title="ChangeOrder Intelligence API", version="0.5.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[s.strip() for s in settings.cors_origins.split(",") if s.strip()],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


@app.middleware("http")
async def no_sensitive_response_caching(request: Request, call_next) -> Response:
    """OCR/AI response data should not be cached by proxies or browsers."""
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@app.get("/health")
def health():
    return {"status": "ok", "ai_configured": bool(settings.groq_api_key)}


async def _extract_upload(file: UploadFile) -> ExtractionResult:
    if not file.filename:
        raise HTTPException(400, "File name is required")
    name = PurePath(file.filename.replace("\\", "/")).name
    if not name or len(name) > 255:
        raise HTTPException(400, "Invalid file name")
    limit = settings.max_upload_mb * 1024 * 1024
    try:
        data = await file.read(limit + 1)
    finally:
        await file.close()
    if len(data) > limit:
        raise HTTPException(413, f"File exceeds the {settings.max_upload_mb} MB upload limit")
    if not data:
        raise HTTPException(422, "File is empty")
    document = parse_document(name, data)
    if document.kind == "image":
        transcript = await transcribe_image(data)
        document = attach_image_transcript(document, transcript)
    return await extract_fields(name, document)


@app.post("/api/v1/extract", response_model=ExtractionResult)
async def extract(file: UploadFile = File(...)):
    return await _extract_upload(file)


@app.post("/api/v1/extract/batch", response_model=BatchResult)
async def extract_batch(files: list[UploadFile] = File(...)):
    """Process up to five files in order to avoid provider rate-limit bursts.

    Failures remain attached to their filenames; one invalid document cannot
    discard a successful extraction. Nothing is written to server storage.
    """
    if not 1 <= len(files) <= MAX_BATCH_FILES:
        for upload in files:
            await upload.close()
        raise HTTPException(413, f"Select between 1 and {MAX_BATCH_FILES} documents")

    results: list[ExtractionResult] = []
    failures: list[BatchFailure] = []
    for index, file in enumerate(files):
        safe_name = PurePath((file.filename or "").replace("\\", "/")).name
        if not safe_name:
            safe_name = f"Document {index + 1}"
        try:
            results.append(await _extract_upload(file))
        except HTTPException as exc:
            failures.append(BatchFailure(
                document_name=safe_name,
                status_code=exc.status_code,
                detail=str(exc.detail),
            ))
        except Exception:
            # A malformed document or unexpected parser defect must not
            # abandon other documents or leak stack traces into the response.
            logger.exception("Unexpected batch processing failure at document index %s", index)
            failures.append(BatchFailure(
                document_name=safe_name,
                status_code=500,
                detail="Unexpected processing failure. Check server logs and retry this document",
            ))
    return BatchResult(results=results, failures=failures, requested=len(files))
