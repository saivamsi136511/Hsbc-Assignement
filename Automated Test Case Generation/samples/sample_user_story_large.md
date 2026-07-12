# User Story: International Money Transfer

## Epic
As a business banking customer, I need to transfer money internationally
to suppliers and partners in multiple currencies, so that I can manage
cross-border payments efficiently from within the online banking portal.

## User Personas
- **Primary**: Finance Manager at a mid-size enterprise using HSBC business banking
- **Secondary**: Treasury Analyst who reviews and approves large transfers

---

## Acceptance Criteria

### Section A: Transfer Initiation

1. The user shall be able to initiate a transfer by specifying: source account
   (from their linked accounts), destination country, destination bank SWIFT/BIC
   code (8 or 11 characters), destination IBAN or account number, amount,
   source currency, target currency, transfer date (today or up to 90 calendar
   days in the future), and an optional payment reference (max 140 characters).

2. The system shall validate the SWIFT/BIC code format (exactly 8 or 11
   alphanumeric characters, first 4 alpha, next 2 alpha country code, next 2
   alpha-numeric location code, optional 3 alpha-numeric branch code) and
   return ``ValidationError: Invalid SWIFT/BIC format`` for non-compliant codes.

3. The system shall validate IBAN format per ISO 13616 (2-letter country code,
   2 check digits, up to 30 alphanumeric characters, total 15–34 characters)
   and return ``ValidationError: Invalid IBAN`` for non-compliant IBANs.

4. The transfer amount shall be a positive decimal number with at most 2
   decimal places, between 0.01 and 10,000,000.00 (inclusive) in the source
   currency. Amounts outside this range shall be rejected with
   ``ValidationError: Amount out of allowed range``.

5. The payment reference field shall accept 0–140 characters.  A reference of
   exactly 0 characters shall be treated as "no reference" (valid).  References
   longer than 140 characters shall be rejected with
   ``ValidationError: Reference exceeds 140 characters``.

6. The transfer date must be today or a future date within 90 calendar days.
   Past dates shall return ``ValidationError: Transfer date must not be in the past``.
   Dates more than 90 days in the future shall return
   ``ValidationError: Transfer date exceeds scheduling horizon (90 days)``.

### Section B: FX Rate and Fee Calculation

7. Before confirming, the system shall display the live FX exchange rate
   retrieved from the rates service (with a timestamp). If the rate service
   is unavailable, the system shall display a cached rate (max 1 hour old)
   with a ``[Rate indicative – live rate unavailable]`` banner, and still
   allow the transfer to proceed.

8. The system shall display the transfer fee schedule. For amounts up to
   £1,000.00 the fee is £5.00. For £1,000.01 to £10,000.00 the fee is
   £12.50. For amounts above £10,000.00 the fee is £25.00. Boundary values
   (£1,000.00, £1,000.01, £10,000.00, £10,000.01) must be tested.

9. The FX rate shall be locked for 30 seconds once the user requests a quote.
   If 30 seconds elapse before confirmation, the system shall refresh the rate,
   notify the user, and require re-confirmation with the new rate.

### Section C: Approval Workflow

10. Transfers below £5,000.00 shall be executed immediately upon the initiating
    user's confirmation without a second approver.

11. Transfers of £5,000.00 and above shall be placed in "Pending Approval"
    status and require confirmation by a second authorised user (not the same
    as the initiator). The approver shall receive an in-app notification and
    email alert.

12. Transfers pending approval for more than 72 hours without action shall
    expire automatically with status ``Expired`` and the initiator shall
    receive an expiry notification.

### Section D: Compliance and Limits

13. The system shall enforce a daily outbound transfer limit per account.
    Transfers that would cause the total transfers for that calendar day to
    exceed the account's configured daily limit shall be rejected with
    ``LimitExceededError: Daily transfer limit exceeded``.

14. Transfers to OFAC-sanctioned countries (maintained in a reference list)
    shall be blocked and return ``ComplianceError: Transfer to sanctioned
    jurisdiction is prohibited`` without revealing the exact block reason
    beyond the generic compliance message.

15. If the AML (Anti-Money Laundering) risk score for the beneficiary exceeds
    the high-risk threshold, the transfer shall be routed to a manual compliance
    review queue and the status set to ``Pending Compliance Review``.

### Section E: Confirmation and Receipts

16. Upon successful submission (immediate or pending), the system shall return
    a unique 12-character alphanumeric transaction reference (e.g. ``TXN-A1B2C3D4``),
    the submitted transfer details, the applied FX rate, the calculated fee,
    and the estimated settlement date (T+1 for EU SEPA, T+2 for SWIFT).

17. The system shall send an email confirmation to the account holder's
    registered email address within 2 minutes of a successful submission.
    The email shall contain the transaction reference, amount, currency pair,
    fee, and estimated settlement date.
