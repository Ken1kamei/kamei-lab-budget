# Portal member removal repair

Date: 2026-07-27

## Change

- Root cause: the removal path reapplied the new-member email allowlist, so
  legacy test accounts outside `@nyu.edu` could not be deactivated.
- Removal now normalizes an existing account email without applying the
  new-registration restriction. New registrations remain restricted to NYU
  accounts and configured shared-account exceptions.
- Inactive members and inactive app roles are hidden from the active Registry
  tables while their Google Sheet rows remain available for audit history.
- PI and self-removal protections remain in place.

## Deployment

- Previous production revision: `kamei-lab-budget-web-staging-00053-koz`
- Rejected intermediate candidate: `kamei-lab-budget-web-staging-00055-jil`
  - It fixed revocation but still displayed inactive rows in Active members.
- Verified candidate: `kamei-lab-budget-web-staging-00056-cas`
- Candidate tag:
  `https://member-remove-fix---kamei-lab-budget-web-staging-7id3bdyliq-ww.a.run.app`
- Production URL:
  `https://kamei-lab-budget-web-staging-7id3bdyliq-ww.a.run.app`
- Rollback target: `kamei-lab-budget-web-staging-00053-koz=100%`

## Verification

- Automated suite: `147 passed in 1.77s`.
- Candidate authenticated through IAP as `kk4801@nyu.edu`.
- `Research Member <member@example.edu>` and `test1 <test@test.com>` were
  removed through the candidate Registry UI as requested.
- The UI reported successful Google Sheet verification for both operations.
- Direct Google Sheet read-back confirmed Members `M003` and `M005`, their four
  app roles, and their three team memberships are `FALSE` with end date
  `2026-07-27`.
- Active members decreased from eight to six; both removed users and their app
  roles disappeared from the active Registry tables.
- The candidate Portal retained all three app cards, the seven-column Google
  Calendar, connected `KameiLab_NYUAD` Slack content with seven messages, and no
  page-level horizontal overflow.
- Cloud Run ERROR logs for the verified candidate returned no entries.

## Rollback

```bash
gcloud run services update-traffic kamei-lab-budget-web-staging \
  --project kamei-lab-budget \
  --region me-central1 \
  --to-revisions kamei-lab-budget-web-staging-00053-koz=100
```
