# Kamei Lab Budget Web

This Django application is the parallel web version of the existing Streamlit
budget manager. Google Sheets remain the source of truth during validation.

## Local verification

```bash
python -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python manage.py migrate
.venv/bin/python manage.py sync_sheets
.venv/bin/python manage.py verify_streamlit_parity
ENABLE_SHEET_WRITES=true .venv/bin/python manage.py runserver
```

Local development may reuse `../streamlit_app/.streamlit/secrets.toml`.
Production never reads that file and uses Cloud Run Application Default
Credentials. The gateway requests a read-only Sheets scope unless
`ENABLE_SHEET_WRITES=true`.

## Safety boundary

- Dashboard and transactions remain read-only in the parallel web UI.
- Refresh copies Google Sheet values into a mirror and compares all totals.
- Every lab member may upload PDF review drafts.
- Registration requires both `ENABLE_SHEET_WRITES=true` and membership in
  `SHEET_WRITE_ALLOWED_EMAILS`. The staging pilot limits this list to the PI;
  Team Lead and Budget Manager registration waits for durable draft routing.
- Registration is serialized with a process lock, carries a durable PDF hash,
  checks every registered fiscal year for duplicates, reads the Sheet row back,
  and refreshes the web mirror before reporting success.
- The staging service must remain at a maximum of one Cloud Run instance while
  it uses temporary SQLite. Drafts may disappear on a restart; registered Sheet
  transactions do not.
- The Streamlit application remains unchanged and continues to be the production entry point during parallel validation.

## Reversible Sheet verification

Run only with write mode explicitly enabled. The command writes a USD 0.01
verification transaction, reads it back, refreshes the mirror, removes the row,
and compares the complete transaction row set with its original state.

```bash
ENABLE_SHEET_WRITES=true .venv/bin/python manage.py verify_invoice_roundtrip \
  --fiscal-year FY2025-26 --team "Core Lab"
```
