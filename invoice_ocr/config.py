from __future__ import annotations

import os


class Settings:
    APP_NAME = os.getenv("APP_NAME", "invoice-ocr-backend")
    APP_ENV = os.getenv("APP_ENV", "production")
    HOST = os.getenv("HOST", "0.0.0.0")
    PORT = int(os.getenv("PORT", "8000"))
    MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "15"))
    API_KEY = os.getenv("API_KEY", "").strip()
    SAVE_TO_ORACLE = os.getenv("SAVE_TO_ORACLE", "false").lower() == "true"
    ORACLE_USER = os.getenv("ORACLE_USER", "").strip()
    ORACLE_PASSWORD = os.getenv("ORACLE_PASSWORD", "").strip()
    ORACLE_DSN = os.getenv("ORACLE_DSN", "").strip()

    @classmethod
    def as_public_dict(cls) -> dict[str, object]:
        return {
            "app_name": cls.APP_NAME,
            "environment": cls.APP_ENV,
            "max_upload_mb": cls.MAX_UPLOAD_MB,
            "oracle_enabled": cls.oracle_enabled(),
        }

    @classmethod
    def oracle_enabled(cls) -> bool:
        return cls.SAVE_TO_ORACLE and all(
            [cls.ORACLE_USER, cls.ORACLE_PASSWORD, cls.ORACLE_DSN]
        )
