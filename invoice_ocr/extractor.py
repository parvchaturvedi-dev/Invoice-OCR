from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pytesseract
from PIL import Image, ImageFilter, ImageOps


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}
PDF_EXTENSIONS = {".pdf"}


@dataclass(frozen=True)
class ExtractedField:
    value: str | None
    confidence: float
    source: str

    def to_json(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "confidence": round(self.confidence, 2),
            "source": self.source,
        }


def extract_invoice(file_path: str | Path, uploaded_by: str = "accountant") -> dict[str, Any]:
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    images = _load_file_as_images(path)
    page_texts: list[str] = []
    page_confidences: list[float] = []

    for image in images:
        prepared = _preprocess_image(image)
        text, confidence = _ocr_image(prepared)
        page_texts.append(text)
        page_confidences.append(confidence)

    raw_text = "\n\n".join(page_texts)
    fields = _extract_fields(raw_text)
    upload_date = datetime.now().astimezone().isoformat(timespec="seconds")

    fields["upload_date"] = ExtractedField(upload_date, 1.0, "system")
    fields["uploaded_by"] = ExtractedField(uploaded_by, 1.0, "input")

    return {
        "file_name": path.name,
        "page_count": len(images),
        "ocr_confidence": round(_average(page_confidences), 2),
        "fields": {name: field.to_json() for name, field in fields.items()},
        "flat_fields": {name: field.value for name, field in fields.items()},
        "raw_text": raw_text,
    }


def _load_file_as_images(path: Path) -> list[Image.Image]:
    extension = path.suffix.lower()

    if extension in IMAGE_EXTENSIONS:
        return [Image.open(path).convert("RGB")]

    if extension in PDF_EXTENSIONS:
        try:
            import fitz
        except ImportError as exc:
            raise RuntimeError(
                "PDF input requires PyMuPDF. Install it with: pip install PyMuPDF"
            ) from exc

        images: list[Image.Image] = []
        document = fitz.open(path)
        try:
            for page in document:
                pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                image = Image.frombytes("RGB", [pixmap.width, pixmap.height], pixmap.samples)
                images.append(image)
        finally:
            document.close()

        if not images:
            raise RuntimeError("PDF has no pages to OCR.")
        return images

    allowed = ", ".join(sorted(IMAGE_EXTENSIONS | PDF_EXTENSIONS))
    raise ValueError(f"Unsupported file type '{extension}'. Allowed: {allowed}")


def _preprocess_image(image: Image.Image) -> Image.Image:
    gray = ImageOps.grayscale(image)
    if gray.width < 1400:
        scale = 1400 / max(gray.width, 1)
        new_size = (int(gray.width * scale), int(gray.height * scale))
        gray = gray.resize(new_size, Image.Resampling.LANCZOS)

    gray = ImageOps.autocontrast(gray)
    gray = gray.filter(ImageFilter.MedianFilter(size=3))
    return gray.point(lambda pixel: 255 if pixel > 175 else 0)


def _ocr_image(image: Image.Image) -> tuple[str, float]:
    config = "--oem 3 --psm 6"
    text = pytesseract.image_to_string(image, config=config)
    data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT, config=config)
    confidences = [
        float(conf)
        for conf in data.get("conf", [])
        if _is_number(conf) and float(conf) >= 0
    ]
    return text.strip(), _average(confidences) / 100 if confidences else 0.0


def _extract_fields(text: str) -> dict[str, ExtractedField]:
    normalized = _normalize_text(text)

    return {
        "invoice_number": _first_match(
            normalized,
            [
                r"\b(?:invoice|inv|bill)\s*(?:number|no|#)\s*[:\-]?\s*([A-Z0-9][A-Z0-9\/\-_.]{2,})",
                r"\b(?:tax\s+invoice)\s*[:\-]?\s*([A-Z0-9][A-Z0-9\/\-_.]{2,})",
            ],
        ),
        "invoice_date": _first_match(
            normalized,
            [
                r"\b(?:invoice\s*)?date\s*[:\-]?\s*([0-3]?\d[\/\-.][01]?\d[\/\-.](?:\d{4}|\d{2}))",
                r"\b(?:invoice\s*)?date\s*[:\-]?\s*([0-3]?\d\s+[A-Z]{3,9}\s+\d{2,4})",
                r"\b(?:invoice\s*)?date\s*[:\-]?\s*((?:\d{2}|\d{4})[\/\-.][01]?\d[\/\-.][0-3]?\d)",
            ],
        ),
        "vendor_name": _extract_vendor_name(normalized),
        "total_amount": _amount_after_label(
            normalized,
            [
                "grand total",
                "total amount",
                "amount payable",
                "net payable",
                "invoice total",
                "total",
            ],
        ),
        "taxable_amount": _amount_after_label(
            normalized,
            ["taxable value", "taxable amount", "total taxable", "subtotal", "sub total"],
        ),
        "gstin": _extract_gstin(normalized),
        "invoice_type": _extract_invoice_type(normalized),
        "currency": _extract_currency(normalized),
    }


def _normalize_text(text: str) -> str:
    text = text.replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _first_match(text: str, patterns: list[str]) -> ExtractedField:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return ExtractedField(_clean_value(match.group(1)), 0.85, f"regex:{pattern}")
    return ExtractedField(None, 0.0, "not_found")


def _extract_vendor_name(text: str) -> ExtractedField:
    labelled = _first_match(
        text,
        [
            r"\b(?:supplier|vendor|seller)\s*name\s*[:\-]?\s*([^\n]{3,80})",
            r"\b(?:bill\s+from|from)\s*[:\-]?\s*([^\n]{3,80})",
        ],
    )
    if labelled.value:
        return labelled

    for line in [line.strip() for line in text.splitlines() if line.strip()]:
        lower = line.lower()
        if any(word in lower for word in ["invoice", "date", "gstin", "total", "amount"]):
            continue
        if len(line) >= 3 and re.search(r"[A-Za-z]", line):
            return ExtractedField(_clean_value(line), 0.45, "heuristic:first_header_line")

    return ExtractedField(None, 0.0, "not_found")


def _amount_after_label(text: str, labels: list[str]) -> ExtractedField:
    amount_pattern = r"(?:INR|USD|EUR|GBP|Rs\.?|\$)?\s*([0-9]{1,3}(?:,[0-9]{2,3})+(?:\.\d{1,2})?|[0-9]+(?:\.\d{1,2})?)"
    for label in labels:
        pattern = rf"\b{re.escape(label)}\b\s*[:\-]?\s*{amount_pattern}"
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return ExtractedField(_clean_amount(match.group(1)), 0.8, f"label:{label}")
    return ExtractedField(None, 0.0, "not_found")


def _extract_gstin(text: str) -> ExtractedField:
    match = re.search(r"\b([0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z])\b", text)
    if match:
        return ExtractedField(match.group(1), 0.95, "regex:gstin")
    return ExtractedField(None, 0.0, "not_found")


def _extract_invoice_type(text: str) -> ExtractedField:
    patterns = [
        ("Tax Invoice", r"\btax\s+invoice\b"),
        ("Debit Note", r"\bdebit\s+note\b"),
        ("Credit Note", r"\bcredit\s+note\b"),
        ("Proforma Invoice", r"\bproforma\s+invoice\b"),
    ]
    for value, pattern in patterns:
        if re.search(pattern, text, flags=re.IGNORECASE):
            return ExtractedField(value, 0.9, f"regex:{pattern}")
    return ExtractedField(None, 0.0, "not_found")


def _extract_currency(text: str) -> ExtractedField:
    currency_patterns = [
        ("INR", r"\bINR\b|\bRs\.?\b"),
        ("USD", r"\bUSD\b|\$"),
        ("EUR", r"\bEUR\b"),
        ("GBP", r"\bGBP\b"),
    ]
    for value, pattern in currency_patterns:
        if re.search(pattern, text, flags=re.IGNORECASE):
            return ExtractedField(value, 0.85, f"regex:{pattern}")
    return ExtractedField(None, 0.0, "not_found")


def _clean_value(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip(" :-|")


def _clean_amount(value: str) -> str:
    return value.replace(",", "").strip()


def _average(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _is_number(value: Any) -> bool:
    try:
        float(value)
    except (TypeError, ValueError):
        return False
    return True
