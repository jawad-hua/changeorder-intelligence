"""Bounded local OCR and preview generation. Tesseract may use temporary files."""
from __future__ import annotations

import base64
import io
import logging
from dataclasses import dataclass

from fastapi import HTTPException
from PIL import Image, ImageOps, UnidentifiedImageError
import pytesseract
from pytesseract import TesseractError, TesseractNotFoundError

from .config import settings

logger = logging.getLogger(__name__)
MAX_IMAGE_PIXELS = 14_000_000
MAX_OCR_SIDE = 2800
MAX_VISUALS = 4

# Detect decompression bombs instead of attempting to decode them.
Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS


@dataclass(frozen=True)
class VisualPreview:
    source: str
    page: int | None
    data_uri: str


def _open_image(content: bytes) -> Image.Image:
    try:
        with Image.open(io.BytesIO(content)) as source:
            if source.width * source.height > MAX_IMAGE_PIXELS:
                raise HTTPException(413, "Image exceeds 14 million pixels")
            if source.format not in {"PNG", "JPEG", "WEBP", "TIFF"}:
                raise HTTPException(422, "Unsupported image encoding")
            source.load()
            oriented = ImageOps.exif_transpose(source)
            # White background keeps dark text readable on transparent images.
            if oriented.mode in {"RGBA", "LA"} or "transparency" in oriented.info:
                rgba = oriented.convert("RGBA")
                flat = Image.new("RGB", rgba.size, "white")
                flat.paste(rgba, mask=rgba.getchannel("A"))
                return flat
            return oriented.convert("RGB")
    except HTTPException:
        raise
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError) as exc:
        raise HTTPException(422, "Image could not be decoded or exceeds safe processing limits") from exc


def prepare_image(content: bytes) -> Image.Image:
    image = _open_image(content)
    image.thumbnail((MAX_OCR_SIDE, MAX_OCR_SIDE), Image.Resampling.LANCZOS)
    return image


def ocr_image(image: Image.Image) -> str:
    if settings.tesseract_cmd.strip():
        pytesseract.pytesseract.tesseract_cmd = settings.tesseract_cmd.strip()
    try:
        # OCR on high-contrast grayscale; the original color is preserved for preview.
        gray = ImageOps.autocontrast(ImageOps.grayscale(image))
        return pytesseract.image_to_string(gray, lang=settings.ocr_language, timeout=18).strip()
    except TesseractNotFoundError as exc:
        raise HTTPException(503, "OCR is not installed. Install Tesseract OCR and add it to PATH or configure TESSERACT_CMD in backend/.env") from exc
    except TesseractError as exc:
        logger.warning("Local OCR engine could not read image (TesseractError)")
        raise HTTPException(422, "OCR could not read this image; try a clearer scan") from exc
    except RuntimeError as exc:
        raise HTTPException(422, "OCR timed out; try a smaller or clearer image") from exc


def preview(image: Image.Image, source: str, page: int | None) -> VisualPreview:
    thumb = image.copy()
    thumb.thumbnail((520, 360), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    thumb.save(buf, format="JPEG", quality=68, optimize=True)
    return VisualPreview(source=source, page=page, data_uri="data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii"))
