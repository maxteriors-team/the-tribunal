"""Management reporting and scorecard read tools for the CRM assistant.

Both tools are dispatchers: one ``get_report`` covering seven reports and one
``get_scorecard`` covering three teams, rather than ten near-identical tools.
Every tool schema is sent on *every* assistant request, so a tool per report
would tax all traffic to serve a rare question, and a long list of similar names
makes the model's choice worse rather than better.

Gated on ``reports:view`` -- the capability the ``/reporting`` and ``/scorecard``
routers require -- so workspace-wide money and staff-performance figures stay
with the admin tier.

Read-only: these tools compute, they never write a target or a scorecard.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any, get_args

from app.models.workspace import Workspace
from app.schemas.inventory import COGSGroupBy
from app.services.ai.crm_assistant._tool_context import (
    CRMToolContext,
    ToolArguments,
    ToolHandler,
    parse_date,
)
from app.services.ai.crm_assistant._tool_errors import invalid_argument, unavailable
from app.services.dashboard.scorecard_service import ScorecardService
from app.services.inventory.cogs_service import COGSService
from app.services.reporting.capacity_service import CapacityService
from app.services.reporting.reporting_service import ReportingService
from app.services.reporting.sales_performance_service import SalesPerformanceService

_REPORTS = (
    "ar_aging",
    "job_pnl",
    "cogs",
    "attribution_gap",
    "sales_performance",
    "backlog",
    "estimate_capacity",
)
# Office-rep activity is intentionally absent: ``ScorecardService`` exposes no
# ``get_office_rep_activity`` here, so offering the option would hand the model a
# tool call that cannot succeed. Restore it alongside that service method.
_TEAMS = ("reception", "technicians")
# Derived from the schema's Literal so a new breakdown cannot drift out of sync.
_COGS_GROUP_BY: tuple[str, ...] = get_args(COGSGroupBy)

# The scorecard routes refuse a window wider than a year; the same bound is
# applied here so the tool cannot ask for a scan the route would have rejected.
_MAX_SCORECARD_DAYS = 366


class ReportingAssistantTools:
    """Run management reports and activity scorecards."""

    def __init__(self, context: CRMToolContext) -> None:
        self.context = context

    def handlers(self) -> dict[str, ToolHandler]:
        return {
            "get_report": self.get_report,
            "get_scorecard": self.get_scorecard,
        }

    def _window(self, args: ToolArguments) -> tuple[date | None, date | None] | str:
        """Parse and sanity-check the shared date window, or return an error message."""
        date_from = parse_date(args.get("date_from"))
        date_to = parse_date(args.get("date_to"))
        if date_from is False or date_to is False:
            return "date_from and date_to must be dates in YYYY-MM-DD form."
        if date_from is not None and date_to is not None and date_from > date_to:
            return "date_from must not be after date_to."
        return date_from, date_to

    async def get_report(self, args: ToolArguments) -> dict[str, object]:
        report = args.get("report")
        if report not in _REPORTS:
            return invalid_argument(
                "report is not a known report.",
                f"Use one of: {', '.join(_REPORTS)}.",
            )

        window = self._window(args)
        if isinstance(window, str):
            return invalid_argument(window)
        date_from, date_to = window

        today = datetime.now(UTC).date()
        workspace_id = self.context.workspace_id
        data: Any

        if report == "ar_aging":
            data = await ReportingService(self.context.db).ar_aging(workspace_id, as_of=date_to)
        elif report == "job_pnl":
            # This one is the outlier: it windows on ``scheduled_start``, a
            # datetime, so the inclusive end date is widened to cover that day.
            data = await ReportingService(self.context.db).job_pnl_summary(
                workspace_id,
                date_from=(
                    datetime.combine(date_from, datetime.min.time(), tzinfo=UTC)
                    if date_from
                    else None
                ),
                date_to=(
                    datetime.combine(date_to, datetime.max.time(), tzinfo=UTC) if date_to else None
                ),
            )
        elif report == "cogs":
            group_by = args.get("group_by", "item")
            if group_by not in _COGS_GROUP_BY:
                return invalid_argument(
                    "group_by is not a known breakdown.",
                    f"Use one of: {', '.join(_COGS_GROUP_BY)}.",
                )
            data = await COGSService(self.context.db).cogs(
                workspace_id,
                date_from=date_from or today.replace(day=1),
                date_to=date_to or today,
                group_by=group_by,
            )
        elif report == "attribution_gap":
            data = await ReportingService(self.context.db).attribution_gap(
                workspace_id,
                date_from=date_from or today.replace(day=1),
                date_to=date_to or today,
            )
        elif report == "sales_performance":
            data = await SalesPerformanceService(self.context.db).sales_performance(
                workspace_id, date_from=date_from, date_to=date_to
            )
        elif report == "backlog":
            capacity_hours = args.get("weekly_capacity_hours")
            if capacity_hours is not None and (
                isinstance(capacity_hours, bool)
                or not isinstance(capacity_hours, int | float)
                or capacity_hours <= 0
            ):
                return invalid_argument("weekly_capacity_hours must be a positive number.")
            data = await CapacityService(self.context.db).compute_backlog(
                workspace_id,
                as_of=date_to,
                weekly_capacity_hours=float(capacity_hours) if capacity_hours else None,
            )
        else:  # estimate_capacity
            data = await CapacityService(self.context.db).compute_estimate_capacity(
                workspace_id, date_from or date_to
            )

        return {"success": True, "report": report, "data": data.model_dump(mode="json")}

    async def get_scorecard(self, args: ToolArguments) -> dict[str, object]:
        team = args.get("team", "reception")
        if team not in _TEAMS:
            return invalid_argument(
                "team is not a known scorecard.",
                f"Use one of: {', '.join(_TEAMS)}.",
            )

        window = self._window(args)
        if isinstance(window, str):
            return invalid_argument(window)
        start_date, end_date = window
        if (
            start_date is not None
            and end_date is not None
            and (end_date - start_date).days > _MAX_SCORECARD_DAYS
        ):
            return invalid_argument(
                f"The scorecard window cannot exceed {_MAX_SCORECARD_DAYS} days."
            )

        # The scorecard services resolve the workspace's timezone from the row
        # itself, so they take the object rather than the id. The id comes from
        # the caller's resolved membership, never from tool arguments, so loading
        # it by primary key cannot cross a tenant boundary.
        workspace = await self.context.db.get(Workspace, self.context.workspace_id)
        if workspace is None:
            return unavailable("The workspace could not be loaded.")

        service = ScorecardService(self.context.db)
        if team == "reception":
            card = await service.get_scorecard(workspace, start_date, end_date)
            return {"success": True, "team": team, "data": card.model_dump(mode="json")}

        rows = await service.get_technician_activity(workspace, start_date, end_date)
        return {
            "success": True,
            "team": team,
            "returned": len(rows),
            "data": [row.model_dump(mode="json") for row in rows],
        }
