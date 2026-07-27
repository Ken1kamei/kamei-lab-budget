# Portal Calendar and Slack verification

Date: 2026-07-27

## Change

- Application commit: `9861f17` (`feat: add portal calendar and personal Slack`)
- Previous production revision: `kamei-lab-budget-web-staging-00044-yik`
- Verified candidate revision: `kamei-lab-budget-web-staging-00048-kij`
- Production URL: `https://kamei-lab-budget-web-staging-7id3bdyliq-ww.a.run.app`
- Final traffic: `00048-kij=100%`
- Rollback target: `00044-yik=100%`

## Slack configuration

The combined Slack manifest create/install flow returned a generic Slack UI error. The app was instead created as a blank Slack app, configured through its manifest editor, and installed into `KameiLab_NYUAD`.

- Slack app ID: `A0BL28SM481`
- Workspace ID: `T044ULKBG91`
- OAuth redirect: `https://kamei-lab-budget-web-staging-7id3bdyliq-ww.a.run.app/portal/slack/callback/`
- Secret Manager references:
  - `kamei-portal-slack-client-id`
  - `kamei-portal-slack-client-secret`
  - `kamei-portal-slack-token-key`
- Secret access is limited to `budget-app@kamei-lab-budget.iam.gserviceaccount.com`.
- No credential or Slack token is recorded in this file.

## Verification

- Local test suite: `139 passed in 3.65s`.
- Candidate and production portal authenticated through IAP as `kk4801@nyu.edu`.
- Google Calendar rendered real events for the current Dubai-time week.
- Slack completed OAuth, showed the one-time identity confirmation, and persisted the confirmed personal connection.
- Production rendered the connected Slack identity, 100 accessible conversations, and 7 messages for the selected conversation.
- All three app cards linked to internal non-Streamlit routes.
- Desktop and narrow viewport checks showed no horizontal overflow.
- Cloud Run error log query for `00048-kij` returned no entries before or after promotion.
- One encrypted `SlackConnection` record for `kk4801@nyu.edu` is intentional production data.

## Rollback

```bash
gcloud run services update-traffic kamei-lab-budget-web-staging \
  --project kamei-lab-budget \
  --region me-central1 \
  --to-revisions kamei-lab-budget-web-staging-00044-yik=100
```
