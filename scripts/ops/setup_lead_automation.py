"""Provision the canonical consent-aware website lead-to-call funnel.

The source remains ``collect`` so ``lead_created`` owns the one first SMS. The
workflow is source-scoped and idempotently updated in place. It tags a new lead,
sends consent-gated SMS through the selected AI agent, and parks between a
bounded set of follow-ups. Every outbound is preceded by a terminal branch;
the worker also stops this named acquisition funnel if a booking lands while a
wait is parked.

Production writes require the shared harness confirmation. Dry runs execute all
readiness checks and print the intended graph without committing.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_HARNESS = next(
    path / "backend" / "scripts" / "_harness.py"
    for path in Path(__file__).resolve().parents
    if (path / "backend" / "scripts" / "_harness.py").is_file()
)
if str(_HARNESS.parent) not in sys.path:
    sys.path.insert(0, str(_HARNESS.parent))

from _harness import (  # type: ignore[import-not-found]  # noqa: E402
    EXIT_FAILURE,
    EXIT_OK,
    ExecutionContext,
    ScriptAbortError,
    bootstrap,
    log_event,
    run,
)

DEFAULT_PUBLIC_KEY = "ls_n2dSPTZe"
DEFAULT_AGENT_ID: str | None = None
DEFAULT_TAGS = ("Perm Light Lead", "Facebook")
DEFAULT_SOURCE_DETAIL = "permholidaylights instant quote"
DEFAULT_NAME_BASE = "Perm Light Lead — AI call-booking funnel"
DEFAULT_MESSAGE = (
    "Hi {first_name}, it's Max with Maxteriors — got your permanent roofline "
    "lighting estimate. What questions can I answer before we book a quick call?"
)
DEFAULT_FOLLOW_UP_MESSAGES = (
    "Hi {first_name}, want to book a quick phone or video call about your lighting estimate?",
    "Last check-in, {first_name}: reply here if you'd like a phone or video consultation.",
)
DEFAULT_WAIT_MINUTES = (30, 1440)
DEFAULT_SOURCE_TYPE = "facebook_ads"
KEEP_SOURCE_TYPE = "keep"
TRIGGER_TYPE = "lead_created"
FUNNEL_ID_PREFIX = "acquisition:lead-source:"
REQUIRED_STAGES = frozenset({"Qualified", "Visit/Demo Scheduled"})
REQUIRED_AGENT_TOOLS = frozenset({"book_appointment"})
SMS_AUTO = "auto"
SMS_ON = "on"
SMS_OFF = "off"
SMS_MODES = (SMS_AUTO, SMS_ON, SMS_OFF)


@dataclass(frozen=True)
class Readiness:
    agent_id: uuid.UUID
    blockers: tuple[str, ...]

    @property
    def ready(self) -> bool:
        return not self.blockers


def _normalize_tags(tags: Iterable[str]) -> list[str]:
    """Trim, drop blanks, and de-duplicate while preserving operator order."""
    seen: dict[str, None] = {}
    seen_keys: set[str] = set()
    for raw in tags:
        tag = str(raw).strip()
        key = tag.casefold()
        if tag and key not in seen_keys:
            seen[tag] = None
            seen_keys.add(key)
    return list(seen)


def _terminal_branch(step_id: str, continue_to: str) -> dict[str, Any]:
    """Stop booked, opted-out, lost, or globally muted contacts before a send."""
    return {
        "id": step_id,
        "type": "branch",
        "config": {
            "logic": "or",
            "conditions": [
                {"field": "last_appointment_status", "operator": "equals", "value": "scheduled"},
                {"field": "sms_consent_status", "operator": "not_equals", "value": "opted_in"},
                {"field": "status", "operator": "equals", "value": "lost"},
            ],
            "then_goto": "__end__",
            "else_goto": continue_to,
        },
    }


def _build_actions(
    tags: Sequence[str],
    message: str,
    *,
    with_sms: bool,
    agent_id: str | uuid.UUID | None = None,
    follow_up_messages: Sequence[str] = DEFAULT_FOLLOW_UP_MESSAGES,
    wait_minutes: Sequence[int] = DEFAULT_WAIT_MINUTES,
) -> list[dict[str, Any]]:
    """Build one bounded acquisition graph; every SMS is consent-gated."""
    actions: list[dict[str, Any]] = [{"type": "add_tag", "config": {"tag": tag}} for tag in tags]
    if not with_sms:
        return actions
    if agent_id is None:
        raise ValueError("agent_id is required when the funnel sends SMS")
    if len(follow_up_messages) != len(wait_minutes):
        raise ValueError("each follow-up requires exactly one preceding wait")

    messages = [message, *follow_up_messages]
    for index, body in enumerate(messages):
        send_id = f"send_{index + 1}"
        actions.append(_terminal_branch(f"terminal_{index + 1}", send_id))
        actions.append(
            {
                "id": send_id,
                "type": "send_sms",
                "config": {
                    "message": body,
                    "fallbacks": {"first_name": "there"},
                    "agent_id": str(agent_id),
                    "require_consent": True,
                    "quiet_hours_start": "21:00",
                    "quiet_hours_end": "08:00",
                },
            }
        )
        if index < len(wait_minutes):
            actions.append(
                {
                    "id": f"wait_{index + 1}",
                    "type": "wait",
                    "config": {"minutes": int(wait_minutes[index])},
                }
            )
    return actions


def _resolve_sms(mode: str, source_action: str) -> tuple[bool, str]:
    """The acquisition automation is the only allowed first-outreach owner."""
    if mode == SMS_OFF:
        return False, "--sms off"
    if source_action != "collect":
        return True, f"source action will be changed from {source_action!r} to 'collect'"
    return True, "lead source action is 'collect'"


def _build_trigger_config(public_key: str, source_id: str, source_detail: str) -> dict[str, Any]:
    return {
        "lead_source_public_key": public_key,
        "lead_source_id": source_id,
        "source_detail": source_detail,
        "funnel_id": f"{FUNNEL_ID_PREFIX}{source_id}",
    }


def _parse_labels(args: argparse.Namespace, logger: logging.Logger) -> tuple[list[str], Any] | None:
    from app.models.lead_source import LeadSourceType

    tags = _normalize_tags(args.tag or DEFAULT_TAGS)
    if not tags:
        log_event(logger, logging.ERROR, "--tag produced no usable tag names")
        return None
    if args.source_type == KEEP_SOURCE_TYPE:
        return tags, None
    try:
        return tags, LeadSourceType(args.source_type)
    except ValueError:
        log_event(
            logger,
            logging.ERROR,
            "unknown --source-type",
            value=args.source_type,
            valid=",".join([*(member.value for member in LeadSourceType), KEEP_SOURCE_TYPE]),
        )
        return None


def _policy_for(profile: Any | None, action_type: str) -> str:
    if profile is None:
        return "auto"
    return str((profile.action_policies or {}).get(action_type, profile.default_policy))


def _readiness_blockers(  # noqa: PLR0912
    *,
    source: Any,
    agent: Any | None,
    staff: Any | None,
    human_profile: Any | None,
    has_google_connection: bool,
    auto_pipeline_enabled: bool,
    stage_names: set[str],
    consent_integration_confirmed: bool,
) -> list[str]:
    """Pure readiness audit used by the CLI and regression tests."""
    blockers: list[str] = []
    if not source.enabled:
        blockers.append("target lead source is disabled")
    if agent is None or not agent.is_active:
        blockers.append("selected AI agent is missing or inactive")
        return blockers

    tools = set(agent.enabled_tools or [])
    missing_tools = REQUIRED_AGENT_TOOLS - tools
    if missing_tools:
        blockers.append(f"agent is missing tools: {', '.join(sorted(missing_tools))}")
    settings = agent.tool_settings or {}
    if settings.get("website_lead_qualification_enabled") is not True:
        blockers.append("website-lead qualification is disabled")
    questions = settings.get("qualification_questions")
    if not isinstance(questions, list) or not any(str(item).strip() for item in questions):
        blockers.append("qualification questions are not configured")
    score = settings.get("qualification_min_score")
    if isinstance(score, bool) or not isinstance(score, int) or not 0 <= score <= 100:
        blockers.append("qualification minimum score is not configured")
    label = settings.get("qualification_booking_label")
    if not isinstance(label, str) or not label.strip():
        blockers.append("qualification booking label is not configured")
    if _policy_for(human_profile, "book_appointment") != "auto":
        blockers.append("book_appointment action policy must be auto")
    if staff is None or not staff.is_active or staff.user_id is None:
        blockers.append("agent needs active bookable staff linked to a user")
    if not has_google_connection:
        blockers.append("assigned rep needs a connected Google Calendar for video calls")
    if not auto_pipeline_enabled:
        blockers.append("workspace auto-pipeline is disabled")
    missing_stages = REQUIRED_STAGES - stage_names
    if missing_stages:
        blockers.append(f"pipeline is missing stages: {', '.join(sorted(missing_stages))}")
    if not consent_integration_confirmed:
        blockers.append("public form integration must send explicit sms_consent")
    return blockers


async def _load_readiness(
    db: Any, source: Any, raw_agent_id: str | None, consent: bool
) -> Readiness:
    from sqlalchemy import select

    from app.models.agent import Agent
    from app.models.google_calendar_connection import GoogleCalendarConnection
    from app.models.human_profile import HumanProfile
    from app.models.pipeline import Pipeline, PipelineStage
    from app.models.workspace import Workspace

    if not raw_agent_id:
        return Readiness(uuid.UUID(int=0), ("--agent-id is required",))
    try:
        agent_id = uuid.UUID(raw_agent_id)
    except ValueError:
        return Readiness(uuid.UUID(int=0), ("--agent-id must be a UUID",))

    agent = await db.scalar(
        select(Agent).where(Agent.id == agent_id, Agent.workspace_id == source.workspace_id)
    )
    from app.services.calendar.staff_assignment import (
        STRATEGY_SINGLE,
        VALID_STRATEGIES,
        resolve_staff_for_booking,
    )

    staff = None
    if agent is not None and agent.is_active:
        strategy = agent.assignment_strategy or STRATEGY_SINGLE
        if strategy in VALID_STRATEGIES:
            staff = await resolve_staff_for_booking(db, agent=agent, record=False)
    profile = await db.scalar(
        select(HumanProfile).where(
            HumanProfile.workspace_id == source.workspace_id,
            HumanProfile.agent_id == agent_id,
        )
    )
    has_google = False
    if staff is not None and staff.user_id is not None:
        has_google = (
            await db.scalar(
                select(GoogleCalendarConnection.id).where(
                    GoogleCalendarConnection.user_id == staff.user_id
                )
            )
            is not None
        )
    workspace = await db.get(Workspace, source.workspace_id)
    settings = workspace.settings if workspace is not None else {}
    auto_pipeline = bool((settings or {}).get("auto_pipeline", {}).get("enabled"))
    stages = set(
        (
            await db.execute(
                select(PipelineStage.name)
                .join(Pipeline, Pipeline.id == PipelineStage.pipeline_id)
                .where(Pipeline.workspace_id == source.workspace_id, Pipeline.is_active.is_(True))
            )
        ).scalars()
    )
    blockers = _readiness_blockers(
        source=source,
        agent=agent,
        staff=staff,
        human_profile=profile,
        has_google_connection=has_google,
        auto_pipeline_enabled=auto_pipeline,
        stage_names=stages,
        consent_integration_confirmed=consent,
    )
    return Readiness(agent_id, tuple(blockers))


async def _apply(ctx: ExecutionContext, args: argparse.Namespace) -> int:
    from sqlalchemy import select

    from app.db.session import AsyncSessionLocal
    from app.models.automation import Automation
    from app.models.lead_source import LeadSource

    parsed = _parse_labels(args, ctx.logger)
    if parsed is None:
        return int(EXIT_FAILURE)
    tags, want_channel = parsed

    async with AsyncSessionLocal() as db:
        source = await db.scalar(select(LeadSource).where(LeadSource.public_key == args.public_key))
        if source is None:
            log_event(
                ctx.logger, logging.ERROR, "lead source not found", public_key=args.public_key
            )
            return int(EXIT_FAILURE)

        with_sms, sms_reason = _resolve_sms(args.sms, source.action)
        readiness = await _load_readiness(
            db, source, args.agent_id, args.consent_integration_confirmed
        )
        if with_sms and not readiness.ready:
            for blocker in readiness.blockers:
                log_event(
                    ctx.logger,
                    logging.ERROR,
                    "call-booking readiness blocker",
                    blocker=blocker,
                )
            return int(EXIT_FAILURE)

        trigger_config = _build_trigger_config(args.public_key, str(source.id), args.source_detail)
        actions = _build_actions(
            tags,
            args.message,
            with_sms=with_sms,
            agent_id=readiness.agent_id if with_sms else None,
            follow_up_messages=args.follow_up_message or DEFAULT_FOLLOW_UP_MESSAGES,
            wait_minutes=args.wait_minutes,
        )
        existing = await db.scalar(
            select(Automation).where(
                Automation.workspace_id == source.workspace_id,
                Automation.trigger_type == TRIGGER_TYPE,
                Automation.trigger_config["lead_source_public_key"].astext == args.public_key,
            )
        )
        name = args.name or DEFAULT_NAME_BASE
        verb = "update" if existing else "create"
        log_event(
            ctx.logger,
            logging.INFO,
            f"would {verb} automation" if ctx.dry_run else f"{verb} automation",
            name=name,
            actions=len(actions),
            sends_sms=with_sms,
            sms_reason=sms_reason,
            funnel_id=trigger_config["funnel_id"],
        )
        if ctx.dry_run:
            log_event(ctx.logger, logging.WARNING, "dry-run: no changes committed")
            return int(EXIT_OK)

        ctx.confirm(f"{verb} the '{name}' automation")
        source.action = "collect"
        if want_channel is not None:
            source.source_type = want_channel
        if existing is None:
            existing = Automation(workspace_id=source.workspace_id)
            db.add(existing)
        existing.name = name
        existing.description = args.description
        existing.trigger_type = TRIGGER_TYPE
        existing.trigger_config = trigger_config
        existing.actions = actions
        existing.is_active = True
        await db.commit()
        log_event(
            ctx.logger,
            logging.INFO,
            "call-booking funnel ready",
            automation_id=str(existing.id),
            lead_source_action=source.action,
            agent_id=str(readiness.agent_id) if with_sms else None,
        )
        return int(EXIT_OK)


def _configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--public-key", default=DEFAULT_PUBLIC_KEY)
    parser.add_argument("--agent-id", default=DEFAULT_AGENT_ID)
    parser.add_argument("--tag", action="append", default=None)
    parser.add_argument("--source-type", default=DEFAULT_SOURCE_TYPE)
    parser.add_argument("--source-detail", default=DEFAULT_SOURCE_DETAIL)
    parser.add_argument("--name", default=None)
    parser.add_argument("--description", default="Consent-aware AI lead-to-call acquisition funnel")
    parser.add_argument("--message", default=DEFAULT_MESSAGE)
    parser.add_argument("--follow-up-message", action="append", default=None)
    parser.add_argument(
        "--wait-minutes",
        nargs=2,
        type=int,
        metavar=("FIRST", "SECOND"),
        default=DEFAULT_WAIT_MINUTES,
    )
    parser.add_argument("--sms", choices=SMS_MODES, default=SMS_AUTO)
    parser.add_argument(
        "--consent-integration-confirmed",
        action="store_true",
        help="Assert that the public form sends sms_consent only when its checkbox is selected.",
    )


def main() -> int:
    ctx, args = bootstrap(
        description="Create/refresh a consent-aware AI lead-to-call acquisition funnel.",
        logger_name="setup_lead_automation",
        configure=_configure,
    )
    try:
        return asyncio.run(_apply(ctx, args))
    except ScriptAbortError:
        raise
    except Exception:
        ctx.logger.exception("failed to set up lead automation")
        return int(EXIT_FAILURE)


if __name__ == "__main__":
    raise SystemExit(run(main))
