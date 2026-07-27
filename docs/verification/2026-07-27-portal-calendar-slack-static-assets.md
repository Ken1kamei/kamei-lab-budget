# Portal Calendar and Slack static asset repair

Date: 2026-07-27

## Change

- Root cause: deploying from `web_app` included a stale generated `staticfiles`
  directory, so production served `app.49edc92340d5.css` without the Portal
  Calendar and Slack layout rules.
- `web_app/.gcloudignore` now excludes generated static files from source
  uploads.
- `web_app/start.sh` runs `collectstatic --noinput --clear` before Gunicorn so
  each Cloud Run container serves assets generated from the current source.
- An architecture test protects the ignore rule, startup order, and required
  Calendar/Slack selectors.

## Deployment

- Previous production revision: `kamei-lab-budget-web-staging-00050-big`
- Rejected candidate: `kamei-lab-budget-web-staging-00052-yic`
  - It received 0% production traffic.
  - It exposed the missing `collectstatic` step with a manifest error and was
    not promoted.
- Verified candidate and production revision:
  `kamei-lab-budget-web-staging-00053-koz`
- Production URL:
  `https://kamei-lab-budget-web-staging-7id3bdyliq-ww.a.run.app`
- Final traffic: `00053-koz=100%`
- Rollback target: `00050-big=100%`

## Verification

- Upload manifest excluded `staticfiles` and included the current source CSS.
- Production-style local collection generated `app.24c35fbb91ca.css` with
  `.portal-integrations`, `.week-calendar`, and `.slack-messages`.
- Automated suite: `146 passed in 3.45s`.
- Django system check: no issues.
- Candidate and production were authenticated through IAP as
  `kk4801@nyu.edu`.
- Production served `app.24c35fbb91ca.css`.
- Calendar rendered as a seven-column grid with the current real events.
- Calendar and Slack panels rendered in the expected two-column layout.
- Slack rendered the connected `KameiLab_NYUAD` account, conversation picker,
  a 300px message viewport, and seven messages.
- Active Members remained at eight and all three app cards remained present.
- Narrow viewport verification showed no page-level horizontal overflow; the
  Calendar alone retained its intended internal horizontal scroll.
- Cloud Run ERROR log query for `00053-koz` returned no entries before or after
  promotion.
- No production data was changed for this visual repair.

## Rollback

```bash
gcloud run services update-traffic kamei-lab-budget-web-staging \
  --project kamei-lab-budget \
  --region me-central1 \
  --to-revisions kamei-lab-budget-web-staging-00050-big=100
```
