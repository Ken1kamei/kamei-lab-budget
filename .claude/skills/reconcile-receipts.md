---
name: reconcile-receipts
description: Find equipment orders without delivery receipt confirmation, show how many days they have been outstanding, and draft reminder emails
type: flexible
---

# Reconcile Receipts Skill

Identify unconfirmed equipment orders and help the user follow up.

## Steps

1. **Fetch unconfirmed orders** from the GAS API:
   ```
   POST {webAppUrl}
   {"action": "getUnconfirmedOrders"}
   ```

2. **Display the results**:
   ```
   Unconfirmed Equipment Orders
   ════════════════════════════
   TXN-20251001-0003 | Fisher Scientific   | AED 3,450  | Ordered 2025-10-01 | 21 days ⚠️
   TXN-20251005-0007 | Sigma-Aldrich       | AED 1,200  | Ordered 2025-10-05 | 17 days
   TXN-20251015-0012 | VWR International   | AED 870    | Ordered 2025-10-15 |  7 days ✓
   ```
   Flag orders > 14 days as ⚠️, > 30 days as 🚨.

3. **Offer actions** for each order:
   - `[M] Mark as received` — updates Status to "Delivered" and Receipt Confirmed to TRUE
   - `[E] Email vendor` — drafts a follow-up email
   - `[C] Cancel order` — updates Status to "Cancelled"
   - `[S] Skip`

4. **For mark as received**, call:
   ```
   POST {webAppUrl}
   {"action": "addReceipt", "data": {
     "transactionId": "TXN-...",
     "receiptDate": "YYYY-MM-DD",
     "condition": "OK",
     "notes": "Confirmed via Claude Code reconciliation"
   }}
   ```

5. **For email draft**, compose a plain-text follow-up:
   ```
   Subject: Order Follow-up — [Order/Invoice #]

   Dear [Vendor],

   I am writing to follow up on an order placed on [date].
   Could you please provide an update on the delivery status?

   Order details: [description], [amount]

   Thank you,
   [PI name]
   Kamei Reverse Bioengineering Lab, NYUAD
   ```
   Show the draft and ask if the user wants to copy it or send via Gmail.

6. **Summary**: after processing, show a count of items resolved vs. still outstanding.
