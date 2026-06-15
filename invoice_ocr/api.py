from __future__ import annotations

import tempfile
from pathlib import Path

from flask import Flask, jsonify, request
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.utils import secure_filename

from .config import Settings
from .database import save_invoice_result
from .extractor import extract_invoice


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = Settings.MAX_UPLOAD_MB * 1024 * 1024

    @app.get("/")
    def index() -> tuple[object, int]:
        return (
            jsonify(
                {
                    "service": Settings.APP_NAME,
                    "status": "running",
                    "endpoints": ["/api/v1/health", "/api/v1/ocr/extract"],
                }
            ),
            200,
        )

    @app.get("/api/v1/health")
    def health() -> tuple[object, int]:
        return jsonify({"status": "ok", "config": Settings.as_public_dict()}), 200

    @app.post("/api/v1/ocr/extract")
    def extract() -> tuple[object, int]:
        auth_error = _validate_api_key()
        if auth_error is not None:
            return auth_error

        uploaded_file = request.files.get("file")
        if uploaded_file is None or uploaded_file.filename == "":
            return jsonify({"error": "Upload a file using form field 'file'."}), 400

        uploaded_by = request.form.get("uploaded_by", "accountant").strip() or "accountant"
        save_result = request.form.get("save_to_oracle", "false").lower() == "true"
        original_name = secure_filename(uploaded_file.filename) or "invoice"
        suffix = Path(original_name).suffix

        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
            uploaded_file.save(temp_file.name)
            temp_path = Path(temp_file.name)

        try:
            result = extract_invoice(temp_path, uploaded_by=uploaded_by)
            response_payload: dict[str, object] = {
                "success": True,
                "message": "Invoice extracted successfully.",
                "result": result,
            }

            if save_result:
                db_result = save_invoice_result(
                    result,
                    {
                        "file_name": original_name,
                        "file_type": uploaded_file.mimetype or "application/octet-stream",
                        "uploaded_by": uploaded_by,
                    },
                )
                response_payload["database"] = db_result

            return jsonify(response_payload), 200
        except Exception as exc:
            return jsonify({"success": False, "error": str(exc)}), 500
        finally:
            temp_path.unlink(missing_ok=True)

    @app.errorhandler(RequestEntityTooLarge)
    def file_too_large(_: RequestEntityTooLarge) -> tuple[object, int]:
        return (
            jsonify(
                {
                    "success": False,
                    "error": f"File exceeds {Settings.MAX_UPLOAD_MB} MB upload limit.",
                }
            ),
            413,
        )

    return app


def _validate_api_key() -> tuple[object, int] | None:
    if not Settings.API_KEY:
        return None

    provided_key = request.headers.get("X-API-Key", "").strip()
    if provided_key == Settings.API_KEY:
        return None
    return jsonify({"success": False, "error": "Unauthorized"}), 401
