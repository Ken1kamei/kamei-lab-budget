# Web parallel validation

Last verified: 2026-07-22 (Asia/Dubai)

## Scope

- Existing Streamlit remains the production application.
- Django staging currently mirrors Google Sheets and retains its controlled
  invoice pilot until the Cloud SQL/GCS promotion below is approved.
- The completed local candidate adds the full Budget workflow: manual
  transactions, edit/cancel, reports, ERB import, Settings, roles, audit and
  durable storage models.
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

The currently deployed one-instance staging revision still uses temporary
SQLite. The new candidate refuses to start in production without a configured
`DATABASE_URL`; it must be deployed with Cloud SQL PostgreSQL and a private GCS
invoice bucket.

## Controlled staging write path

- `ENABLE_SHEET_WRITES=false` is the default and keeps both the endpoint and
  service layer read-only.
- Member: upload and view their own review drafts.
- Registration is additionally restricted by `SHEET_WRITE_ALLOWED_EMAILS`.
  During the temporary-SQLite pilot this list contains only the PI.
- The candidate supports Team Lead and Budget Manager registration within their
  normal role/team scope after Cloud SQL is connected.
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

## Candidate verification completed

- Django test suite: 67 passed.
- Django production deployment check: no issues with production settings.
- Production Docker image: built successfully; migrations completed and the
  Gunicorn login endpoint returned HTTP 200 from the running container.
- Google Sheet sync: row counts and normalized transaction rows matched.
- Dashboard: fiscal-year selection and all four FY2025-26 metrics verified.
- Transactions: 27 FY2025-26 rows and transaction IDs verified.
- Invoice import: two real PDFs uploaded together and retained as separate
  review drafts; the review form renders parsed date, FY, category, vendor,
  description, PO, invoice, currency, amount, and team.
- Deployed parser: `INS6000_9216658.PDF` produced PeopleSoft Inventory,
  invoice `INS6000_9216658`, USD 151.95, date 2026-03-26, description, fiscal
  year, category, and team controls through the authenticated staging UI.
- Reversible category budget: FY2026-27 Consumables was changed from $109,500
  to $10,000, read back from Google Sheets, mirrored as `Matched`, and restored
  to $109,500 in both Sheet and web mirror.
- Reversible transaction lifecycle: a temporary USD 0.01 row was written to
  FY2025-26, read back, cancelled, verified to release the budget, deleted, and
  restored to the exact original 27-row set and totals.
- Responsive UI: desktop 1440px and small-screen 500px viewports had no
  horizontal overflow; metric values remained inside their panels.
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
- Local startup: migrations are separate from web startup; both Sheet syncs and
  parity comparisons completed successfully before Gunicorn/Django serving.
- Summary formulas: all eight category/TOTAL formula ranges were repaired and
  read back successfully in both FY2025-26 and FY2026-27 without changing their
  category budget inputs.

## Rollback

Set `ENABLE_SHEET_WRITES=false` to disable new registrations immediately. The
existing Streamlit application remains available. The reversible verification
row has been removed and no dummy transaction remains.

## Promotion gate

Do not replace Streamlit until Cloud SQL PostgreSQL and the private GCS bucket
are provisioned, migrations/sync run as release jobs, authenticated role smoke
tests pass in Cloud Run, and daily Streamlit-vs-Web totals match for one week.
