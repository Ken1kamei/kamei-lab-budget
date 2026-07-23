# Kamei Lab Integrated Web

This Django application is the integrated web version of the Kamei Lab Budget
Manager, Portal, Project Tracker, and Notebooks/Protocols. Google Sheets remain
the structured-data source of truth, private GCS buckets hold uploaded files,
and PostgreSQL provides the fast web mirror, audit trail, durable import queue,
and idempotency.

The existing Streamlit application remains available during the measured
parallel-run period. Do not switch the production entry point until the two
systems have matched for at least one week.

## Local verification

```bash
python -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python manage.py migrate
.venv/bin/python manage.py sync_sheets
.venv/bin/python manage.py verify_streamlit_parity
.venv/bin/python manage.py runserver
```

Local development may reuse `../streamlit_app/.streamlit/secrets.toml`.
Production never reads that file and uses Cloud Run Application Default
Credentials. The gateway requests a read-only Sheets scope unless
`ENABLE_SHEET_WRITES=true`.

## Supported workflows

- Fiscal-year dashboard, team/category/monthly reports, filters, and CSV export.
- Manual transaction creation, correction, fiscal-year moves, and cancellation.
- Multi-PDF upload with private durable object storage and review-before-import.
- NYUAD ERB Excel preview and verified multi-row registration.
- Category budgets, teams, exchange rates, members/roles, and fiscal-year creation.
- PI, Budget Manager, Team Leader, Member, and unknown-user access boundaries.
- Every Sheet mutation is serialized, read back, mirrored, and audited before
  the UI reports success. Repeated submissions use durable idempotency keys.
- Shared launcher and registry administration at `/portal/`.
- Project, milestone, experiment, review, and next-action workflows at `/tracker/`,
  including per-project Excel Gantt import, preview, and timeline display.
- Searchable protocol and notebook registry plus private uploads at `/knowledge/`.

## Production requirements

- Cloud SQL PostgreSQL configured through the Secret Manager-backed
  `CLOUD_DATABASE_URL` (or `DATABASE_URL` for local compatibility).
- A private GCS bucket configured through `INVOICE_BUCKET`.
- A separate private GCS bucket configured through `KNOWLEDGE_BUCKET`; public
  access prevention and uniform bucket-level access must remain enabled.
- Cloud Run IAP with `IAP_EXPECTED_AUDIENCE` and the approved NYU users.
- `ENABLE_SHEET_WRITES=true` only after the PostgreSQL migration and smoke test.
- `SHEET_WRITE_ALLOWED_EMAILS` set to the accounts permitted for the rollout;
  `*` enables each role's normal application permission.
- Run `manage.py migrate`, `manage.py sync_sheets`, and `manage.py verify_parity`
  as release/scheduled jobs. They are intentionally not run by every web startup.

Recommended Cloud Run job schedule after PostgreSQL is connected:

- Every 5 minutes: `python manage.py sync_sheets`, then
  `python manage.py sync_lab_apps`
- Daily after the sync: `python manage.py verify_streamlit_parity`
- Each release: `python manage.py migrate --noinput`, then one `sync_sheets` and
  one `sync_lab_apps`

The integrated-app parity and reversible release checks are:

```bash
python manage.py verify_lab_apps_parity
python manage.py verify_lab_apps_roundtrip --actor kk4801@nyu.edu
```

The round trip temporarily adds and removes one Project row and one private GCS
object. It fails unless both sources are restored exactly.

The scheduled job and web service must use the same database URL, service
account, registry/Sheet configuration, and private invoice bucket. Alert on any
non-zero exit; a parity mismatch is deliberately returned as a failed job.

## Reversible Sheet verification

Run only with write mode explicitly enabled. The first command temporarily sets
the selected category allocation, verifies the Sheet and web mirror, then restores
the original value. The second creates a USD 0.01 transaction, verifies it,
cancels it to prove the budget is released, deletes it, and compares the complete
row set with its original state. The storage check writes, reads, and removes a
temporary private invoice object without changing the ledger.

```bash
ENABLE_SHEET_WRITES=true .venv/bin/python manage.py verify_budget_roundtrip \
  --fiscal-year FY2026-27 --category Consumables --amount 10000
```

```bash
ENABLE_SHEET_WRITES=true .venv/bin/python manage.py verify_invoice_roundtrip \
  --fiscal-year FY2025-26 --team "Core Lab"
```

```bash
.venv/bin/python manage.py verify_storage_roundtrip
```
