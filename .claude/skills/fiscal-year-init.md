---
name: fiscal-year-init
description: Initialize a new academic fiscal year — set up the Summary sheet, enter budget allocations, and configure triggers for the new year (Sep 1 – Aug 31)
type: flexible
---

# Fiscal Year Init Skill

Guide the user through initializing a new fiscal year in the budget system.

## Steps

1. **Determine the new fiscal year** — ask if not provided:
   ```
   Which fiscal year are you initializing?
   (e.g. FY2026-27 covers Sep 1, 2026 – Aug 31, 2027)
   ```

2. **Collect budget allocations** — ask for each category:
   ```
   Enter budget allocations for FY2026-27.
   You can enter amounts in AED, USD, or both.
   Press Enter to skip a category (sets it to 0).

   Equipment  — AED: ______  USD: ______
   Personnel  — AED: ______  USD: ______
   Travel     — AED: ______  USD: ______
   Other      — AED: ______  USD: ______
   ```

3. **Confirm the totals**:
   ```
   Summary for FY2026-27:
   ──────────────────────────────────────────────
   Category    AED Budget    USD Budget    AED Equiv
   Equipment   500,000       0             500,000
   Personnel   300,000       50,000        483,625
   Travel      50,000        10,000        86,725
   Other       20,000        0             20,000
   ──────────────────────────────────────────────
   TOTAL                                 1,090,350
   Exchange rate: 1 USD = 3.6725 AED

   Confirm? [y/n]
   ```

4. **Call the GAS API**:
   ```
   POST {webAppUrl}
   {
     "action": "initializeFiscalYear",
     "fiscalYear": "FY2026-27",
     "allocations": {
       "Equipment": {"aed": 500000, "usd": 0},
       "Personnel":  {"aed": 300000, "usd": 50000},
       "Travel":     {"aed": 50000,  "usd": 10000},
       "Other":      {"aed": 20000,  "usd": 0}
     }
   }
   ```

5. **Set up triggers** — ask if the user wants to (re)configure auto-import triggers:
   ```
   POST {webAppUrl}
   {"action": "setupTriggers"}
   ```

6. **Final checklist**:
   ```
   ✓ Summary sheet initialized for FY2026-27
   ✓ Budget allocations saved
   ✓ Gmail auto-import triggers set
   □ Remember to update the exchange rate if needed (/update-exchange-rate)
   □ Share the new spreadsheet with lab members via Google Drive
   □ Archive last year's spreadsheet in Drive
   ```

## Notes

- Fiscal year naming format: `FY{start_year}-{end_year_2digit}`, e.g., `FY2026-27`
- Running this does NOT delete existing transactions — it only resets the Summary tab allocations
- The current fiscal year is tracked in the `Config` tab of the spreadsheet
