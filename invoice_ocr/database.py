from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import oracledb

from .config import Settings


def save_invoice_result(result: dict[str, Any], metadata: dict[str, Any]) -> dict[str, int]:
    if not Settings.oracle_enabled():
        raise RuntimeError("Oracle persistence is disabled or incomplete.")

    connection = oracledb.connect(
        user=Settings.ORACLE_USER,
        password=Settings.ORACLE_PASSWORD,
        dsn=Settings.ORACLE_DSN,
    )
    try:
        with connection.cursor() as cursor:
            invoice_id_var = cursor.var(oracledb.NUMBER)
            cursor.execute(
                """
                INSERT INTO invoices (
                    file_name,
                    file_type,
                    invoice_number,
                    invoice_date,
                    vendor_name,
                    total_amount,
                    taxable_amount,
                    gstin,
                    invoice_type,
                    currency,
                    uploaded_by,
                    ocr_status,
                    validation_status,
                    raw_text,
                    extracted_json
                ) VALUES (
                    :file_name,
                    :file_type,
                    :invoice_number,
                    :invoice_date,
                    :vendor_name,
                    :total_amount,
                    :taxable_amount,
                    :gstin,
                    :invoice_type,
                    :currency,
                    :uploaded_by,
                    'SUCCESS',
                    'PENDING',
                    :raw_text,
                    :extracted_json
                )
                RETURNING invoice_id INTO :invoice_id
                """,
                {
                    "file_name": metadata["file_name"],
                    "file_type": metadata["file_type"],
                    "invoice_number": _field_value(result, "invoice_number"),
                    "invoice_date": _to_date(_field_value(result, "invoice_date")),
                    "vendor_name": _field_value(result, "vendor_name"),
                    "total_amount": _to_number(_field_value(result, "total_amount")),
                    "taxable_amount": _to_number(_field_value(result, "taxable_amount")),
                    "gstin": _field_value(result, "gstin"),
                    "invoice_type": _field_value(result, "invoice_type"),
                    "currency": _field_value(result, "currency"),
                    "uploaded_by": metadata["uploaded_by"],
                    "raw_text": result["raw_text"],
                    "extracted_json": json.dumps(result, ensure_ascii=False),
                    "invoice_id": invoice_id_var,
                },
            )
            invoice_id = int(invoice_id_var.getvalue()[0])

            cursor.execute(
                """
                INSERT INTO ocr_jobs (
                    invoice_id,
                    job_status,
                    input_file_name,
                    output_json,
                    completed_at
                ) VALUES (
                    :invoice_id,
                    'SUCCESS',
                    :input_file_name,
                    :output_json,
                    SYSTIMESTAMP
                )
                """,
                {
                    "invoice_id": invoice_id,
                    "input_file_name": metadata["file_name"],
                    "output_json": json.dumps(result, ensure_ascii=False),
                },
            )
        connection.commit()
        return {"invoice_id": invoice_id}
    finally:
        connection.close()


def _field_value(result: dict[str, Any], field_name: str) -> str | None:
    return result["flat_fields"].get(field_name)


def _to_number(value: str | None) -> float | None:
    if value in (None, ""):
        return None
    return float(value)


def _to_date(value: str | None) -> datetime | None:
    if value in (None, ""):
        return None

    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%Y-%m-%d", "%d %b %Y", "%d %B %Y"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    raise ValueError(f"Unsupported invoice_date format: {value}")
