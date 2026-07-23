# Integrated web validation

Last verified: 2026-07-23 (Asia/Dubai)

## Scope

- Django/Cloud Run is the production application.
- No user-facing route, parser, runtime configuration, container layer, or
  operational workflow depends on the legacy application.
- The Web application includes the full Budget workflow: manual transactions,
  edit/cancel, receipt attachment, reports, PDF and ERB import, Settings,
  multi-team roles, audit, fiscal-year creation, notification settings, and
  durable Cloud SQL/GCS storage.
- The same Web service also provides the private portal, Project Tracker, and
  Notebooks/Protocols application.
- Uploaded invoices remain temporary review drafts until a Team Lead, Budget
  Manager, or PI confirms the extracted fields.

## Staging

- Service: `kamei-lab-budget-web-staging`
- Revision: `kamei-lab-budget-web-staging-00038-pun`
- Region: `me-central1`
- URL: <https://kamei-lab-budget-web-staging-7id3bdyliq-ww.a.run.app>
- Access: Google Cloud IAP plus the application lab-member allowlist
- Scaling: zero idle instances, maximum one instance

The production revision uses Cloud SQL PostgreSQL, a private invoice bucket,
and a private knowledge bucket. It scales to zero when idle and keeps a maximum
of one Cloud Run instance.

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

The verification command compares the Google Sheet source with the PostgreSQL
web mirror, including fiscal-year routing, currency conversion, team
allocations, and `Cancelled` exclusion.

## Candidate verification completed

- Django test suite: 125 passed.
- Independent QA review: no remaining P0, P1, or P2 findings.
- Main authenticated production routes returned normal pages for Budget
  overview, transactions, imports, reports, Settings, portal, Project Tracker,
  and Notebooks/Protocols.
- Google Sheet-to-Web parity remained exact after the release for FY2025-26
  and FY2026-27.
- The completed parity work adds team/category/recent/pending dashboard views,
  filtered CSV, multi-currency previews, member receipt attachment, safer
  invoice and ERB identity matching, partial batch recovery, per-team roles,
  fiscal-year creator status, notification settings, lifecycle/status controls
  for knowledge records, broader Office/CSV extraction, and tracker blocker,
  help, data-link, and Gantt controls.
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
- The final reversible budget probe reached the Google Sheets per-user read
  limit during immediate post-write verification and therefore reported a
  failed verification. Both attempts restored FY2025-26 Consumables to
  $109,500.00. A subsequent complete parity read confirmed 27 rows, $169,500.00
  total budget, $10,698.03 allocated, and $158,801.97 available, with no dummy
  data remaining.
- Portal routing correction: the previous production Portal was observed
  rendering three registry-provided legacy URLs. Revision `00038-pun` ignores
  registry `app_url` values for navigation and always resolves Budget,
  Project Tracker, and Notebooks/Protocols to internal Django routes.
- Candidate and production click checks: all three Portal cards stayed on the
  same Cloud Run host and opened `/`, `/tracker/`, and `/knowledge/`.
- Runtime independence: the deployment image copies only `web_app/`; invoice
  parsing and Google configuration no longer read files from the legacy app.
- Operational cleanup: the keep-awake workflow and old operational guide were
  removed.

## Rollback

Set `ENABLE_SHEET_WRITES=false` to disable new registrations immediately.
Traffic can be returned to Django revision `00036-kuw`. No dummy transaction or
budget value remains.

## Promotion status

Revision `00038-pun` receives 100% production traffic. Continue daily
Google Sheet-to-Web parity checks. Run production write probes only when Google
Sheets quota is healthy, and always verify restoration before closing a
maintenance task.
