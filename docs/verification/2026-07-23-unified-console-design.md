# Unified Lab Operations Console Verification

Date: 2026-07-23

## Scope

- Unified the Portal, Budget Manager, Project Tracker, Notebooks / Protocols,
  and Lab Registry under one restrained dark console design.
- Kept the Portal free of an app sidebar and retained app-specific navigation
  inside each operational app.
- Added visible keyboard focus, a skip link, active navigation semantics,
  compact responsive controls, and screen-reader text for the monthly chart.
- Made Cloud static asset generation deterministic with
  `collectstatic --clear`.

## Design Review

The implementation incorporated three independent review perspectives:

- Beauty: quiet navy surfaces, thin borders, compact typography, and limited
  cyan, blue, magenta, and amber functional accents.
- Usability: clear app boundaries, working launch cards, visible active states,
  keyboard focus, and predictable information hierarchy.
- Performance: no remote fonts, no new JavaScript, no decorative image assets,
  and a 7.2 KB gzip CSS payload.

## Automated Verification

- `python manage.py check`: passed with zero issues.
- `pytest -q`: 131 tests passed.
- `git diff --check`: passed.
- Production static manifest: `budget/app.49edc92340d5.css`.

## Candidate Verification

Candidate revision: `kamei-lab-budget-web-staging-00044-yik`

- Deployed with zero production traffic.
- Signed in as the registered PI account.
- Checked 11 routes:
  - `/portal/`
  - `/`
  - `/tracker/`
  - `/knowledge/`
  - `/portal/admin/`
  - `/transactions/`
  - `/transactions/add/`
  - `/imports/`
  - `/reports/`
  - `/settings/`
  - `/knowledge/upload/`
- Every route rendered exactly one H1 and the current hashed CSS.
- Every route had document width equal to the 1440 px viewport.
- Portal Budget Manager launch-card click navigated to the Budget dashboard.
- Visual checks covered Portal, Budget, Project Tracker, and Knowledge.
- Cloud Run candidate errors at severity ERROR or higher: zero.

## Production Verification

Production revision: `kamei-lab-budget-web-staging-00044-yik`

- Traffic switched to 100%.
- Rechecked Portal, Budget, Project Tracker, Knowledge, and Lab Registry using
  the authenticated production URL.
- All five routes loaded the expected H1, current CSS hash, and registered
  account identity without horizontal overflow.
- Cloud Run production errors at severity ERROR or higher: zero.

## Data Safety

- No Google Sheet, Cloud SQL, invoice, project, notebook, protocol, or registry
  data was written or modified.
- No dummy data was required.
- Restoration status: not applicable.

## Remaining Caveat

- Responsive breakpoint rules and mobile control sizes were reviewed in CSS.
  The authenticated Cloud candidate was visually inspected at a 1440 px
  desktop viewport; no separate mobile browser screenshot was captured.
