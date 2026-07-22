# Kamei Lab Budget Web

This Django application is the read-only parallel web version of the existing Streamlit budget manager. Google Sheets remain the source of truth during validation.

## Local verification

```bash
python -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python manage.py migrate
.venv/bin/python manage.py sync_sheets
.venv/bin/python manage.py verify_streamlit_parity
.venv/bin/python manage.py runserver
```

Local development may reuse `../streamlit_app/.streamlit/secrets.toml`. Production never reads that file and uses Cloud Run Application Default Credentials with the Sheets read-only OAuth scope.

## Safety boundary

- Dashboard and transactions are read-only.
- Refresh copies Google Sheet values into a mirror and compares all totals.
- Invoice imports create review drafts in the mirror only.
- No Google Sheet write method or Drive write scope is present.
- The Streamlit application remains unchanged and continues to be the production entry point during parallel validation.
