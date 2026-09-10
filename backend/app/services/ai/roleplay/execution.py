"""Database-claimed, checkpointed rehearsal steps; no automatic paid-call replay.

A provider cannot atomically commit with Postgres. If its result is uncertain
(timeout, cancellation, process death or lost checkpoint), fail unscored and
forbid retry. Known rejections/invalid results may be explicitly retried, only
at the failed step. Successful turns and reports are never regenerated.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import structlog
from openai import APIStatusError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.roleplay import RehearsalRun, RehearsalStatus, RehearseeType
from app.services.ai.openai_credentials import (
    OpenAICredentialError,
    create_workspace_openai_client,
)
from app.services.ai.roleplay.agent_responder import generate_agent_reply
from app.services.ai.roleplay.prospect_simulator import generate_prospect_reply
from app.services.ai.roleplay.report_scorer import RehearsalReport, score_rehearsal
from app.services.ai.roleplay.roleplay_service import RoleplayService

logger = structlog.get_logger()
STEP_TIMEOUT_SECONDS = 90
# Longer than the hard step timeout. Expiry never reclaims/replays paid work.
STALE_AFTER = timedelta(minutes=3)
INTERRUPTED = (
    "Execution was interrupted or its provider outcome is unknown. Saved dialogue is intact. "
    "Retry is disabled to avoid duplicate charges; start a new rehearsal only intentionally."
)


async def claim_runs(db: AsyncSession, limit: int) -> list[tuple[uuid.UUID, uuid.UUID]]:
    """Short SKIP LOCKED claims work even during an overlapping single-process deploy."""
    runs = list(
        (
            await db.scalars(
                select(RehearsalRun)
                .where(
                    RehearsalRun.status == RehearsalStatus.PENDING,
                    RehearsalRun.pending_action.is_not(None),
                    RehearsalRun.execution_context.is_not(None),
                    RehearsalRun.deleted_at.is_(None),
                )
                .order_by(RehearsalRun.updated_at, RehearsalRun.id)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        ).all()
    )
    claims = []
    for run in runs:
        token = uuid.uuid4()
        run.status = RehearsalStatus.RUNNING
        run.processing_token = token
        run.processing_started_at = datetime.now(UTC)
        run.attempt_count += 1
        run.retryable = False
        claims.append((run.id, token))
    await db.commit()
    return claims


def _fail(run: RehearsalRun, error: str, *, retryable: bool) -> None:
    run.status = RehearsalStatus.FAILED
    run.error = error
    run.retryable = retryable
    run.processing_token = None
    run.processing_started_at = None
    run.completed_at = datetime.now(UTC)
    run.overall_score = run.objection_coverage = run.tone_score = None
    run.booking_attempted = None
    run.scores = {}
    run.summary = None
    run.strengths = []
    run.gaps = []
    run.suggestions = []


async def recover_stale_runs(db: AsyncSession) -> int:
    """Recover readable terminal status after process death, never replay an uncertain call."""
    runs = list(
        (
            await db.scalars(
                select(RehearsalRun)
                .where(
                    RehearsalRun.status == RehearsalStatus.RUNNING,
                    RehearsalRun.processing_token.is_not(None),
                    RehearsalRun.processing_started_at < datetime.now(UTC) - STALE_AFTER,
                )
                .limit(100)
                .with_for_update(skip_locked=True)
            )
        ).all()
    )
    for run in runs:
        _fail(run, INTERRUPTED, retryable=False)
    await db.commit()
    return len(runs)


async def _owned_run(
    db: AsyncSession,
    run_id: uuid.UUID,
    token: uuid.UUID,
    *,
    lock: bool = False,
) -> RehearsalRun | None:
    stmt = (
        select(RehearsalRun)
        .where(
            RehearsalRun.id == run_id,
            RehearsalRun.status == RehearsalStatus.RUNNING,
            RehearsalRun.processing_token == token,
        )
        .execution_options(populate_existing=True)
    )
    result = await db.execute(stmt.with_for_update() if lock else stmt)
    return result.scalar_one_or_none()


async def _record_failure(
    db: AsyncSession,
    run_id: uuid.UUID,
    token: uuid.UUID,
    error: str,
    *,
    retryable: bool,
) -> None:
    await db.rollback()
    run = await _owned_run(db, run_id, token, lock=True)
    if run is not None:
        _fail(run, error, retryable=retryable)
    await db.commit()


async def _generate_step(db: AsyncSession, run: RehearsalRun) -> str | RehearsalReport:
    context = run.execution_context or {}
    async with asyncio.timeout(STEP_TIMEOUT_SECONDS):
        client = await create_workspace_openai_client(db, run.workspace_id)
        # SDK defaults retry timeouts/5xx; that can repeat paid work invisibly.
        async with client.with_options(max_retries=0, timeout=60.0) as provider:
            await db.commit()  # Release DB connection before the slow provider call.
            if run.pending_action == "agent":
                return await generate_agent_reply(
                    client=provider,
                    system_prompt=context["system_prompt"],
                    transcript=run.transcript,
                    temperature=context["temperature"],
                )
            if run.pending_action == "prospect":
                return await generate_prospect_reply(
                    client=provider,
                    persona_prompt=context["persona_prompt"],
                    transcript=run.transcript,
                )
            if run.pending_action == "score":
                return await score_rehearsal(
                    client=provider,
                    transcript=run.transcript,
                    persona_name=run.persona_name or "Prospect",
                    objections=context["objections"],
                    goal=context["goal"],
                )
            raise RuntimeError("Unknown rehearsal step")


async def _save_result(
    db: AsyncSession,
    run: RehearsalRun,
    result: str | RehearsalReport,
) -> None:
    run.processing_token = None
    run.processing_started_at = None
    if isinstance(result, RehearsalReport):
        run.overall_score = result.overall_score
        run.objection_coverage = result.objection_coverage
        run.booking_attempted = result.booking_attempted
        run.tone_score = result.tone_score
        run.strengths = result.strengths
        run.gaps = result.gaps
        run.suggestions = result.suggestions
        run.summary, run.scores = result.summary, result.scores
        run.status = RehearsalStatus.COMPLETED
        run.pending_action = None
        run.completed_at = datetime.now(UTC)
        await RoleplayService(db)._emit_completed_event(run)
    else:
        run.transcript = [*run.transcript, {"role": run.pending_action, "content": result}]
        if run.pending_action == "agent":
            run.pending_action = "prospect"
        elif run.rehearsee == RehearseeType.HUMAN:
            run.pending_action = None
        else:
            rep_turns = sum(t["role"] == "agent" for t in run.transcript)
            run.pending_action = "score" if rep_turns >= run.max_turns else "agent"
        run.status = RehearsalStatus.PENDING if run.pending_action else RehearsalStatus.RUNNING
    await db.commit()


async def execute_step(db: AsyncSession, run_id: uuid.UUID, token: uuid.UUID) -> None:
    """Run exactly the claimed step, outside a DB transaction, then fence its checkpoint."""
    run = await _owned_run(db, run_id, token, lock=True)
    if run is None:
        await db.commit()
        return
    # Consume the claim ticket once, even if an internal delivery is duplicated.
    token = uuid.uuid4()
    run.processing_token = token
    await db.commit()
    action = run.pending_action
    try:
        result = await _generate_step(db, run)
    except asyncio.CancelledError:
        await _record_failure(db, run_id, token, INTERRUPTED, retryable=False)
        raise
    except Exception as exc:
        # A definite rejection or invalid returned result is not a lost response.
        # Retrying either is explicit and may pay for the failed step again.
        retryable = isinstance(exc, (OpenAICredentialError, ValueError)) or (
            isinstance(exc, APIStatusError) and exc.status_code in (400, 401, 403, 404, 422, 429)
        )
        error = (
            f"The {action} step failed and remains unscored. Check provider settings, then retry "
            "only this step; a new provider attempt may be charged. Saved turns will not repeat."
            if retryable
            else INTERRUPTED
        )
        logger.warning(
            "rehearsal_step_failed",
            run_id=str(run_id),
            step=action,
            error_type=type(exc).__name__,
            retryable=retryable,
        )
        await _record_failure(db, run_id, token, error, retryable=retryable)
        return

    try:
        run = await _owned_run(db, run_id, token, lock=True)
        if run is None:
            return  # Expired owners cannot overwrite a recovered terminal status.
        await _save_result(db, run, result)
    except asyncio.CancelledError:
        await _record_failure(db, run_id, token, INTERRUPTED, retryable=False)
        raise
    except Exception:
        await _record_failure(db, run_id, token, INTERRUPTED, retryable=False)
        logger.warning("rehearsal_checkpoint_failed", run_id=str(run_id))
        return

    # Only after the completed report/event transaction is durably committed.
    if isinstance(result, RehearsalReport):
        try:
            await RoleplayService(db)._notify_roleplay_completed(run)
            await db.commit()
        except Exception:
            await db.rollback()
            logger.warning("rehearsal_notification_failed", run_id=str(run_id))
