---
name: budget-status
description: Show live budget status for the Kamei Lab — category breakdown, % used, recent transactions, and alerts for overspent categories
type: flexible
---

# Budget Status Skill

Fetch and display the current budget status from Google Sheets via the GAS web app API.

## Steps

1. **Get the web app URL** — read it from `gas/.clasp.json` or ask the user if not set. The URL format is `https://script.google.com/macros/s/{DEPLOYMENT_ID}/exec`.

2. **Fetch budget summary** — call the API:
   ```
   POST {webAppUrl}
   Content-Type: application/json
   {"action": "getBudgetSummary"}
   ```

3. **Fetch recent transactions** — call:
   ```
   POST {webAppUrl}
   {"action": "getTransactions", "filters": {}}
   ```

4. **Display a formatted summary**:

   ```
   ╔══════════════════════════════════════════════════════╗
   ║  Kamei Lab Budget — FY2025-26                        ║
   ╚══════════════════════════════════════════════════════╝
   Exchange rate: 1 USD = 3.6725 AED

   Category      Budgeted (AED)   Spent (AED)   Remaining    % Used
   ─────────────────────────────────────────────────────────────────
   Equipment     XXX,XXX          XXX,XXX       XXX,XXX      XX%  [████░░░░░░]
   Personnel     XXX,XXX          XXX,XXX       XXX,XXX      XX%  [██████░░░░]
   Travel        XXX,XXX          XXX,XXX       XXX,XXX      XX%  [███░░░░░░░]
   Other         XXX,XXX          XXX,XXX       XXX,XXX      XX%  [█░░░░░░░░░]
   ─────────────────────────────────────────────────────────────────
   TOTAL         XXX,XXX          XXX,XXX       XXX,XXX      XX%

   Recent transactions (last 5):
   • YYYY-MM-DD | Vendor | AED XXX | Category | Status
   ...

   ⚠️  Alerts: [list any category ≥ 80% used]
   📋  Pending review: N transaction(s)
   ```

5. **Highlight alerts**: mark categories ≥ 90% in red (⛔), 70–89% in yellow (⚠️), <70% in green (✓).

6. **Show days remaining** in the current fiscal year.

## Notes

- If the web app URL is unknown, check `gas/.clasp.json` or run `clasp deployments` in `gas/`.
- API calls require the user to be authenticated (nyu.edu Google account in a browser session). For CLI use, the GAS web app must be deployed with `Execute as: Me` so the token is PI's credentials.
- If the API returns an error, display the error message and suggest checking the deployment.
