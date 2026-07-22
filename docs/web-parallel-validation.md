# Web parallel validation

Last verified: 2026-07-22 (Asia/Dubai)

## Scope

- Existing Streamlit remains the production application.
- Django staging mirrors Google Sheets with read-only credentials.
- The web mirror cannot update or delete Google Sheet data.
- Uploaded invoices remain review drafts in temporary mirror storage.

## Staging

- Service: `kamei-lab-budget-web-staging`
- Region: `me-central1`
- URL: <https://kamei-lab-budget-web-staging-678641983168.me-central1.run.app>
- Access: Google Cloud IAP plus the application lab-member allowlist
- Scaling: zero idle instances, maximum one instance

The one-instance limit is intentional while staging uses temporary SQLite. A
durable database is required before the web application becomes a write path.

## Verified parity

| Fiscal year | Source rows | Mirror rows | Total budget | Allocated | Available | Result |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| FY2025-26 | 27 | 27 | $169,500.00 | $10,698.03 | $158,801.97 | Exact match |
| FY2026-27 | 0 | 0 | $169,500.00 | $0.00 | $169,500.00 | Exact match |

The verification command compares Django output against the existing
Streamlit calculation functions, including fiscal-year routing, currency
conversion, team allocations, and `Cancelled` exclusion.

## Tests completed

- Django test suite: 14 passed.
- Django deployment check: no issues.
- Google Sheet sync: row counts and normalized transaction rows matched.
- Dashboard: fiscal-year selection and all four FY2025-26 metrics verified.
- Transactions: 27 FY2025-26 rows and transaction IDs verified.
- Invoice import: two real PDFs uploaded together and retained as separate
  review drafts.
- Responsive UI: desktop and 390 x 844 mobile viewports had no horizontal
  overflow.
- Browser console: no JavaScript errors.
- IAP: anonymous requests redirect to Google sign-in; direct public Cloud Run
  invocation is disabled.
- IAP user flow: `kk4801@nyu.edu` authenticated successfully and the dashboard,
  transactions, imports, and parity routes returned HTTP 200.
- Cloud fiscal-year switch: FY2025-26 and FY2026-27 changed the URL, selected
  option, metrics, and transaction counts correctly.
- Cloud live parity refresh: run `#3` at `2026-07-22 12:44:17 +04` reported
  `Matched`, 27 source rows, 27 mirror rows, and `Exact match`.
- Cloud browser console: no errors or warnings after the authenticated flow.
- Cloud startup: migrations, both sheet syncs, both parity comparisons, and
  Gunicorn startup completed successfully.

## Rollback

The existing Streamlit application and Google Sheets are unchanged. To stop
the staging experiment, disable or delete only the Cloud Run service
`kamei-lab-budget-web-staging`; no data restoration is necessary.

## Promotion gate

Do not make the Django application the write path until it has a durable
database, transaction-level reconciliation, write-path tests, audit logging,
and a reversible production-data round trip.
