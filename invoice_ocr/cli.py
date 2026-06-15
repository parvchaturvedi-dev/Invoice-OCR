from __future__ import annotations

import argparse
import json
from pathlib import Path

from .extractor import extract_invoice


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract invoice fields using Tesseract OCR.")
    parser.add_argument("file", help="Path to invoice image or PDF")
    parser.add_argument("--uploaded-by", default="accountant", help="Uploader name/user id")
    parser.add_argument("--output", help="Optional JSON output file path")
    args = parser.parse_args()

    result = extract_invoice(args.file, uploaded_by=args.uploaded_by)
    json_text = json.dumps(result, indent=2, ensure_ascii=False)

    if args.output:
        Path(args.output).write_text(json_text, encoding="utf-8")
    else:
        print(json_text)


if __name__ == "__main__":
    main()
