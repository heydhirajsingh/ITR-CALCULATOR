"""Local-only OCR engine backed by Tesseract."""
from __future__ import annotations

from dataclasses import dataclass

import fitz
import pytesseract
from PIL import Image, ImageOps


@dataclass(slots=True)
class OCRResult:
    text: str
    confidence: float


class TesseractOCREngine:
    """Render PDF pages and OCR them without sending data off the machine."""

    def page_to_text(self, page: fitz.Page, dpi: int = 220) -> OCRResult:
        matrix = fitz.Matrix(dpi / 72, dpi / 72)
        pix = page.get_pixmap(matrix=matrix, alpha=False)
        image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        image = ImageOps.grayscale(image)
        image = ImageOps.autocontrast(image)
        data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT, config="--psm 6")
        words: list[str] = []
        confidences: list[float] = []
        for text, confidence in zip(data.get("text", []), data.get("conf", []), strict=False):
            text = str(text).strip()
            try:
                score = float(confidence)
            except (TypeError, ValueError):
                score = -1
            if text:
                words.append(text)
            if score >= 0:
                confidences.append(score)
        return OCRResult(
            text=" ".join(words),
            confidence=(sum(confidences) / len(confidences)) if confidences else 0.0,
        )
