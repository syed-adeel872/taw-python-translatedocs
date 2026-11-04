# PostgreSQL manual test checklist

This checklist documents how to verify the TranslateDocs PostgreSQL integration
manually. The automated suite uses isolated SQLite databases and does not
exercise PostgreSQL. No production database is required; use a local or free
development database whose name contains `test` or a clearly throwaway database.

## Prerequisites

- A PostgreSQL 15+ instance reachable from the workstation.
- A database and user created for testing only, for example:

  ```sql
  CREATE USER translatedocs_test WITH PASSWORD 'test-only-password';
  CREATE DATABASE translatedocs_test OWNER translatedocs_test;
  ```

- The application virtual environment with dependencies installed.
- A copy of `.env` (never committed) pointing at the test database.

## Safety rules

- Never use a production database or any database containing real data.
- Never commit `.env` or credentials.
- Use synthetic sample documents only.
- Remove smoke-test rows and generated output files after verification.

## Steps

1. Set `DATABASE_URL` in `.env` to a `postgresql+psycopg://` URL for the test
   database, keeping `sslmode=require` for hosted databases:

   ```dotenv
   DATABASE_URL=postgresql+psycopg://translatedocs_test:test-only-password@localhost:5432/translatedocs_test
   AI_PROVIDER=mock
   ```

2. Apply the migration:

   ```powershell
   .\.venv\Scripts\python.exe -m alembic upgrade head
   ```

3. Verify the current revision:

   ```powershell
   .\.venv\Scripts\python.exe -m alembic current
   ```

   Expected: `0001 (head)`.

4. Inspect the schema:

   ```sql
   \dt
   \d jobs
   SELECT * FROM alembic_version;
   ```

   Expected: `jobs` and `alembic_version` tables exist; `jobs` has `status` and
   `created_at` indexes.

5. Start the application:

   ```powershell
   .\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
   ```

6. Check health:

   ```powershell
   Invoke-RestMethod http://127.0.0.1:8000/health
   ```

   Expected: database status `ok`, provider `mock`.

7. Run the synthetic DOCX smoke workflow:

   - Open `http://127.0.0.1:8000`.
   - Upload `samples/sample_export_invoice.docx`, source English, target Spanish.
   - Confirm the job completes and the download succeeds.
   - Record the job ID and output filename.

8. Run the synthetic PDF smoke workflow:

   - Upload `samples/sample_packing_list.pdf`, source English, target French.
   - Confirm the job completes and the download succeeds.
   - Record the job ID and output filename.

9. Verify schema readiness by restarting the application and confirming it starts
   without a migration error.

10. Cleanup:

    ```sql
    DELETE FROM jobs WHERE id IN ('<docx-job-id>', '<pdf-job-id>');
    ```

    Remove the corresponding files under `instance/outputs/`. Do not truncate
    tables or delete unrelated rows.

## What remains unverified

- No automated PostgreSQL test runs in CI or locally.
- Schema readiness was verified against Neon on 2026-11-02 only.
- No load, concurrency, or restart-recovery testing against PostgreSQL.
- No production backup or retention testing.
