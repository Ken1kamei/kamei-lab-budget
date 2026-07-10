# Kamei Lab Budget Fiscal-Year Creator

This standalone Apps Script is owned by the PI. It reads fiscal-year requests
that the Budget app writes to the master workbook's `Config` sheet, copies the
configured template into the PI's My Drive, then shares the new workbook with
the Budget app service account.

It deliberately has no public Web App endpoint, browser-user credential, or
static shared secret. The installable trigger executes as the PI and the
existing service-account sharing on the master sheet is sufficient for the app
to queue requests.

## Deployment

Run these commands while authenticated with the PI's Google account:

```bash
clasp create --type standalone --title "Kamei Lab Budget Fiscal Year Creator" --rootDir gas_fiscal_year_creator
clasp push
```

Open the created project and run `setupFiscalYearCreatorTrigger` once as the
PI. Approve the requested Drive and Sheets permissions. This installs a
one-minute trigger that creates, shares, migrates, or removes the workbook
requested by Settings. The default master spreadsheet ID and service-account
email are set for this lab; Script Properties can override
`MASTER_SPREADSHEET_ID` and `BUDGET_SERVICE_ACCOUNT_EMAIL` if either changes.

Each created workbook stores a creator-managed marker and its fiscal year in
its own `Config` tab. The trigger checks these markers before reusing or
deleting a workbook, and writes a heartbeat to the master `Config` tab every
minute so Settings can report whether the automation is running.
