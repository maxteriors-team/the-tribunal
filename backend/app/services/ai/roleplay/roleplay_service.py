"""Practice-arena orchestrator.

CRUD for personas + rehearsal runs, and the engine that drives a synthetic
prospect against an agent's real prompt and scores the result.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from openai import AsyncOpenAI
from sqlalchemy import or_, select
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
from app.services.ai.openai_credentials import get_workspace_openai_bearer_token
from app.services.ai.roleplay.agent_responder import (
    build_agent_system_prompt,
    generate_agent_reply,
)
from app.services.ai.roleplay.default_personas import DEFAULT_PERSONAS
from app.services.ai.roleplay.prospect_simulator import generate_prospect_reply
from app.services.ai.roleplay.report_scorer import score_rehearsal
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
        stmt = select(RehearsalRun).where(RehearsalRun.workspace_id == workspace_id)
        if agent_id is not None:
            stmt = stmt.where(RehearsalRun.agent_id == agent_id)
        stmt = stmt.order_by(RehearsalRun.created_at.desc()).limit(limit)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_run(self, run_id: uuid.UUID, workspace_id: uuid.UUID) -> RehearsalRun:
        """Fetch a rehearsal run scoped to the workspace."""
        result = await self.db.execute(
            select(RehearsalRun).where(
                RehearsalRun.id == run_id,
                RehearsalRun.workspace_id == workspace_id,
            )
        )
        run = result.scalar_one_or_none()
        if run is None:
            raise NotFoundError("Rehearsal run not found")
        return run

    async def delete_run(self, run_id: uuid.UUID, workspace_id: uuid.UUID) -> None:
        """Delete a rehearsal run."""
        run = await self.get_run(run_id, workspace_id)
        await self.db.delete(run)
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

    async def _client(self, workspace_id: uuid.UUID) -> AsyncOpenAI:
        token = await get_workspace_openai_bearer_token(self.db, workspace_id)
        if not token:
            raise ValidationError("No OpenAI credential is configured for this workspace")
        return AsyncOpenAI(api_key=token)

    async def create_run(
        self,
        workspace_id: uuid.UUID,
        *,
        agent_id: uuid.UUID,
        persona_id: uuid.UUID,
        rehearsee: str = RehearseeType.AI.value,
        channel: str | None = None,
        max_turns: int = 6,
    ) -> RehearsalRun:
        """Create a rehearsal run and, for AI rehearsees, run + score it inline.

        For ``rehearsee == "human"`` the run is left ``running`` with only the
        prospect's opening message so a human rep can reply turn-by-turn via
        :meth:`advance_human_turn`, then finalize with :meth:`score_run`.
        """
        rehearsee_type = RehearseeType(rehearsee)
        agent = await self._load_agent(agent_id, workspace_id)
        persona = await self.get_persona(persona_id, workspace_id)
        turns = max(1, min(_MAX_TURNS_CAP, max_turns))
        run_channel = channel or persona.channel or "sms"

        client = await self._client(workspace_id)

        # Seed the transcript with the prospect's opening line.
        opening = (persona.opening_message or "").strip()
        if not opening:
            opening = await generate_prospect_reply(
                client=client,
                persona_prompt=persona.persona_prompt,
                transcript=[],
            )
        transcript: list[dict[str, Any]] = [{"role": "prospect", "content": opening}]

        run = RehearsalRun(
            workspace_id=workspace_id,
            agent_id=agent.id,
            persona_id=persona.id,
            agent_name=agent.name,
            persona_name=persona.name,
            rehearsee=rehearsee_type,
            channel=run_channel,
            max_turns=turns,
            status=RehearsalStatus.RUNNING,
            transcript=transcript,
        )
        self.db.add(run)
        await self.db.commit()
        await self.db.refresh(run)

        if rehearsee_type == RehearseeType.HUMAN:
            # Wait for the human to drive the conversation.
            return run

        # AI rehearsee: simulate the full conversation, then score it.
        try:
            timezone = await get_workspace_timezone(workspace_id, self.db)
            system_prompt = await build_agent_system_prompt(self.db, agent, timezone=timezone)
            for _ in range(turns):
                agent_text = await generate_agent_reply(
                    client=client,
                    system_prompt=system_prompt,
                    transcript=transcript,
                    temperature=agent.temperature,
                )
                transcript.append({"role": "agent", "content": agent_text})
                prospect_text = await generate_prospect_reply(
                    client=client,
                    persona_prompt=persona.persona_prompt,
                    transcript=transcript,
                )
                transcript.append({"role": "prospect", "content": prospect_text})

            run.transcript = list(transcript)
            await self._apply_report(run, client, persona)
            run.status = RehearsalStatus.COMPLETED
            run.completed_at = datetime.now(UTC)
            await self._emit_completed_event(run)
        except Exception as exc:  # noqa: BLE001 - persist failure, never 500 silently
            logger.exception("rehearsal_run_failed", run_id=str(run.id))
            run.status = RehearsalStatus.FAILED
            run.error = str(exc)

        await self.db.commit()
        await self.db.refresh(run)
        return run

    async def advance_human_turn(
        self, run_id: uuid.UUID, workspace_id: uuid.UUID, message: str
    ) -> RehearsalRun:
        """Append a human rep's message and return the prospect's reply."""
        run = await self.get_run(run_id, workspace_id)
        if run.rehearsee != RehearseeType.HUMAN:
            raise ValidationError("Only human-rehearsee runs accept manual turns")
        if run.status != RehearsalStatus.RUNNING:
            raise ValidationError("This rehearsal is no longer running")
        text = (message or "").strip()
        if not text:
            raise ValidationError("Message cannot be empty")

        persona = await self.get_persona(run.persona_id, workspace_id) if run.persona_id else None
        if persona is None:
            raise ValidationError("Persona for this rehearsal no longer exists")

        client = await self._client(workspace_id)
        transcript = list(run.transcript or [])
        transcript.append({"role": "agent", "content": text})
        prospect_text = await generate_prospect_reply(
            client=client,
            persona_prompt=persona.persona_prompt,
            transcript=transcript,
        )
        transcript.append({"role": "prospect", "content": prospect_text})

        run.transcript = transcript
        await self.db.commit()
        await self.db.refresh(run)
        return run

    async def score_run(self, run_id: uuid.UUID, workspace_id: uuid.UUID) -> RehearsalRun:
        """Score a (typically human) rehearsal and mark it completed."""
        run = await self.get_run(run_id, workspace_id)
        if run.status == RehearsalStatus.COMPLETED:
            return run
        if not run.transcript:
            raise ValidationError("Nothing to score yet")

        persona = await self.get_persona(run.persona_id, workspace_id) if run.persona_id else None
        client = await self._client(workspace_id)
        try:
            await self._apply_report(run, client, persona)
            run.status = RehearsalStatus.COMPLETED
            run.completed_at = datetime.now(UTC)
            await self._emit_completed_event(run)
        except Exception as exc:  # noqa: BLE001
            logger.exception("rehearsal_score_failed", run_id=str(run.id))
            run.status = RehearsalStatus.FAILED
            run.error = str(exc)
        await self.db.commit()
        await self.db.refresh(run)
        return run

    async def _emit_completed_event(self, run: RehearsalRun) -> None:
        """Queue the ``roleplay_completed`` automation trigger for a scored run."""
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
        await self._notify_roleplay_completed(run)

    async def _notify_roleplay_completed(self, run: RehearsalRun) -> None:
        """Push + email workspace members about a completed rehearsal (best-effort)."""
        from app.services.notifications import notify_workspace_event

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

    async def _apply_report(
        self,
        run: RehearsalRun,
        client: AsyncOpenAI,
        persona: ProspectPersona | None,
    ) -> None:
        """Score the run's transcript and write report fields in place."""
        report = await score_rehearsal(
            client=client,
            transcript=list(run.transcript or []),
            persona_name=run.persona_name or (persona.name if persona else "Prospect"),
            objections=list(persona.objections) if persona else [],
            goal=persona.goal if persona else None,
        )
        run.overall_score = report.overall_score
        run.objection_coverage = report.objection_coverage
        run.booking_attempted = report.booking_attempted
        run.tone_score = report.tone_score
        run.strengths = report.strengths
        run.gaps = report.gaps
        run.suggestions = report.suggestions
        run.summary = report.summary
        run.scores = report.scores
