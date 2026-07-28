# Portal multi-calendar integration

Date: 2026-07-28

## Change

- The Portal calendar now combines the main lab calendar with six shared lab
  calendars: BSC1, BSC2, BSC3, Confocal, Desiccator, and TC at CTP.
- Calendar sources are configured through `LAB_CALENDAR_SOURCES` without
  storing calendar IDs in source code.
- Events are merged chronologically and show their source with a stable color.
- A failure in one shared calendar no longer hides events from healthy
  calendars; the Portal displays a partial-data notice instead.

## Deployment

- Previous production revision: `kamei-lab-budget-web-staging-00056-cas`
- Verified candidate and production revision:
  `kamei-lab-budget-web-staging-00058-zug`
- Production URL:
  `https://kamei-lab-budget-web-staging-7id3bdyliq-ww.a.run.app`
- Final traffic: `00058-zug=100%`
- Rollback target: `00056-cas=100%`

## Verification

- Targeted integration suite: `10 passed`.
- Full automated suite: `149 passed in 4.67s`.
- Django system check: no issues.
- Migration check: no pending model changes.
- Cloud Build completed successfully for candidate `00058-zug`.
- The candidate and production Portal were authenticated through IAP as
  `kk4801@nyu.edu`.
- Production displayed all seven configured source labels.
- Production displayed four real events for the current week, including BSC1
  and BSC2 events, proving shared-calendar API access.
- The seven-day calendar, connected `KameiLab_NYUAD` Slack panel, and all three
  app cards remained present.
- Desktop and 390 x 844 viewport checks showed no page-level horizontal
  overflow.
- Cloud Run produced no application errors after promotion. The only warning
  requests were two harmless missing-favicon 404 responses.
- No calendar, Slack, member, budget, or other production data was changed.
- A local Docker build was unavailable because Docker Desktop was not running;
  the production-equivalent Google Cloud Build succeeded.

## Rollback

```bash
gcloud run services update-traffic kamei-lab-budget-web-staging \
  --project kamei-lab-budget \
  --region me-central1 \
  --to-revisions kamei-lab-budget-web-staging-00056-cas=100
```
