# Time & Attendance payroll export

Verified: 2026-08-20

## Decision

The Tribunal exports a **generic payroll time CSV for mapping and reconciliation**. It does not claim direct compatibility with QuickBooks, Gusto, ADP, or another payroll product because no universal payroll CSV schema exists and this repository contains no configured payroll vendor.

The export contains raw completed time entries with stable entry and employee IDs, names/emails for matching, workspace-local punch timestamps, decimal gross hours, paused hours, and `total_hours` calculated as gross minus paused. It also includes source and notes. Open and voided entries are excluded. The Tribunal does not decide whether paused time is legally paid or unpaid, or classify regular, overtime, double-time, paid leave, earnings codes, or pay rates; the payroll administrator must review paused intervals and classify all values in the payroll system under the employer's policy and applicable law.

## Why the export is generic

- QuickBooks Time publishes different, case-sensitive Manual Time and Punch Time templates and limits imports to 750 rows. QuickBooks Online Payroll receives time through the QuickBooks Time workflow rather than a universal payroll CSV.
- Gusto Smart Import maps a customer's spreadsheet layout and requires human review. It does not define a universal source schema.
- ADP Workforce Now's official pay-data examples use tenant-specific API identifiers, payroll groups, pay dates, and earning codes rather than a generic CSV contract.
- RFC 4180 defines interoperable CSV syntax, not payroll meanings or columns.

## Authoritative references

- Intuit, [Export or import time data in QuickBooks Time](https://quickbooks.intuit.com/learn-support/en-us/help-article/time-tracking/export-import-time-data-quickbooks-time/L1f77o0jJ_US_en_US)
- Intuit, [Set up time tracking in QuickBooks Online Payroll](https://quickbooks.intuit.com/learn-support/en-us/help-article/time-tracking/set-time-tracking-quickbooks-online-payroll/L7Jz6Ai2U_US_en_US)
- Gusto, [Run payroll with Smart Import](https://support.gusto.com/article/999914471000000/run-payroll-with-smart-import)
- Gusto Embedded Payroll, [Complete a regular payroll](https://docs.gusto.com/embedded-payroll/docs/complete-a-regular-payroll)
- ADP, [Workforce Now pay-data input samples](https://github.com/adpllc/marketplace-sample-payloads/tree/master/wfn/payroll/pay-data-input/Next-Gen)
- IETF, [RFC 4180](https://www.rfc-editor.org/rfc/rfc4180.html)

## Adding a direct adapter later

A vendor adapter must be validated against the customer's exact payroll product, tenant configuration, employee identifiers, earning codes, import template, and duplicate-import behavior. Until then, UI and documentation must call the file **Generic payroll CSV**, not provider-compatible.
