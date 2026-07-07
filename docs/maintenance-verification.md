# Maintenance and Verification Protocol

This protocol applies to the Kamei Lab management apps, including Budget,
Portal, Notebooks/Protocols, and Project Tracker.

The completion standard is not "code was changed." The completion standard is
"the requested workflow was verified end to end, with evidence, and any dummy
data was restored."

## When to Use Multi-Agent Review

Use a lightweight single-agent workflow for small visual or text-only changes.

Use a multi-agent-style workflow for changes involving any of the following:

- Google Sheets reads or writes
- Streamlit Cloud deployment behavior
- user roles, allowlists, or authentication
- invoice/PDF import
- fiscal-year data routing
- cross-app synchronization
- any operation that touches production data

The coordinator remains responsible for the final answer and must not delegate
the final judgment. Suggested roles:

- Coordinator: scope, risk, final decision, and user report
- Implementation: code changes
- QA: real workflow verification and dummy-data round trip
- Regression: existing test suite and adjacent feature checks
- Security/Access: roles, allowlists, secrets, and sharing checks

## Required Verification Pattern

Before implementation, define the smallest real workflow that proves the fix.

For production-data paths, use a reversible round trip:

1. Record the current value.
2. Write a clearly bounded dummy value.
3. Read the value back from the source of truth.
4. Verify the app calculation or UI path that depends on it.
5. Restore the original value.
6. Read back again to confirm restoration.

Do not report completion until restoration is confirmed.

## Budget App Minimum Checks

For Settings, fiscal year, or budget allocation changes:

- Select the target fiscal year.
- Save a dummy category allocation, such as Consumables = 10000 USD.
- Confirm the relevant Google Sheet row changed.
- Confirm Dashboard totals reflect the dummy value.
- Restore the original category allocation.
- Confirm the Google Sheet and Dashboard totals returned to the original state.

For invoice import changes:

- Upload at least one representative PDF.
- Confirm parsed vendor, PO/invoice number, currency, amount, category, and team.
- Import the transaction.
- Confirm it appears in Google Sheets.
- Confirm it appears in Transactions/Dashboard.
- Cancel or delete the dummy transaction if it was only for testing.

For permission changes:

- Verify PI access.
- Verify Budget Manager access.
- Verify Team Lead access.
- Verify Member access.
- Verify unknown or unregistered user behavior.

## Portal, Notebooks, and Project Tracker Minimum Checks

- Verify login or allowlist access for a known registered user.
- Verify the main page renders after login.
- Verify one create/edit/read workflow if the change touches data.
- Confirm the expected Google Sheet or registry row is written.
- Restore dummy data when applicable.

## Completion Report Format

Every maintenance completion report should include:

- what changed
- exact verification steps performed
- production or dummy data touched
- restoration status
- automated test results
- commit hash
- push/deployment status
- any remaining caveats

## Non-Negotiable Rules

- Do not claim a Google Sheet fix works without reading the Sheet back.
- Do not claim a Dashboard fix works without checking the calculation path or UI.
- Do not leave dummy data in production unless the user explicitly asks for it.
- Do not treat a passing unit test as a substitute for an end-to-end workflow
  check when the bug was observed in the deployed app.
