---
name: update-exchange-rate
description: Update the AED/USD exchange rate used for all budget calculations, and show the impact on existing USD transactions
type: flexible
---

# Update Exchange Rate Skill

Update the exchange rate in the Config tab and recalculate AED equivalents.

## Steps

1. **Fetch the current rate**:
   ```
   POST {webAppUrl}
   {"action": "getConfig", "key": "AED/USD Exchange Rate"}
   ```
   Display: `Current rate: 1 USD = 3.6725 AED (set on 2025-09-01)`

2. **Get the new rate** from the user — or note that the AED is officially pegged at 3.6725:
   ```
   The UAE Dirham is pegged to USD at 3.6725.
   Enter a new rate only if your institution uses a different rate
   (e.g. for budgeting purposes or a specific grant's required rate).

   New rate (or press Enter to keep 3.6725): ______
   ```

3. **Show impact** — fetch all USD transactions and recalculate:
   ```
   Impact of changing rate from 3.6725 → 3.6800:

   Category    Current AED equiv    New AED equiv    Difference
   Equipment   12,435.00            12,460.50        +25.50
   Travel       5,508.75             5,520.00        +11.25
   ─────────────────────────────────────────────────────────
   TOTAL        17,943.75           17,980.50        +36.75

   Confirm update? [y/n]
   ```

4. **On confirmation**, update the Config tab:
   ```
   POST {webAppUrl}
   {"action": "setConfig", "key": "AED/USD Exchange Rate", "value": 3.68}
   ```
   Also update `Rate Last Updated` to today's date.

5. **Note**: existing `Amount (AED equiv)` values in the Transactions sheet are static snapshots at the rate when they were entered. Only new transactions will use the new rate. To recalculate all historical AED equiv values, the user must do so manually in the spreadsheet.

## Notes

- The official USD/AED peg is 3.6725 — only change this if required by a specific grant or institutional policy
- Rate changes affect the Summary tab formulas (which reference `Config!B2`) immediately
- Historical transaction rows store the AED equiv at time of entry and are not retroactively updated
