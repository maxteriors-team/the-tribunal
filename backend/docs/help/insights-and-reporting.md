---
title: Scorecard, Reports, and Sales Performance
slug: insights-reporting
tags:
  - scorecard
  - reports
  - sales performance
  - campaign reports
  - analytics
---

# Scorecard, Reports, and Sales Performance

## Scorecards

Route: `/scorecard`. Sidebar label: **Scorecard**. This surface requires `reports:view` and is normally available to workspace owners and admins.

Use **AI receptionist** to review how the receptionist captured, recovered, and booked demand for the selected date range. Use **Technicians** to review assigned jobs, completed job-time records, job time, attendance worked time, and paused time for each field-service technician.

Technician totals are activity context, not an employee rating. The page does not rank workers or infer work quality, productivity, pay, or customer satisfaction. Job assignments, job-costing timers, and attendance records have different operational meanings; investigate the source records before using a total in coaching, discipline, scheduling, or compensation decisions.

## Reports

Route: `/reports`. Sidebar label: **Reports**.

Use Reports for the available workspace-level operational and campaign reporting. Campaign intelligence reports appear after eligible campaigns complete and can also be generated from a completed campaign where that action is available. Empty campaign-report state means no report is available yet, not that a campaign had zero activity.

## Sales Performance

Route: `/reports/sales`. Sidebar label: **Sales Performance**.

1. Open **Sales Performance**.
2. Choose the date range.
3. Review approved revenue, quote volume, close rate, attach rate, average job value, and attribution warnings.
4. Use the closer and lead-source breakdowns to locate the contributing records.
5. Compare each change with the equal-length period immediately before the selected range.

Reports require the `reports:view` capability and are normally available to workspace admins. If the page says **No access to reports**, ask a workspace admin rather than retrying the request.
