from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import oracledb

from .config import Settings


def save_invoice_result(result: dict[str, Any], metadata: dict[str, Any]) -> dict[str, int]:
    if not Settings.oracle_enabled():
        raise RuntimeError("Oracle persistence is disabled or incomplete.")

    connection = _connect()
    try:
        with connection.cursor() as cursor:
            document_id = _insert_document(cursor, result, metadata)
            invoice_id = _insert_invoice(cursor, result, metadata)
            _link_document_to_invoice(cursor, document_id, invoice_id)
            _insert_extraction_results(cursor, document_id, invoice_id, result)
            _insert_dynamic_fields(cursor, invoice_id, result)
            _insert_missing_fields(cursor, invoice_id, result)

        connection.commit()
        return {"document_id": document_id, "invoice_id": invoice_id}
    finally:
        connection.close()


def load_learning_hints() -> list[dict[str, Any]]:
    if not Settings.oracle_learning_enabled():
        return []

    connection = _connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT db_column_name, synonym_text, confidence_boost
                FROM inv_field_synonyms
                WHERE is_active = 'Y'
                """
            )
            return [
                {
                    "mapped_column": row[0],
                    "field_label_raw": row[1],
                    "confidence_boost": float(row[2] or 0),
                }
                for row in cursor.fetchall()
            ]
    except oracledb.Error:
        return []
    finally:
        connection.close()


def save_learning_feedback(payload: dict[str, Any]) -> dict[str, str]:
    if not Settings.oracle_enabled():
        raise RuntimeError("Oracle persistence is disabled or incomplete.")

    raw_label = str(payload.get("field_label_raw") or "").strip()
    corrected_column = str(
        payload.get("corrected_to_column") or payload.get("mapped_to_column") or ""
    ).strip().upper()
    if not raw_label or not corrected_column:
        raise ValueError("field_label_raw and corrected_to_column are required.")

    connection = _connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                MERGE INTO inv_field_synonyms target
                USING (
                    SELECT :db_column_name AS db_column_name,
                           :synonym_text AS synonym_text
                    FROM dual
                ) source
                ON (
                    target.db_column_name = source.db_column_name
                    AND UPPER(target.synonym_text) = UPPER(source.synonym_text)
                )
                WHEN MATCHED THEN UPDATE SET
                    target.confidence_boost = LEAST(NVL(target.confidence_boost, 0) + 0.05, 0.50),
                    target.is_active = 'Y'
                WHEN NOT MATCHED THEN INSERT (
                    db_column_name,
                    db_table_name,
                    synonym_text,
                    confidence_boost,
                    is_active
                ) VALUES (
                    :db_column_name,
                    'INV_INVOICES',
                    :synonym_text,
                    0.15,
                    'Y'
                )
                """,
                {"db_column_name": corrected_column, "synonym_text": raw_label},
            )
            cursor.execute(
                """
                INSERT INTO inv_ai_learning_log (
                    document_id,
                    invoice_id,
                    vendor_id,
                    field_label_raw,
                    mapped_to_column,
                    was_correct,
                    corrected_to_column,
                    ai_model,
                    prompt_used,
                    response_received,
                    processing_time_ms
                ) VALUES (
                    :document_id,
                    :invoice_id,
                    :vendor_id,
                    :field_label_raw,
                    :mapped_to_column,
                    :was_correct,
                    :corrected_to_column,
                    'offline_scoring_v1',
                    :prompt_used,
                    :response_received,
                    0
                )
                """,
                {
                    "document_id": _to_int(payload.get("document_id")),
                    "invoice_id": _to_int(payload.get("invoice_id")),
                    "vendor_id": _to_int(payload.get("vendor_id")),
                    "field_label_raw": raw_label,
                    "mapped_to_column": str(payload.get("mapped_to_column") or "").upper() or None,
                    "was_correct": "Y" if payload.get("was_correct") in (True, "Y", "true", "TRUE") else "N",
                    "corrected_to_column": corrected_column,
                    "prompt_used": "manual_feedback",
                    "response_received": json.dumps(payload, ensure_ascii=False),
                },
            )
        connection.commit()
        return {"status": "learned", "mapped_column": corrected_column}
    finally:
        connection.close()


def _connect() -> oracledb.Connection:
    return oracledb.connect(
        user=Settings.ORACLE_USER,
        password=Settings.ORACLE_PASSWORD,
        dsn=Settings.ORACLE_DSN,
    )


def _insert_document(cursor: oracledb.Cursor, result: dict[str, Any], metadata: dict[str, Any]) -> int:
    document_id_var = cursor.var(oracledb.NUMBER)
    cursor.execute(
        """
        INSERT INTO inv_documents (
            file_name,
            mime_type,
            file_size,
            upload_source,
            ocr_status,
            ocr_raw_text,
            ocr_structured_json,
            ocr_confidence,
            ocr_engine,
            ocr_processed_date,
            page_count,
            created_by
        ) VALUES (
            :file_name,
            :mime_type,
            :file_size,
            'API',
            'COMPLETED',
            :raw_text,
            :structured_json,
            :ocr_confidence,
            'TESSERACT_OFFLINE_SCORING',
            SYSTIMESTAMP,
            :page_count,
            :created_by
        )
        RETURNING document_id INTO :document_id
        """,
        {
            "file_name": metadata["file_name"],
            "mime_type": metadata["file_type"],
            "file_size": metadata.get("file_size"),
            "raw_text": result["raw_text"],
            "structured_json": json.dumps(result, ensure_ascii=False),
            "ocr_confidence": result.get("ocr_confidence"),
            "page_count": result.get("page_count", 1),
            "created_by": metadata["uploaded_by"],
            "document_id": document_id_var,
        },
    )
    return int(document_id_var.getvalue()[0])


def _insert_invoice(cursor: oracledb.Cursor, result: dict[str, Any], metadata: dict[str, Any]) -> int:
    structured = result.get("structured_fields", {})
    missing_count = len(result.get("missing_fields", []))
    invoice_id_var = cursor.var(oracledb.NUMBER)
    cursor.execute(
        """
        INSERT INTO inv_invoices (
            invoice_number,
            vendor_name_raw,
            invoice_date,
            due_date,
            currency,
            subtotal,
            cgst_amount,
            sgst_amount,
            igst_amount,
            tax_amount,
            discount_amount,
            shipping_amount,
            total_amount,
            amount_in_words,
            po_number,
            grn_number,
            vendor_gstin,
            buyer_gstin,
            place_of_supply,
            hsn_sac_code,
            irn_number,
            eway_bill_no,
            bank_account_no,
            bank_ifsc,
            bank_name,
            payment_terms,
            description,
            notes,
            status,
            extraction_confidence,
            is_complete,
            missing_field_count,
            created_by
        ) VALUES (
            :invoice_number,
            :vendor_name_raw,
            :invoice_date,
            :due_date,
            :currency,
            :subtotal,
            :cgst_amount,
            :sgst_amount,
            :igst_amount,
            :tax_amount,
            :discount_amount,
            :shipping_amount,
            :total_amount,
            :amount_in_words,
            :po_number,
            :grn_number,
            :vendor_gstin,
            :buyer_gstin,
            :place_of_supply,
            :hsn_sac_code,
            :irn_number,
            :eway_bill_no,
            :bank_account_no,
            :bank_ifsc,
            :bank_name,
            :payment_terms,
            :description,
            :notes,
            :status,
            :extraction_confidence,
            :is_complete,
            :missing_field_count,
            :created_by
        )
        RETURNING invoice_id INTO :invoice_id
        """,
        {
            "invoice_number": structured.get("INVOICE_NUMBER"),
            "vendor_name_raw": structured.get("VENDOR_NAME_RAW"),
            "invoice_date": _to_date(structured.get("INVOICE_DATE")),
            "due_date": _to_date(structured.get("DUE_DATE")),
            "currency": structured.get("CURRENCY"),
            "subtotal": _to_number(structured.get("SUBTOTAL")),
            "cgst_amount": _to_number(structured.get("CGST_AMOUNT")),
            "sgst_amount": _to_number(structured.get("SGST_AMOUNT")),
            "igst_amount": _to_number(structured.get("IGST_AMOUNT")),
            "tax_amount": _to_number(structured.get("TAX_AMOUNT")),
            "discount_amount": _to_number(structured.get("DISCOUNT_AMOUNT")),
            "shipping_amount": _to_number(structured.get("SHIPPING_AMOUNT")),
            "total_amount": _to_number(structured.get("TOTAL_AMOUNT")),
            "amount_in_words": structured.get("AMOUNT_IN_WORDS"),
            "po_number": structured.get("PO_NUMBER"),
            "grn_number": structured.get("GRN_NUMBER"),
            "vendor_gstin": structured.get("VENDOR_GSTIN"),
            "buyer_gstin": structured.get("BUYER_GSTIN"),
            "place_of_supply": structured.get("PLACE_OF_SUPPLY"),
            "hsn_sac_code": structured.get("HSN_SAC_CODE"),
            "irn_number": structured.get("IRN_NUMBER"),
            "eway_bill_no": structured.get("EWAY_BILL_NO"),
            "bank_account_no": structured.get("BANK_ACCOUNT_NO"),
            "bank_ifsc": structured.get("BANK_IFSC"),
            "bank_name": structured.get("BANK_NAME"),
            "payment_terms": structured.get("PAYMENT_TERMS"),
            "description": structured.get("DESCRIPTION"),
            "notes": structured.get("NOTES"),
            "status": "INCOMPLETE" if missing_count else "EXTRACTED",
            "extraction_confidence": _average_confidence(result),
            "is_complete": "N" if missing_count else "Y",
            "missing_field_count": missing_count,
            "created_by": metadata["uploaded_by"],
            "invoice_id": invoice_id_var,
        },
    )
    return int(invoice_id_var.getvalue()[0])


def _link_document_to_invoice(cursor: oracledb.Cursor, document_id: int, invoice_id: int) -> None:
    cursor.execute(
        "UPDATE inv_documents SET invoice_id = :invoice_id WHERE document_id = :document_id",
        {"invoice_id": invoice_id, "document_id": document_id},
    )


def _insert_extraction_results(
    cursor: oracledb.Cursor,
    document_id: int,
    invoice_id: int,
    result: dict[str, Any],
) -> None:
    rows = [
        {
            "document_id": document_id,
            "invoice_id": invoice_id,
            "field_label": item.get("label"),
            "field_value": item.get("value"),
            "mapped_column": item.get("mapped_column"),
            "confidence_score": item.get("confidence"),
            "page_number": 1,
            "ai_reasoning": item.get("reason"),
        }
        for item in result.get("extraction_results", [])
    ]
    rows.extend(
        {
            "document_id": document_id,
            "invoice_id": invoice_id,
            "field_label": item.get("label"),
            "field_value": item.get("value"),
            "mapped_column": None,
            "confidence_score": None,
            "page_number": 1,
            "ai_reasoning": "discovered_unknown_field",
        }
        for item in result.get("discovered_fields", [])
    )
    if not rows:
        return

    cursor.executemany(
        """
        INSERT INTO inv_extraction_results (
            document_id,
            invoice_id,
            field_label,
            field_value,
            mapped_column,
            confidence_score,
            page_number,
            ai_reasoning
        ) VALUES (
            :document_id,
            :invoice_id,
            :field_label,
            :field_value,
            :mapped_column,
            :confidence_score,
            :page_number,
            :ai_reasoning
        )
        """,
        rows,
    )


def _insert_missing_fields(cursor: oracledb.Cursor, invoice_id: int, result: dict[str, Any]) -> None:
    rows = [
        {
            "invoice_id": invoice_id,
            "field_name": item["mapped_column"],
            "field_label": item["field_name"],
            "message": item["message"],
        }
        for item in result.get("missing_fields", [])
    ]
    if not rows:
        return

    cursor.executemany(
        """
        INSERT INTO inv_missing_fields (
            invoice_id,
            field_name,
            field_label,
            issue_type,
            message
        ) VALUES (
            :invoice_id,
            :field_name,
            :field_label,
            'MISSING',
            :message
        )
        """,
        rows,
    )


def _insert_dynamic_fields(cursor: oracledb.Cursor, invoice_id: int, result: dict[str, Any]) -> None:
    for item in result.get("discovered_fields", []):
        raw_label = str(item.get("label") or "").strip()
        value = str(item.get("value") or "").strip()
        if not raw_label or not value:
            continue

        field_name = _dynamic_field_name(raw_label)
        cursor.execute(
            """
            MERGE INTO inv_dynamic_fields target
            USING (
                SELECT :field_name AS field_name,
                       :display_name AS display_name
                FROM dual
            ) source
            ON (target.field_name = source.field_name)
            WHEN MATCHED THEN UPDATE SET
                target.display_name = COALESCE(target.display_name, source.display_name)
            WHEN NOT MATCHED THEN INSERT (
                field_name,
                display_name,
                data_type,
                is_known_business
            ) VALUES (
                :field_name,
                :display_name,
                'TEXT',
                'N'
            )
            """,
            {"field_name": field_name, "display_name": raw_label[:200]},
        )
        cursor.execute(
            "SELECT field_id FROM inv_dynamic_fields WHERE field_name = :field_name",
            {"field_name": field_name},
        )
        field_id = int(cursor.fetchone()[0])
        cursor.execute(
            """
            INSERT INTO inv_invoice_field_values (
                invoice_id,
                field_id,
                raw_label,
                field_value,
                confidence_score,
                source_type
            ) VALUES (
                :invoice_id,
                :field_id,
                :raw_label,
                :field_value,
                :confidence_score,
                'OCR_DISCOVERED'
            )
            """,
            {
                "invoice_id": invoice_id,
                "field_id": field_id,
                "raw_label": raw_label[:200],
                "field_value": value[:4000],
                "confidence_score": item.get("confidence"),
            },
        )


def _average_confidence(result: dict[str, Any]) -> float:
    values = [
        float(item.get("confidence"))
        for item in result.get("extraction_results", [])
        if item.get("confidence") is not None
    ]
    return round(sum(values) / len(values), 2) if values else 0.0


def _to_number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return float(str(value).replace(",", ""))


def _to_date(value: Any) -> datetime | None:
    if value in (None, ""):
        return None

    value = str(value)
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%Y-%m-%d", "%d %b %Y", "%d %B %Y"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def _to_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


def _dynamic_field_name(label: str) -> str:
    value = "".join(ch if ch.isalnum() else "_" for ch in label.upper())
    value = "_".join(part for part in value.split("_") if part)
    return f"DISC_{value[:90]}" if value else "DISC_UNKNOWN_FIELD"
