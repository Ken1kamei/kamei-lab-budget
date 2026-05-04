---
name: generate-report
description: Generate a formatted budget report for the current or specified fiscal year, including narrative text suitable for grant reporting
type: flexible
---

# Generate Report Skill

Fetch full budget and transaction data, produce a Markdown-formatted report, and optionally export it to Google Docs.

## Steps

1. **Determine the period** — default to current fiscal year. Accept argument like `FY2025-26` or `Q1` (Oct–Dec).

2. **Fetch data** from the GAS API:
   ```
   POST {webAppUrl}
   {"action": "generateReport", "fiscalYear": "FY2025-26"}
   ```

3. **Render a Markdown report**:

   ```markdown
   # Kamei Lab Budget Report — FY2025-26
   Generated: 2025-11-01

   ## Summary

   | Category   | Budgeted (AED) | Spent (AED) | Remaining | % Used |
   |------------|----------------|-------------|-----------|--------|
   | Equipment  | XXX,XXX        | XXX,XXX     | XXX,XXX   | XX%    |
   | Personnel  | XXX,XXX        | XXX,XXX     | XXX,XXX   | XX%    |
   | Travel     | XXX,XXX        | XXX,XXX     | XXX,XXX   | XX%    |
   | Other      | XXX,XXX        | XXX,XXX     | XXX,XXX   | XX%    |
   | **TOTAL**  | **XXX,XXX**    | **XXX,XXX** | **XXX,XXX**| **XX%** |

   Exchange rate used: 1 USD = 3.6725 AED

   ## Budget Narrative

   [AI-generated paragraph from the narrative prompt]

   ## Monthly Spending

   | Month   | Equipment | Personnel | Travel | Other | Total |
   |---------|-----------|-----------|--------|-------|-------|
   | Sep 25  | ...       | ...       | ...    | ...   | ...   |
   ...

   ## Transactions (N total, N pending review)
   ```

4. **Output the report** as formatted Markdown in the terminal.

5. **Ask** whether to export to Google Docs — if yes, call:
   ```
   POST {webAppUrl}
   {"action": "exportReportToDoc", "fiscalYear": "FY2025-26"}
   ```
   Then open the returned Google Doc URL.

## Options

- `/generate-report FY2025-26` — specific fiscal year
- `/generate-report` — current fiscal year
