# Portal cross-app action panel

Date: 2026-07-30

## Change

- Added a role-scoped Portal action panel for Overdue, Blocked, Pending
  approval, and Budget alert items.
- Tracker counts use the existing database mirror and the union of every team
  allowed by the member's Portal roles.
- Pending approval combines Tracker reviews and visible invoice drafts.
- Budget alerts identify visible team allocations, and PI-visible category
  allocations, at or above 80%; items at or above 100% are critical.
- No Google Sheets call or write is performed by the Portal request.

## Deployment

- Previous production revision and rollback target:
  `kamei-lab-budget-web-staging-00058-zug`
- Verified candidate and production revision:
  `kamei-lab-budget-web-staging-00062-loz`
- Production URL:
  `https://kamei-lab-budget-web-staging-678641983168.me-central1.run.app/portal`
- Final traffic: `00062-loz=100%`

## Verification

- Focused Portal suite: `33 passed`.
- Budget and Lab Apps suites: `150 passed`.
- Django system check: no issues.
- Cloud Build and Cloud Run candidate deployment succeeded.
- Authenticated candidate and production smoke tests as `kk4801@nyu.edu`
  displayed Overdue 2, Blocked 0, Pending approval 3, and Budget alert 0.
- Calendar, Slack, and all three app cards remained present.
- Desktop and narrow viewport checks showed no page-level horizontal overflow.
- Candidate revision produced no Cloud Run error logs before promotion.
- No member, Tracker, budget, invoice, calendar, Slack, or Sheet data was
  changed during verification.

## Rollback

```bash
gcloud run services update-traffic kamei-lab-budget-web-staging \
  --project kamei-lab-budget \
  --region me-central1 \
  --to-revisions kamei-lab-budget-web-staging-00058-zug=100
```
