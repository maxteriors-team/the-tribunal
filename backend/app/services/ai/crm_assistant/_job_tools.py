"""Field-service job (work order) read tools for the CRM assistant.

Read-only. Scheduling and dispatch stay on the HTTP surface; this only answers
"what work is on the board, and who is on it".
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException

from app.core.permissions import Capability, role_can
from app.models.field_service import JobStatus
from app.services.ai.crm_assistant._pagination import listing, parse_limit
from app.services.ai.crm_assistant._tool_context import (
    CRMToolContext,
    ToolArguments,
    ToolHandler,
    parse_uuid,
)
from app.services.ai.crm_assistant._tool_errors import invalid_argument, invalid_id, not_found
from app.services.jobs.job_service import JobService

_JOB_STATUSES = frozenset(status.value for status in JobStatus)


class JobAssistantTools:
    """Read the workspace's field-service jobs."""

    def __init__(self, context: CRMToolContext) -> None:
        self.context = context
        self.service = JobService(context.db)

    def handlers(self) -> dict[str, ToolHandler]:
        return {
            "list_jobs": self.list_jobs,
            "get_job": self.get_job,
        }

    def _visible_to_user_id(self) -> int | None:
        """The user this caller's job reads are confined to, or ``None`` for the board.

        Mirrors ``_calendar_scope_user_id`` in ``app/api/v1/jobs.py``: ``jobs:write``
        is the dispatch line, and everyone below it sees only the jobs they are
        tagged on. Keying off the capability (not a role name list) keeps the tool
        boundary on the same line as the route's and fails closed for unknown roles.
        """
        if role_can(self.context.role, Capability.JOBS_WRITE):
            return None
        return self.context.user_id

    async def list_jobs(self, args: ToolArguments) -> dict[str, object]:
        limit = parse_limit(args.get("limit"), default=10, maximum=50)
        if limit is None:
            return invalid_argument("limit must be an integer between 1 and 50.")

        status = args.get("status")
        if status is not None and status not in _JOB_STATUSES:
            return invalid_argument(
                "status is not a known job status.",
                f"Use one of: {', '.join(sorted(_JOB_STATUSES))}.",
            )

        try:
            date_from = self._parse_dt(args.get("date_from"))
            date_to = self._parse_dt(args.get("date_to"))
        except ValueError:
            return invalid_argument("Invalid job date range.", "Use ISO 8601 datetimes.")
        if date_from is not None and date_to is not None and date_from > date_to:
            return invalid_argument("date_from must not be after date_to.")

        result = await self.service.list(
            self.context.workspace_id,
            status=JobStatus(status) if status else None,
            date_from=date_from,
            date_to=date_to,
            visible_to_user_id=self._visible_to_user_id(),
        )
        # ``JobService.list`` returns the whole matching set; ``total`` stays the
        # true count so the model never reports the page size as the answer.
        items = list(result["items"])
        return listing(
            [job.model_dump(mode="json") for job in items[:limit]],
            total=int(result["total"]),
        )

    async def get_job(self, args: ToolArguments) -> dict[str, object]:
        job_id = parse_uuid(args.get("job_id"))
        if job_id is None:
            return invalid_id("job_id", "Call list_jobs to get a valid job id.")
        try:
            job = await self.service.get(
                job_id,
                self.context.workspace_id,
                visible_to_user_id=self._visible_to_user_id(),
            )
        except HTTPException:
            return not_found("Job", "Call list_jobs to get a visible id.")
        return {"success": True, "data": job.model_dump(mode="json")}

    @staticmethod
    def _parse_dt(raw_value: Any) -> datetime | None:
        """Parse an ISO 8601 argument into an aware UTC datetime."""

        if raw_value is None:
            return None
        if not isinstance(raw_value, str):
            raise ValueError("expected an ISO 8601 string")
        parsed = datetime.fromisoformat(raw_value)
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed
