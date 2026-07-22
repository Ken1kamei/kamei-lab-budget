# Web parallel validation

Last verified: 2026-07-22 (Asia/Dubai)

## Scope

- Existing Streamlit remains the production application.
- Django staging mirrors Google Sheets and has a feature-flagged invoice
  registration path.
- Uploaded invoices remain temporary review drafts until a Team Lead, Budget
  Manager, or PI confirms the extracted fields.
- Existing Streamlit remains the production application and is unchanged.

## Staging

- Service: `kamei-lab-budget-web-staging`
- Revision: `kamei-lab-budget-web-staging-00008-wzv`
- Region: `me-central1`
- URL: <https://kamei-lab-budget-web-staging-678641983168.me-central1.run.app>
- Access: Google Cloud IAP plus the application lab-member allowlist
- Scaling: zero idle instances, maximum one instance

The one-instance limit is required while staging uses temporary SQLite and a
cross-process file lock for Sheet writes. A durable database and distributed
lock are required before production cutover or scale-out.

## Controlled staging write path

- `ENABLE_SHEET_WRITES=false` is the default and keeps both the endpoint and
  service layer read-only.
- Member: upload and view their own review drafts.
- Registration is additionally restricted by `SHEET_WRITE_ALLOWED_EMAILS`.
  During the temporary-SQLite pilot this list contains only the PI.
- Team Lead and Budget Manager registration stays disabled until durable draft
  routing is stored in Cloud SQL.
- Registration always writes `Allocated`; a `Cancelled` transaction cannot be
  restored by re-importing its PDF.
- The PDF SHA-256 marker is checked across all registered fiscal years.
- Same-Team duplicate identity requires the same Vendor and Invoice Number;
  PO-only matching never overwrites a row.
- Sheet writes are serialized and read back field-by-field before the draft is
  marked imported. A later mirror-sync failure is shown as a retryable warning;
  it never makes a verified Sheet transaction appear unregistered.

## Verified parity

| Fiscal year | Source rows | Mirror rows | Total budget | Allocated | Available | Result |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| FY2025-26 | 27 | 27 | $169,500.00 | $10,698.03 | $158,801.97 | Exact match |
| FY2026-27 | 0 | 0 | $169,500.00 | $0.00 | $169,500.00 | Exact match |

The verification command compares Django output against the existing
Streamlit calculation functions, including fiscal-year routing, currency
conversion, team allocations, and `Cancelled` exclusion.

## Tests completed

- Django test suite: 25 passed.
- Django deployment check: no issues.
- Google Sheet sync: row counts and normalized transaction rows matched.
- Dashboard: fiscal-year selection and all four FY2025-26 metrics verified.
- Transactions: 27 FY2025-26 rows and transaction IDs verified.
- Invoice import: two real PDFs uploaded together and retained as separate
  review drafts; the review form renders parsed date, FY, category, vendor,
  description, PO, invoice, currency, amount, and team.
- Deployed parser: `INS6000_9216658.PDF` produced PeopleSoft Inventory,
  invoice `INS6000_9216658`, USD 151.95, date 2026-03-26, description, fiscal
  year, category, and team controls through the authenticated staging UI.
- Reversible Sheet write: a temporary USD 0.01 row was written to FY2025-26,
  read back exactly once, mirrored with `Matched`, and removed. The complete
  27-row transaction set and totals matched the original after restoration.
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

Set `ENABLE_SHEET_WRITES=false` to disable new registrations immediately. The
existing Streamlit application remains available. The reversible verification
row has been removed and no dummy transaction remains.

## Promotion gate

Do not replace Streamlit or increase Cloud Run beyond one instance until the
Django app has a durable database, distributed idempotency/outbox, durable PDF
storage, edit/cancel audit history, and a second production-data round trip
after those components are installed.
