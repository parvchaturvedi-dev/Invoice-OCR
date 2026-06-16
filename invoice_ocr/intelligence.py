from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any


@dataclass(frozen=True)
class FieldSpec:
    name: str
    db_column: str
    data_type: str
    required: bool
    synonyms: tuple[str, ...]
    value_patterns: tuple[str, ...] = ()


@dataclass(frozen=True)
class Candidate:
    label: str
    value: str
    source: str
    line_number: int | None = None


FIELD_SPECS: tuple[FieldSpec, ...] = (
    FieldSpec(
        "invoice_number",
        "INVOICE_NUMBER",
        "TEXT",
        True,
        ("invoice no", "invoice number", "inv no", "inv number", "bill no", "document no"),
        (r"\b(?:invoice|inv|bill|document)\s*(?:no|number|#)\s*[:\-]?\s*([A-Z0-9][A-Z0-9\/\-_.]{2,})",),
    ),
    FieldSpec(
        "vendor_name",
        "VENDOR_NAME_RAW",
        "TEXT",
        True,
        ("supplier", "supplier name", "vendor", "vendor name", "seller", "bill from", "from"),
    ),
    FieldSpec(
        "invoice_date",
        "INVOICE_DATE",
        "DATE",
        True,
        ("invoice date", "bill date", "date", "document date", "tax invoice date"),
        (
            r"\b(?:invoice|bill|document)?\s*date\s*[:\-]?\s*([0-3]?\d[\/\-.][01]?\d[\/\-.](?:\d{4}|\d{2}))",
            r"\b(?:invoice|bill|document)?\s*date\s*[:\-]?\s*([0-3]?\d\s+[A-Z]{3,9}\s+\d{2,4})",
        ),
    ),
    FieldSpec("due_date", "DUE_DATE", "DATE", False, ("due date", "payment due date", "pay by")),
    FieldSpec(
        "currency",
        "CURRENCY",
        "CURRENCY",
        False,
        ("currency", "currency code"),
        (r"\b(INR|USD|EUR|GBP)\b",),
    ),
    FieldSpec("subtotal", "SUBTOTAL", "AMOUNT", False, ("subtotal", "sub total", "basic amount")),
    FieldSpec("taxable_amount", "SUBTOTAL", "AMOUNT", False, ("taxable value", "taxable amount", "assessable value")),
    FieldSpec("cgst_amount", "CGST_AMOUNT", "AMOUNT", False, ("cgst", "cgst amount", "central gst")),
    FieldSpec("sgst_amount", "SGST_AMOUNT", "AMOUNT", False, ("sgst", "sgst amount", "state gst")),
    FieldSpec("igst_amount", "IGST_AMOUNT", "AMOUNT", False, ("igst", "igst amount", "integrated gst")),
    FieldSpec("tax_amount", "TAX_AMOUNT", "AMOUNT", False, ("tax amount", "gst amount", "total tax")),
    FieldSpec("discount_amount", "DISCOUNT_AMOUNT", "AMOUNT", False, ("discount", "discount amount")),
    FieldSpec("shipping_amount", "SHIPPING_AMOUNT", "AMOUNT", False, ("shipping", "freight", "delivery charges")),
    FieldSpec(
        "total_amount",
        "TOTAL_AMOUNT",
        "AMOUNT",
        True,
        ("grand total", "total amount", "invoice total", "amount payable", "net payable", "total"),
    ),
    FieldSpec("amount_in_words", "AMOUNT_IN_WORDS", "TEXT", False, ("amount in words", "total in words")),
    FieldSpec("po_number", "PO_NUMBER", "TEXT", False, ("po no", "po number", "purchase order", "purchase order no")),
    FieldSpec("grn_number", "GRN_NUMBER", "TEXT", False, ("grn no", "grn number", "goods receipt note")),
    FieldSpec(
        "vendor_gstin",
        "VENDOR_GSTIN",
        "GSTIN",
        False,
        ("vendor gstin", "supplier gstin", "seller gstin", "gstin", "gst no", "gst number"),
        (r"\b([0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z])\b",),
    ),
    FieldSpec("buyer_gstin", "BUYER_GSTIN", "GSTIN", False, ("buyer gstin", "customer gstin", "recipient gstin")),
    FieldSpec("place_of_supply", "PLACE_OF_SUPPLY", "TEXT", False, ("place of supply", "supply place")),
    FieldSpec("hsn_sac_code", "HSN_SAC_CODE", "TEXT", False, ("hsn", "sac", "hsn code", "sac code", "hsn/sac")),
    FieldSpec("irn_number", "IRN_NUMBER", "TEXT", False, ("irn", "irn no", "irn number")),
    FieldSpec("eway_bill_no", "EWAY_BILL_NO", "TEXT", False, ("eway bill", "e-way bill", "eway bill no", "e-way bill no")),
    FieldSpec("bank_account_no", "BANK_ACCOUNT_NO", "TEXT", False, ("bank account", "account no", "account number")),
    FieldSpec("bank_ifsc", "BANK_IFSC", "TEXT", False, ("ifsc", "ifsc code", "bank ifsc")),
    FieldSpec("bank_name", "BANK_NAME", "TEXT", False, ("bank", "bank name")),
    FieldSpec("payment_terms", "PAYMENT_TERMS", "TEXT", False, ("payment terms", "terms of payment")),
    FieldSpec("description", "DESCRIPTION", "TEXT", False, ("description", "particulars", "item description")),
    FieldSpec("notes", "NOTES", "TEXT", False, ("notes", "remarks", "comments")),
    FieldSpec(
        "invoice_type",
        "INVOICE_TYPE",
        "TEXT",
        False,
        ("invoice type", "tax invoice", "debit note", "credit note", "proforma invoice"),
    ),
)


def extract_intelligent_fields(
    raw_text: str,
    learning_hints: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    text = _normalize_text(raw_text)
    specs = _specs_with_learning(FIELD_SPECS, learning_hints or [])
    candidates = _extract_candidates(text)
    candidates.extend(_regex_candidates(text, specs))

    mapped: dict[str, dict[str, Any]] = {}
    extraction_results: list[dict[str, Any]] = []
    discovered_fields: list[dict[str, Any]] = []

    for candidate in candidates:
        match = _best_field_match(candidate, specs)
        if match is None or match["confidence"] < 0.52:
            discovered_fields.append(_candidate_to_unknown(candidate))
            continue

        field = match["field"]
        value = _clean_value(candidate.value)
        if not value:
            continue

        normalized_value = _normalize_value(value, field.data_type)
        confidence = _score_value(match["confidence"], normalized_value, field.data_type)
        result = {
            "field_name": field.name,
            "mapped_column": field.db_column,
            "label": candidate.label,
            "value": normalized_value,
            "confidence": round(confidence, 2),
            "source": candidate.source,
            "reason": match["reason"],
            "line_number": candidate.line_number,
        }
        extraction_results.append(result)

        previous = mapped.get(field.name)
        if previous is None or result["confidence"] > previous["confidence"]:
            mapped[field.name] = result

    _add_invoice_type_from_text(text, mapped, extraction_results)
    _add_vendor_fallback(text, mapped, extraction_results)

    missing_fields = [
        {
            "field_name": spec.name,
            "mapped_column": spec.db_column,
            "message": f"{spec.db_column} is required but was not confidently extracted.",
        }
        for spec in specs
        if spec.required and spec.name not in mapped
    ]

    flat_fields = {name: item["value"] for name, item in mapped.items()}
    fields = {
        name: {
            "value": item["value"],
            "confidence": item["confidence"],
            "source": item["source"],
            "mapped_column": item["mapped_column"],
            "label": item["label"],
            "reason": item["reason"],
        }
        for name, item in mapped.items()
    }

    return {
        "fields": fields,
        "flat_fields": flat_fields,
        "structured_fields": {item["mapped_column"]: item["value"] for item in mapped.values()},
        "extraction_results": extraction_results,
        "discovered_fields": _dedupe_unknowns(discovered_fields),
        "missing_fields": missing_fields,
        "validation_status": "INCOMPLETE" if missing_fields else "EXTRACTED",
        "learning": {
            "engine": "offline_scoring_v1",
            "hints_used": len(learning_hints or []),
            "is_self_learning": True,
        },
    }


def _specs_with_learning(
    specs: tuple[FieldSpec, ...],
    learning_hints: list[dict[str, Any]],
) -> tuple[FieldSpec, ...]:
    synonyms_by_column: dict[str, list[str]] = {}
    for hint in learning_hints:
        column = str(hint.get("mapped_column") or hint.get("db_column_name") or "").upper()
        label = str(hint.get("field_label_raw") or hint.get("synonym_text") or "").strip()
        if column and label:
            synonyms_by_column.setdefault(column, []).append(label)

    updated: list[FieldSpec] = []
    for spec in specs:
        learned = tuple(synonyms_by_column.get(spec.db_column, []))
        updated.append(
            FieldSpec(
                spec.name,
                spec.db_column,
                spec.data_type,
                spec.required,
                tuple(dict.fromkeys((*spec.synonyms, *learned))),
                spec.value_patterns,
            )
        )
    return tuple(updated)


def _extract_candidates(text: str) -> list[Candidate]:
    candidates: list[Candidate] = []
    for index, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip(" :-|\t")
        if not line:
            continue

        label_match = re.match(r"^([A-Za-z][A-Za-z0-9\s\/#().&-]{2,55})\s*(?::|\s-\s)\s*(.{1,180})$", line)
        if label_match:
            candidates.extend(
                _split_embedded_candidates(
                    _clean_label(label_match.group(1)),
                    label_match.group(2).strip(),
                    index,
                )
            )
            continue

        compact_match = re.match(
            r"^([A-Za-z][A-Za-z0-9\s\/#().&-]{2,35})\s{2,}(.{1,160})$",
            line,
        )
        if compact_match:
            candidates.append(
                Candidate(
                    label=_clean_label(compact_match.group(1)),
                    value=compact_match.group(2).strip(),
                    source="spaced_label_value",
                    line_number=index,
                )
            )
    return candidates


def _split_embedded_candidates(label: str, value: str, line_number: int) -> list[Candidate]:
    embedded_labels = (
        "Invoice No",
        "Invoice Number",
        "Invoice Date",
        "Bill No",
        "Bill Date",
        "GSTIN",
        "Currency",
        "Taxable Value",
        "Grand Total",
        "Total Amount",
        "Invoice Type",
        "Payment Terms",
        "PO Number",
        "E-Way Bill No",
        "IFSC",
    )
    pattern = re.compile(
        r"\s+(" + "|".join(re.escape(item) for item in embedded_labels) + r")\s*[:\-]\s*",
        flags=re.IGNORECASE,
    )

    items: list[Candidate] = []
    current_label = label
    remaining = value
    while True:
        match = pattern.search(remaining)
        if not match:
            break

        current_value = remaining[: match.start()].strip()
        if current_value:
            items.append(
                Candidate(
                    label=current_label,
                    value=current_value,
                    source="label_value",
                    line_number=line_number,
                )
            )
        current_label = _clean_label(match.group(1))
        remaining = remaining[match.end() :].strip()

    if remaining:
        items.append(
            Candidate(
                label=current_label,
                value=remaining,
                source="label_value",
                line_number=line_number,
            )
        )
    return items


def _regex_candidates(text: str, specs: tuple[FieldSpec, ...]) -> list[Candidate]:
    candidates: list[Candidate] = []
    for spec in specs:
        for pattern in spec.value_patterns:
            for match in re.finditer(pattern, text, flags=re.IGNORECASE):
                candidates.append(
                    Candidate(
                        label=spec.synonyms[0],
                        value=match.group(1),
                        source=f"regex:{spec.name}",
                        line_number=None,
                    )
                )
    return candidates


def _best_field_match(candidate: Candidate, specs: tuple[FieldSpec, ...]) -> dict[str, Any] | None:
    normalized_label = _normalize_label(candidate.label)
    best: dict[str, Any] | None = None

    for spec in specs:
        for synonym in spec.synonyms:
            normalized_synonym = _normalize_label(synonym)
            similarity = SequenceMatcher(None, normalized_label, normalized_synonym).ratio()
            if normalized_synonym in normalized_label or normalized_label in normalized_synonym:
                similarity = max(similarity, 0.88)
            if candidate.source == f"regex:{spec.name}":
                similarity = 0.96

            if _value_looks_like(candidate.value, spec.data_type):
                similarity += 0.06

            score = min(similarity, 0.99)
            if best is None or score > best["confidence"]:
                best = {
                    "field": spec,
                    "confidence": score,
                    "reason": f"matched label '{candidate.label}' to '{synonym}'",
                }

    return best


def _score_value(base_score: float, value: str, data_type: str) -> float:
    if not value:
        return 0.0
    if _value_looks_like(value, data_type):
        return min(base_score + 0.08, 0.99)
    return max(base_score - 0.18, 0.1)


def _value_looks_like(value: str, data_type: str) -> bool:
    if data_type == "AMOUNT":
        return bool(re.search(r"\d", value))
    if data_type == "DATE":
        return bool(re.search(r"\d{1,4}[\/\-. ]\d{1,2}[\/\-. ]\d{2,4}|\d{1,2}\s+[A-Za-z]{3,9}\s+\d{2,4}", value))
    if data_type == "GSTIN":
        return bool(re.search(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$", value.strip().upper()))
    if data_type == "CURRENCY":
        return value.strip().upper() in {"INR", "USD", "EUR", "GBP"}
    return True


def _normalize_value(value: str, data_type: str) -> str:
    value = _clean_value(value)
    if data_type in {"AMOUNT", "GSTIN", "CURRENCY"}:
        value = value.upper()
    if data_type == "AMOUNT":
        amount_match = re.search(r"[-+]?\d[\d,]*(?:\.\d{1,2})?", value)
        return amount_match.group(0).replace(",", "") if amount_match else value
    if data_type == "GSTIN":
        match = re.search(r"[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]", value)
        return match.group(0) if match else value
    if data_type == "CURRENCY":
        match = re.search(r"\b(INR|USD|EUR|GBP)\b", value)
        return match.group(1) if match else value
    return value


def _add_invoice_type_from_text(
    text: str,
    mapped: dict[str, dict[str, Any]],
    extraction_results: list[dict[str, Any]],
) -> None:
    if "invoice_type" in mapped:
        return

    invoice_types = (
        ("Tax Invoice", r"\btax\s+invoice\b"),
        ("Debit Note", r"\bdebit\s+note\b"),
        ("Credit Note", r"\bcredit\s+note\b"),
        ("Proforma Invoice", r"\bproforma\s+invoice\b"),
    )
    for value, pattern in invoice_types:
        if re.search(pattern, text, flags=re.IGNORECASE):
            item = {
                "field_name": "invoice_type",
                "mapped_column": "INVOICE_TYPE",
                "label": "invoice type",
                "value": value,
                "confidence": 0.92,
                "source": "document_keyword",
                "reason": f"matched document keyword {value}",
                "line_number": None,
            }
            mapped["invoice_type"] = item
            extraction_results.append(item)
            return


def _add_vendor_fallback(
    text: str,
    mapped: dict[str, dict[str, Any]],
    extraction_results: list[dict[str, Any]],
) -> None:
    if "vendor_name" in mapped:
        return

    for index, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        lower = line.lower()
        if not line or any(word in lower for word in ["invoice", "date", "gstin", "total", "amount"]):
            continue
        if len(line) >= 3 and re.search(r"[A-Za-z]", line):
            item = {
                "field_name": "vendor_name",
                "mapped_column": "VENDOR_NAME_RAW",
                "label": "vendor header",
                "value": line,
                "confidence": 0.46,
                "source": "header_fallback",
                "reason": "first text-like header line",
                "line_number": index,
            }
            mapped["vendor_name"] = item
            extraction_results.append(item)
            return


def _candidate_to_unknown(candidate: Candidate) -> dict[str, Any]:
    return {
        "label": candidate.label,
        "value": _clean_value(candidate.value),
        "source": candidate.source,
        "line_number": candidate.line_number,
        "suggested_action": "review_or_map",
    }


def _dedupe_unknowns(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    deduped: list[dict[str, Any]] = []
    for item in items:
        key = (item["label"].lower(), item["value"].lower())
        if key not in seen:
            seen.add(key)
            deduped.append(item)
    return deduped


def _normalize_text(text: str) -> str:
    text = text.replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _normalize_label(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", label.lower()).strip()


def _clean_label(label: str) -> str:
    return re.sub(r"\s+", " ", label).strip(" :-|")


def _clean_value(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip(" :-|")
