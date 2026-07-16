# Local ITR Income Calculation System

A fully local Indian income aggregation, reconciliation and tax-estimation workspace. It is **not an income-tax filing portal** and does not submit an ITR.

## Start with one command

Requirements:

- Python 3.12 or newer
- Node.js 18 or newer and npm
- Tesseract OCR in `PATH` for scanned PDFs
- Java in `PATH` for the Tabula fallback
- Optional: Ghostscript for some Camelot workflows

From the project folder:

```bash
python main.py
```

On first launch the script creates `.venv`, installs Python packages, installs frontend dependencies, builds React, starts FastAPI, and opens:

```text
http://127.0.0.1:8000
```

Useful launch options:

```bash
python main.py --no-browser
python main.py --rebuild
python main.py --host 127.0.0.1 --port 8000
```

## What is included

- FastAPI + SQLAlchemy + SQLite backend
- React + Vite + TailwindCSS + shadcn-style copied components
- React Query, Recharts and server-side transaction pagination
- PDF extraction with PyMuPDF and pdfplumber
- Camelot and Tabula fallbacks
- Automatic Tesseract OCR for pages with little/no embedded text
- CSV/Excel processing with Pandas and a Polars large-file fast path
- TXT, DOCX and safe multi-ZIP bundle processing
- Password-protected PDF and ZIP retry flow; passwords stay in process memory and are never written to disk
- Automatic document detection for AIS, TIS, Form 16/16A, Form 26AS, bank/card statements, broker/demat records, GST reports, salary slips and more
- Header/filename-prioritized institution detection so counterparty banks in narrations cannot claim statement ownership
- Running-balance, statement-period and debit/credit integrity checks on extracted statements
- Explainable offline narration classification with confidence scores
- User-approved recurring narration rules and grouped bulk review actions
- Conservative credit analysis: uncertain credits enter the review queue rather than being silently taxed
- Duplicate detection across documents using amount, date, UTR/reference, narration and counterparty similarity
- Exact duplicate-file and ZIP-member detection, including renamed copies
- Bulk statement selection and manual merging into one bank account
- Safe document removal with cleanup of imported and derived records
- Two-sided self-transfer detection across owned accounts
- Explicit account-ownership confirmation before self-transfers may be excluded
- Normalized tables for users, banks, accounts, transactions, documents/pages, income, expenses, investments, deductions, gains, interest, dividends, TDS, AIS, 26AS, audit logs and review items
- Tax estimates for FY 2022-23 through FY 2025-26
- Tax-readiness gate that marks estimates provisional while credits or authoritative evidence remain unresolved
- Old/new regime comparison, rebate, surcharge, cess and standard deduction handling
- Deduction suggestions based on local evidence
- AIS and 26AS reconciliation views
- Excel, CSV, JSON and PDF reports
- Optional SQLCipher database encryption

## Privacy and storage

All processing is local. Uploaded documents are copied under `data/uploads/`. The SQLite database is `data/itr_local.db`. Generated reports are under `data/exports/`.

Runtime data and common financial-document formats are excluded by `.gitignore`. Only the explicitly synthetic CSVs under `sample_data/` are intended for source control. Always review `git status` before publishing a fork.

PDF passwords are kept only in an in-memory dictionary while a document is being processed. They are removed immediately after processing and are never logged or stored.

### Optional database encryption

SQLite itself is not encrypted by default. To use SQLCipher, install a working SQLCipher runtime and:

```bash
.venv/bin/python -m pip install -r requirements-optional.txt
```

On Windows, use `.venv\Scripts\python.exe`. Then set `ITR_DB_KEY` before launch. If SQLCipher is unavailable, the app fails clearly rather than pretending the database is encrypted.

## Architecture

```text
backend/app/
  api/              FastAPI routes
  classification/   offline rule/fuzzy classifier
  core/             settings
  database/         SQLAlchemy engine/session
  models/           normalized ORM entities
  ocr/              Tesseract OCR
  parsers/          PDF, tabular, text, DOCX and ZIP parsers
  reports/          CSV/XLSX/JSON/PDF exports
  services/         import, duplicate, transfer, summary, reconciliation
  tax/              financial-year rules and calculator
  utils/            amount/date helpers
frontend/src/
  components/ui/    shadcn-style local components
  pages/            dashboard and workflow screens
backend/tests/       unit and integration-oriented tests
sample_data/         sample bank and AIS files
```

## Tests

After the first launch has created `.venv`:

```bash
.venv/bin/python -m pytest
```

Windows:

```powershell
.venv\Scripts\python.exe -m pytest
```

## Accuracy and review policy

Financial statements vary widely. The parser uses multiple extraction strategies, but every inferred classification remains reviewable. Unknown credits default to **Needs Review**, not taxable income. Capital-gain FIFO calculations require normalized buy/sell quantity data; incomplete broker documents remain review items.

Tax estimates are labelled **incomplete** until all pending credits are resolved, a configured rule set exists, and at least one authoritative source (AIS, TIS, Form 26AS, Form 16 or Form 16A) is present. A displayed provisional figure is never a filing-ready figure.

Duplicate matching is cross-document by default. Within one statement, a repeated amount/date/narration is not suppressed unless a durable UTR or reference number is identical. Reprocessing a document replaces its previously derived rows only after parsing succeeds.

Tax law changes. Built-in rules are versioned in `backend/app/tax/rules.py`. Review the configured year before relying on an estimate, especially for special-rate capital gains, surcharge marginal relief, residency, deductions, exemptions, brought-forward losses, set-offs, indexation and treaty claims.

## Supported extension points

- Add bank-specific parsers under `backend/app/parsers/`
- Add classification rules in `backend/app/classification/engine.py`
- Add/update financial-year rules in `backend/app/tax/rules.py`
- Add report datasets in `backend/app/reports/exporter.py`
- Add future financial years from Settings/API; tax estimation remains disabled until a rule set is configured
