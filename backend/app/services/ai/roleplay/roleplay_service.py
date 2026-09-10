"""Practice-arena orchestrator.

CRUD for personas + rehearsal runs, and the engine that drives a synthetic
prospect against an agent's real prompt and scores the result.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent
from app.models.roleplay import (
    PersonaDifficulty,
    ProspectPersona,
    RehearsalRun,
    RehearsalStatus,
    RehearseeType,
)
from app.services.ai.message_context_builder import get_workspace_timezone
from app.services.ai.roleplay.agent_responder import build_agent_system_prompt
from app.services.ai.roleplay.default_personas import DEFAULT_PERSONAS
from app.services.automations.events import EVENT_ROLEPLAY_COMPLETED, emit_automation_event
from app.services.exceptions import NotFoundError, ValidationError

logger = structlog.get_logger()

_MAX_TURNS_CAP = 12


class RoleplayService:
    """Service for the user-facing practice arena."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # === Persona CRUD ===

    async def ensure_default_personas(self) -> None:
        """Idempotently seed built-in personas (``workspace_id IS NULL``)."""
        result = await self.db.execute(
            select(ProspectPersona.slug).where(
                ProspectPersona.workspace_id.is_(None),
                ProspectPersona.is_builtin.is_(True),
            )
        )
        existing = {row[0] for row in result.all()}
        created = False
        for default in DEFAULT_PERSONAS:
            if default.slug in existing:
                continue
            self.db.add(
                ProspectPersona(
                    workspace_id=None,
                    slug=default.slug,
                    name=default.name,
                    description=default.description,
                    difficulty=default.difficulty,
                    channel=default.channel,
                    persona_prompt=default.persona_prompt,
                    opening_message=default.opening_message,
                    objections=list(default.objections),
                    goal=default.goal,
                    is_builtin=True,
                )
            )
            created = True
        if created:
            await self.db.commit()

    async def list_personas(self, workspace_id: uuid.UUID) -> list[ProspectPersona]:
        """List built-in templates plus this workspace's custom personas."""
        await self.ensure_default_personas()
        result = await self.db.execute(
            select(ProspectPersona)
            .where(
                or_(
                    ProspectPersona.workspace_id == workspace_id,
                    ProspectPersona.workspace_id.is_(None),
                )
            )
            .order_by(ProspectPersona.is_builtin.desc(), ProspectPersona.name.asc())
        )
        return list(result.scalars().all())

    async def get_persona(self, persona_id: uuid.UUID, workspace_id: uuid.UUID) -> ProspectPersona:
        """Fetch a persona usable by this workspace (own or built-in)."""
        result = await self.db.execute(
            select(ProspectPersona).where(ProspectPersona.id == persona_id)
        )
        persona = result.scalar_one_or_none()
        if persona is None or (
            persona.workspace_id is not None and persona.workspace_id != workspace_id
        ):
            raise NotFoundError("Persona not found")
        return persona

    async def create_persona(
        self, workspace_id: uuid.UUID, data: dict[str, Any]
    ) -> ProspectPersona:
        """Create a custom workspace persona."""
        difficulty = data.get("difficulty") or PersonaDifficulty.MEDIUM.value
        persona = ProspectPersona(
            workspace_id=workspace_id,
            slug=str(data.get("slug") or uuid.uuid4().hex[:12]),
            name=data["name"],
            description=data.get("description"),
            difficulty=PersonaDifficulty(difficulty),
            channel=data.get("channel") or "sms",
            persona_prompt=data["persona_prompt"],
            opening_message=data.get("opening_message"),
            objections=list(data.get("objections") or []),
            goal=data.get("goal"),
            is_builtin=False,
        )
        self.db.add(persona)
        await self.db.commit()
        await self.db.refresh(persona)
        return persona

    async def update_persona(
        self, persona_id: uuid.UUID, workspace_id: uuid.UUID, data: dict[str, Any]
    ) -> ProspectPersona:
        """Update a custom workspace persona (built-ins are read-only)."""
        persona = await self.get_persona(persona_id, workspace_id)
        if persona.is_builtin or persona.workspace_id is None:
            raise ValidationError("Built-in personas cannot be edited")
        for field_name in (
            "name",
            "description",
            "channel",
            "persona_prompt",
            "opening_message",
            "goal",
        ):
            if field_name in data and data[field_name] is not None:
                setattr(persona, field_name, data[field_name])
        if data.get("difficulty"):
            persona.difficulty = PersonaDifficulty(data["difficulty"])
        if data.get("objections") is not None:
            persona.objections = list(data["objections"])
        await self.db.commit()
        await self.db.refresh(persona)
        return persona

    async def delete_persona(self, persona_id: uuid.UUID, workspace_id: uuid.UUID) -> None:
        """Delete a custom workspace persona (built-ins are protected)."""
        persona = await self.get_persona(persona_id, workspace_id)
        if persona.is_builtin or persona.workspace_id is None:
            raise ValidationError("Built-in personas cannot be deleted")
        await self.db.delete(persona)
        await self.db.commit()

    # === Run CRUD ===

    async def list_runs(
        self, workspace_id: uuid.UUID, *, agent_id: uuid.UUID | None = None, limit: int = 50
    ) -> list[RehearsalRun]:
        """List rehearsal runs for a workspace, newest first."""
        stmt = select(RehearsalRun).where(
            RehearsalRun.workspace_id == workspace_id, RehearsalRun.deleted_at.is_(None)
        )
        if agent_id is not None:
            stmt = stmt.where(RehearsalRun.agent_id == agent_id)
        stmt = stmt.order_by(RehearsalRun.created_at.desc()).limit(limit)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_run(
        self,
        run_id: uuid.UUID,
        workspace_id: uuid.UUID,
        *,
        for_update: bool = False,
    ) -> RehearsalRun:
        """Fetch a rehearsal run scoped to the workspace; serialize mutations."""
        stmt = (
            select(RehearsalRun)
            .where(
                RehearsalRun.id == run_id,
                RehearsalRun.workspace_id == workspace_id,
                RehearsalRun.deleted_at.is_(None),
            )
            .execution_options(populate_existing=True)
        )
        if for_update:
            stmt = stmt.with_for_update()
        result = await self.db.execute(stmt)
        run = result.scalar_one_or_none()
        if run is None:
            raise NotFoundError("Rehearsal run not found")
        return run

    async def delete_run(self, run_id: uuid.UUID, workspace_id: uuid.UUID) -> None:
        """Hide the report but retain its deduplication identity."""
        run = await self.get_run(run_id, workspace_id, for_update=True)
        if run.status == RehearsalStatus.PENDING or (
            run.status == RehearsalStatus.RUNNING and run.pending_action is not None
        ):
            raise ValidationError("An executing rehearsal cannot be deleted")
        run.deleted_at = datetime.now(UTC)
        await self.db.commit()

    # === Rehearsal engine ===

    async def _load_agent(self, agent_id: uuid.UUID, workspace_id: uuid.UUID) -> Agent:
        result = await self.db.execute(
            select(Agent).where(
                Agent.id == agent_id,
                Agent.workspace_id == workspace_id,
            )
        )
        agent = result.scalar_one_or_none()
        if agent is None:
            raise NotFoundError("Agent not found")
        return agent

    async def create_run(
        self,
        workspace_id: uuid.UUID,
        *,
        idempotency_key: uuid.UUID,
        agent_id: uuid.UUID,
        persona_id: uuid.UUID,
        rehearsee: str = RehearseeType.AI.value,
        channel: str | None = None,
        max_turns: int = 6,
    ) -> RehearsalRun:
        """Commit an identity and immutable inputs. Never call a provider in a request."""
        rehearsee_type = RehearseeType(rehearsee)
        if not 1 <= max_turns <= _MAX_TURNS_CAP:
            raise ValidationError("Rehearsals must have between 1 and 12 turns")
        fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "agent_id": str(agent_id),
                    "persona_id": str(persona_id),
                    "rehearsee": rehearsee,
                    "channel": channel,
                    "max_turns": max_turns,
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        existing = await self.db.scalar(
            select(RehearsalRun).where(
                RehearsalRun.workspace_id == workspace_id,
                RehearsalRun.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            return self._check_request(existing, fingerprint)

        agent = await self._load_agent(agent_id, workspace_id)
        persona = await self.get_persona(persona_id, workspace_id)
        timezone = await get_workspace_timezone(workspace_id, self.db)
        context = {
            "system_prompt": await build_agent_system_prompt(self.db, agent, timezone=timezone),
            "temperature": agent.temperature,
            "persona_prompt": persona.persona_prompt,
            "objections": list(persona.objections),
            "goal": persona.goal,
        }
        opening = (persona.opening_message or "").strip()
        transcript = [{"role": "prospect", "content": opening}] if opening else []
        action = (
            "prospect" if not opening else ("agent" if rehearsee_type == RehearseeType.AI else None)
        )
        # The unique workspace/key constraint arbitrates concurrent HTTP retries.
        result = await self.db.execute(
            insert(RehearsalRun)
            .values(
                workspace_id=workspace_id,
                idempotency_key=idempotency_key,
                request_fingerprint=fingerprint,
                execution_context=context,
                agent_id=agent.id,
                persona_id=persona.id,
                agent_name=agent.name,
                persona_name=persona.name,
                rehearsee=rehearsee_type,
                channel=channel or persona.channel or "sms",
                max_turns=max_turns,
                transcript=transcript,
                pending_action=action,
                status=RehearsalStatus.PENDING if action else RehearsalStatus.RUNNING,
            )
            .on_conflict_do_nothing(constraint="uq_rehearsal_request")
            .returning(RehearsalRun)
        )
        run = result.scalar_one_or_none()
        if run is None:
            run = (
                await self.db.execute(
                    select(RehearsalRun).where(
                        RehearsalRun.workspace_id == workspace_id,
                        RehearsalRun.idempotency_key == idempotency_key,
                    )
                )
            ).scalar_one()
            self._check_request(run, fingerprint)
        await self.db.commit()
        return run

    @staticmethod
    def _check_request(run: RehearsalRun, fingerprint: str) -> RehearsalRun:
        if run.request_fingerprint != fingerprint:
            raise ValidationError(
                "This request key was already used for different rehearsal settings"
            )
        if run.deleted_at is not None:
            raise ValidationError("This rehearsal was deleted. Start a new rehearsal instead")
        return run

    async def advance_human_turn(
        self,
        run_id: uuid.UUID,
        workspace_id: uuid.UUID,
        message: str,
        expected_turn_count: int,
    ) -> RehearsalRun:
        """Checkpoint the human message once, then queue the prospect's reply."""
        run = await self.get_run(run_id, workspace_id, for_update=True)
        if run.rehearsee != RehearseeType.HUMAN:
            raise ValidationError("Only human-rehearsee runs accept manual turns")
        text = message.strip()
        if not text or len(text) > 4000:
            raise ValidationError("Message must contain between 1 and 4000 characters")
        transcript = list(run.transcript or [])
        if 0 <= expected_turn_count < len(transcript):
            if transcript[expected_turn_count] == {"role": "agent", "content": text}:
                return run  # A lost response must not append or pay for another turn.
            raise ValidationError("This turn was already submitted with a different message")
        if expected_turn_count != len(transcript):
            raise ValidationError("Refresh the rehearsal before sending another message")
        if run.status != RehearsalStatus.RUNNING or run.pending_action is not None:
            raise ValidationError("Wait for the current rehearsal step to finish")
        if sum(t["role"] == "agent" for t in transcript) >= run.max_turns:
            raise ValidationError("Turn limit reached; finish and score this rehearsal")
        await self._ensure_execution_context(run)
        run.transcript = [*transcript, {"role": "agent", "content": text}]
        run.pending_action = "prospect"
        run.status = RehearsalStatus.PENDING
        await self.db.commit()
        return run

    async def score_run(self, run_id: uuid.UUID, workspace_id: uuid.UUID) -> RehearsalRun:
        """Queue scoring once; repeated requests return the same execution status."""
        run = await self.get_run(run_id, workspace_id, for_update=True)
        if run.status in (RehearsalStatus.COMPLETED, RehearsalStatus.FAILED):
            return run
        if run.pending_action == "score":
            return run
        if run.pending_action is not None or run.status == RehearsalStatus.PENDING:
            raise ValidationError("Wait for the current rehearsal step to finish")
        if not any(t.get("role") == "agent" for t in run.transcript):
            raise ValidationError("Nothing to score yet")
        await self._ensure_execution_context(run)
        run.pending_action = "score"
        run.status = RehearsalStatus.PENDING
        await self.db.commit()
        return run

    async def retry_run(
        self,
        run_id: uuid.UUID,
        workspace_id: uuid.UUID,
        expected_attempt_count: int,
    ) -> RehearsalRun:
        """Resume only a known failed step, without replaying saved paid turns."""
        run = await self.get_run(run_id, workspace_id, for_update=True)
        if run.attempt_count != expected_attempt_count or run.status != RehearsalStatus.FAILED:
            return run
        if not run.retryable or not run.pending_action:
            raise ValidationError(
                "This step cannot be retried without risking duplicate provider work"
            )
        run.status = RehearsalStatus.PENDING
        run.error = None
        run.retryable = False
        run.completed_at = None
        await self.db.commit()
        return run

    async def _ensure_execution_context(self, run: RehearsalRun) -> None:
        """Allow existing idle human rehearsals to use the durable engine too."""
        if run.execution_context is not None:
            return
        if run.persona_id is None:
            raise ValidationError("Persona for this rehearsal no longer exists")
        persona = await self.get_persona(run.persona_id, run.workspace_id)
        run.execution_context = {
            "persona_prompt": persona.persona_prompt,
            "objections": list(persona.objections),
            "goal": persona.goal,
        }

    async def _emit_completed_event(self, run: RehearsalRun) -> None:
        """Queue the completion event in the same transaction as the genuine report."""
        if run.status != RehearsalStatus.COMPLETED or run.overall_score is None:
            return
        await emit_automation_event(
            self.db,
            workspace_id=run.workspace_id,
            event_type=EVENT_ROLEPLAY_COMPLETED,
            contact_id=None,
            payload={
                "run_id": str(run.id),
                "agent_id": str(run.agent_id) if run.agent_id else None,
                "agent_name": run.agent_name,
                "persona_name": run.persona_name,
                "overall_score": run.overall_score,
                "rehearsee": run.rehearsee.value
                if hasattr(run.rehearsee, "value")
                else str(run.rehearsee),
            },
        )

    async def _notify_roleplay_completed(self, run: RehearsalRun) -> None:
        """Push + email workspace members about a completed rehearsal (best-effort)."""
        from app.services.notifications import notify_workspace_event

        if run.status != RehearsalStatus.COMPLETED or run.overall_score is None:
            return
        agent = run.agent_name or "an agent"
        persona = run.persona_name or "a persona"
        score = run.overall_score
        score_text = f"{score}/100" if score is not None else "not scored"
        title = "Roleplay completed"
        body = f"{agent} finished a rehearsal vs {persona} (score {score_text})."
        try:
            await notify_workspace_event(
                self.db,
                workspace_id=run.workspace_id,
                notification_type="roleplay",
                title=title,
                body=body,
                data={
                    "type": "roleplay",
                    "runId": str(run.id),
                    "screen": f"/(tabs)/roleplay/{run.id}",
                },
                channel_id="roleplay",
                email_subject=title,
                email_heading="Roleplay Completed",
                email_intro=body,
                email_details={
                    "Agent": agent,
                    "Persona": persona,
                    "Score": score_text,
                },
                dedupe_key=str(run.id),
            )
        except Exception:
            logger.warning("roleplay_notification_failed", run_id=str(run.id))
