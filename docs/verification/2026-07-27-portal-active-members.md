# Portal Active Members verification

Date: 2026-07-27

## Change

- Application commit: `a72af08` (`feat: manage active members from portal`)
- Previous production revision: `kamei-lab-budget-web-staging-00048-kij`
- Verified candidate revision: `kamei-lab-budget-web-staging-00050-big`
- Production URL: `https://kamei-lab-budget-web-staging-7id3bdyliq-ww.a.run.app`
- Final traffic: `00050-big=100%`
- Rollback target: `00048-kij=100%`

## Access model

- PI and admin users can add members from `Portal > Manage members`.
- Member email addresses must use `@nyu.edu`, except for explicitly configured shared accounts.
- `nyuadkameilab@gmail.com` is the configured shared-account exception and was retained as intentional production data.
- Removing access deactivates the member, app roles, team memberships, and Portal allowlist entry while preserving audit history.
- PI accounts and the signed-in user's own account cannot be removed from this screen.
- IAP permits `domain:nyu.edu` and `user:nyuadkameilab@gmail.com`; the application still requires an active member record before granting Portal access.

## Verification

- Local test suite: `145 passed in 3.47s`.
- Django system check: no issues.
- Candidate and production Portal authenticated through IAP as `kk4801@nyu.edu`.
- Reversible Cloud Run execution `kamei-portal-member-verify-2t2ck` completed successfully.
- The execution added a temporary NYU member, read it back from Google Sheets and the app allowlist, removed its access, restored `Members`, `Member_Teams`, `App_Roles`, and `Audit_Log`, and confirmed that no temporary record remained.
- The shared account was saved through the candidate Portal UI and the UI reported `Member saved and verified in Google Sheets.`
- Production Portal showed 8 active members, including `nyuadkameilab@gmail.com`.
- Production Registry showed the add form and 6 removable accounts; the PI account did not expose a remove action.
- Portal's `Manage members` link opened the production Registry.
- Calendar, Slack, and all three internal app links remained available.
- Desktop and narrow viewport checks showed no horizontal overflow.
- Cloud Run error log queries for `00050-big` returned no entries before or after promotion.
- The temporary verification Job was deleted after completion.

## Rollback

```bash
gcloud run services update-traffic kamei-lab-budget-web-staging \
  --project kamei-lab-budget \
  --region me-central1 \
  --to-revisions kamei-lab-budget-web-staging-00048-kij=100
```

If the IAP expansion must also be reverted, remove the `domain:nyu.edu` and
`user:nyuadkameilab@gmail.com` bindings from the Cloud Run IAP policy. Existing
individual NYU user bindings remain in the policy.
