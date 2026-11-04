# Demo script

Target length: **60–90 seconds**. Use the synthetic files in `samples/` only. Do not show `.env`, terminal output containing credentials, database URLs, or private documents.

## Preparation

1. Start the app locally:

   ```powershell
   .\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
   ```

2. Open `http://127.0.0.1:8000` in a browser.
3. Keep `samples/sample_export_invoice.docx` and `samples/sample_packing_list.pdf` ready.
4. Confirm the provider is `mock`; do not describe the output as a live AI translation. Do not demonstrate non-Latin/RTL PDF translation; it is not verified and fails safely.

## Recording checklist

- [ ] Open `http://127.0.0.1:8000` and show the upload page.
- [ ] Confirm the development-mode banner says the mock provider is active.
- [ ] DOCX: upload `samples/sample_export_invoice.docx`, source English, target Spanish.
- [ ] Show the completed heading, output filename `sample_export_invoice-es.docx`, segment count, character count, and download button.
- [ ] Download the DOCX and open it in Word or LibreOffice; show translated body text, table text, header, footer, and preserved heading/bold formatting.
- [ ] PDF: upload `samples/sample_packing_list.pdf`, source English, target French.
- [ ] Show the completed heading, output filename `sample_packing_list-fr.pdf`, segment count, character count, and download button.
- [ ] Download the PDF and open it; show translated text on both pages and state the layout limitations.
- [ ] Optionally show the architecture page and the security limitations.
- [ ] Keep `.env`, terminal output, database URLs, job tokens, and private documents off screen.

## Recording flow

### 0:00–0:10 — Opening

**Show:** Upload page.

**Say:**

> TranslateDocs is a FastAPI application that translates DOCX and PDF documents through a provider abstraction. This demo uses the deterministic mock provider, so it runs without paid API calls.

### 0:10–0:30 — DOCX translation

**Do:**

1. Choose `sample_export_invoice.docx`.
2. Set source language to English.
3. Set target language to Spanish.
4. Submit the form.

**Say:**

> The upload is validated, stored under a generated name, and queued as a background job. The browser polls the job status while the DOCX processor translates text runs and preserves core formatting.

**Show:** The completed job page.

**Point out:**

- Heading: `Translation complete.`
- Output filename: `sample_export_invoice-es.docx`
- Segment and character counts.
- Download button.
- Download and open the DOCX to show translated body, table, header, and footer text with preserved heading and bold formatting.

**Say:**

> The completed job exposes a download URL and the translated output filename. The smoke verification for this sample processed 19 segments and preserved the heading style, tables, headers, footers, and bold formatting across body paragraphs and table cells.

### 0:30–0:55 — PDF translation

**Do:**

1. Return to the upload page.
2. Choose `sample_packing_list.pdf`.
3. Set source language to English.
4. Set target language to French.
5. Submit the form.

**Say:**

> PDFs use an in-place redaction and overlay path. The original page count, page sizes, images, vector graphics, and detected solid backgrounds are preserved where safe. Text over raster images or uncertain backgrounds is rejected instead of rebuilding the page.

**Show:** The completed job page and output filename `sample_packing_list-fr.pdf`. Download and open the PDF to show translated text on both pages.

**Say:**

> The offline test suite verifies the two-page PDF path, including redaction, source-text removal, and preserved page dimensions. Text baked into raster image pixels is not removed or translated.

### 0:55–1:15 — Architecture and limitations

**Show:** The job page and, optionally, `docs/architecture.md`.

**Say:**

> Jobs are persisted in the configured database (PostgreSQL in the verified setup; SQLite in the automated tests), schema readiness is checked at startup, and downloads are served only for completed jobs. Uploads are deleted after processing; outputs remain until cleaned up.

> This is not production-ready. It has no authentication, rate limiting, CSRF protection, or output retention policy, so it should not be exposed publicly in its current form.

### 1:15–1:30 — Close

**Say:**

> The repository includes 203 passing and 2 skipped automated tests, genuine screenshots, a demo script, and explicit limitations. The remaining demo deliverable is recording this walkthrough.

## After recording (Loom)

1. Record the walkthrough with Loom (or an equivalent screen recorder) using the flow above. Keep `.env`, terminals, database URLs, job tokens, and private documents off screen.
2. Upload the recording to Loom and copy the share URL.
3. Paste the share URL into `README.md` in the "Demo video" section, replacing the placeholder `https://www.loom.com/share/<recorded-demo-id>`.
4. Record the job IDs and output filenames created during the demo, then remove only those rows and generated files. Do not truncate tables or delete unrelated data.
5. Do not claim a deployment or public URL; the demo remains a local recorded demonstration unless an employer authorizes otherwise.
