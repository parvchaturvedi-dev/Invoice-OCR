# Invoice OCR Backend

Python + Tesseract backend for extracting invoice data from image and PDF files. The service exposes an HTTP API, supports optional Oracle persistence, and is ready for Docker-based Render deployment.

## Single Run Command

```powershell
.\.venv\Scripts\python.exe -m invoice_ocr
```

The same app entrypoint is used inside Docker and on Render.

## API Endpoints

- `GET /`
- `GET /api/v1/health`
- `POST /api/v1/ocr/extract`

## Extracted Fields

- `invoice_number`
- `invoice_date`
- `vendor_name`
- `total_amount`
- `taxable_amount`
- `gstin`
- `invoice_type`
- `currency`
- `upload_date`
- `uploaded_by`

## Local Setup

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m invoice_ocr
```

## Example Request

```powershell
curl -X POST http://127.0.0.1:8000/api/v1/ocr/extract -F "file=@C:\path\to\invoice.pdf" -F "uploaded_by=accountant"
```

To save directly into Oracle as well:

```powershell
curl -X POST http://127.0.0.1:8000/api/v1/ocr/extract -F "file=@C:\path\to\invoice.pdf" -F "uploaded_by=accountant" -F "save_to_oracle=true"
```

## Environment Variables

- Copy values from `.env.example` into your Render environment variables.
- `PORT=8000`
- `HOST=0.0.0.0`
- `MAX_UPLOAD_MB=15`
- `API_KEY=your-secret-key`
- `SAVE_TO_ORACLE=true`
- `ORACLE_USER=...`
- `ORACLE_PASSWORD=...`
- `ORACLE_DSN=...`

## Oracle Schema

Use [sql/schema.sql](/C:/Users/parvc/OneDrive/Documents/invoice-ocr-project/sql/schema.sql) before enabling Oracle persistence.

## Render Deployment

This repo includes:

- `Dockerfile`
- `render.yaml`

Render can deploy this as a Docker web service without a separate start command because the container runs:

```text
python -m invoice_ocr
```
