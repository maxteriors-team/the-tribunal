# Time & Attendance

Open **Time & Attendance** at `/time` to record internal staff work intervals independently from job-costing timers. Job timers remain operational cost records and are not included in payroll exports, which prevents the same hours from being counted twice.

## Staff clock

1. Open **Time & Attendance**.
2. Select **Clock in** when work begins.
3. Select **Pause** when worked time should stop, then **Resume** before returning to work.
4. Select **Clock out** when the shift ends. Clocking out while paused closes the active pause too.
5. Review **My hours** for worked and paused time in the selected date range.

The clock stores server timestamps, pause/resume intervals, an optional note, and the acting user. It does not collect location, screen contents, or activity. Each user can read only their own attendance records. A pause is not automatically a lawful unpaid-break classification: employer policy and payroll review must decide whether each paused interval is compensable.

## Admin review

Workspace owners and admins can open **Team hours** to:

- review every recorded interval and open shift;
- add a missed completed interval with a required reason;
- correct a completed interval with a required reason;
- void an invalid interval without deleting its history; and
- export completed intervals for a selected date range.

Every create, correction, clock, pause, resume, and void action is written to an append-only attendance event history. Overlapping non-void shifts and overlapping pauses are rejected by PostgreSQL.

## Payroll CSV

**Export payroll CSV** downloads a generic UTF-8 CSV containing raw completed intervals. Open and voided intervals are excluded. Each row includes gross hours, paused hours, and `total_hours` (gross minus paused). The export records its creator, date range, row count, entry IDs, net total seconds, and SHA-256 checksum; the CSV itself is not retained by The Tribunal.

The file does not decide whether paused time is paid or unpaid, or classify regular hours, overtime, double-time, leave, pay rates, or earning codes. Review paused intervals and map all payroll values before running payroll. The export is not advertised as directly compatible with a payroll vendor until that vendor's exact tenant template has been tested.

## Corrections and retention

Attendance rows have no hard-delete API. A void keeps the original record and audit trail while excluding it from totals and exports. Pause intervals are immutable in this first version; if one is wrong, an admin must void the shift and add a corrected completed interval with a reason. Company policy and employment counsel must set the retention period, overtime/workweek rules, paid and unpaid break rules, rounding policy, employee correction process, and final payroll approval procedure.
