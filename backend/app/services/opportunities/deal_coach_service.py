"""AI Deal Coach.

Synthesizes the whole relationship behind an opportunity into a single
coaching card: deal health, the top risk, the single next-best action, and a
ready-to-approve drafted action. Also ranks at-risk deals for a list view.

Design notes:
- All reads are workspace-scoped.
- Per-call sentiment/objections are *reused* from ``CallOutcome.signals``
  (populated by the transcript-analysis worker) rather than recomputed.
- Deterministic signals (cadence, days-in-stage, sentiment trend) are computed
  in code; an LLM only synthesizes the narrative + draft on top of them.
- When OpenAI is not configured or the call fails, a deterministic heuristic
  produces the same structured card so the endpoint never 500s.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal

import structlog
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.crud import get_or_404
from app.models.call_outcome import CallOutcome
from app.models.contact import Contact
from app.models.conversation import Conversation, Message, MessageChannel, MessageDirection
from app.models.opportunity import Opportunity, opportunity_contact_table
from app.schemas.deal_coach import (
    AtRiskDeal,
    AtRiskDealsResponse,
    DealCoachCard,
    DealHealthStatus,
    DealSignals,
    DraftedAction,
    NextBestAction,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()

_LLM_MODEL = "gpt-4o-mini"
_MAX_AT_RISK = 100
_DRAFT_ACTION_TYPE = "deal_coach.follow_up"


@dataclass(slots=True)
class _RiskAssessment:
    """Output of the deterministic risk heuristic."""

    risk_score: int
    health: DealHealthStatus
    health_score: int
    top_risk: str
    risk_factors: list[str] = field(default_factory=list)


@dataclass(slots=True)
class _CardBody:
    """The narrative/draft portion of a coaching card (LLM or heuristic)."""

    deal_health: DealHealthStatus
    health_score: int
    health_summary: str
    top_risk: str
    risk_factors: list[str]
    next_best_action: NextBestAction
    drafted_action: DraftedAction


def _str_list(value: object) -> list[str]:
    """Coerce an untyped JSONB value into a list of non-empty strings."""
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


def _days_since(value: datetime | None, *, now: datetime) -> int | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return max(0, (now - value).days)


def _contact_recency_contribution(
    days_since_last_contact: int | None,
) -> tuple[int, str | None]:
    """Points + factor for how long since the deal was last touched."""
    if days_since_last_contact is None:
        return 25, "No recorded engagement yet"
    if days_since_last_contact >= 14:
        return 35, f"Champion silent {days_since_last_contact} days"
    if days_since_last_contact >= 7:
        return 22, f"No contact in {days_since_last_contact} days"
    if days_since_last_contact >= 3:
        return 10, f"Quiet for {days_since_last_contact} days"
    return 0, None


def _stage_contribution(days_in_stage: int | None) -> tuple[int, str | None]:
    if days_in_stage is None:
        return 0, None
    if days_in_stage >= 30:
        return 20, f"Stalled {days_in_stage} days in stage"
    if days_in_stage >= 14:
        return 10, f"{days_in_stage} days in current stage"
    return 0, None


def _sentiment_contribution(last_sentiment: str | None) -> tuple[int, str | None]:
    if last_sentiment == "negative":
        return 20, "Negative sentiment on last call"
    if last_sentiment == "neutral":
        return 5, None
    return 0, None


def _health_for_score(score: int) -> DealHealthStatus:
    if score >= 70:
        return "critical"
    if score >= 45:
        return "at_risk"
    if score >= 25:
        return "watch"
    return "healthy"


def assess_risk(
    *,
    days_since_last_contact: int | None,
    days_in_stage: int | None,
    engagement_score: int,
    lead_score: int,
    last_sentiment: str | None,
    awaiting_reply: bool,
    objections: list[str],
    expected_close_overdue: bool,
) -> _RiskAssessment:
    """Score deal risk 0-100 (higher = more at risk) from deterministic signals.

    Pure function so it can back both the single coaching card's fallback and
    the at-risk ranking without re-querying or calling an LLM.
    """
    contributions: list[tuple[int, str | None]] = [
        _contact_recency_contribution(days_since_last_contact),
        _stage_contribution(days_in_stage),
        _sentiment_contribution(last_sentiment),
    ]
    if awaiting_reply and (days_since_last_contact or 0) >= 3:
        contributions.append((10, "Awaiting their reply"))
    if objections:
        contributions.append((8, f"Open objection: {objections[0]}"))
    if engagement_score < 20:
        contributions.append((10, "Low engagement score"))
    if lead_score < 20:
        contributions.append((5, None))
    if expected_close_overdue:
        contributions.append((15, "Past expected close date"))

    score = max(0, min(100, sum(points for points, _ in contributions)))
    factors = [factor for _, factor in contributions if factor]
    top_risk = factors[0] if factors else "On track — no material risk detected"
    return _RiskAssessment(
        risk_score=score,
        health=_health_for_score(score),
        health_score=100 - score,
        top_risk=top_risk,
        risk_factors=factors,
    )


class DealCoachService:
    """Aggregate per-deal signals and produce coaching output."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.log = logger.bind(component="deal_coach_service")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def coach_opportunity(
        self,
        workspace_id: uuid.UUID,
        opportunity_id: uuid.UUID,
    ) -> DealCoachCard:
        """Build the full coaching card for one opportunity."""
        opportunity = await get_or_404(
            self.db,
            Opportunity,
            opportunity_id,
            workspace_id=workspace_id,
            options=[selectinload(Opportunity.stage)],
        )

        contact = await self._primary_contact(workspace_id, opportunity)
        signals, llm_context = await self._aggregate_signals(workspace_id, opportunity, contact)

        assessment = assess_risk(
            days_since_last_contact=signals.days_since_last_contact,
            days_in_stage=signals.days_in_stage,
            engagement_score=signals.engagement_score,
            lead_score=signals.lead_score,
            last_sentiment=signals.last_call_sentiment,
            awaiting_reply=signals.awaiting_reply,
            objections=signals.objections,
            expected_close_overdue=signals.expected_close_overdue,
        )

        contact_name = contact.full_name if contact else None
        card = await self._synthesize(
            workspace_id=workspace_id,
            opportunity=opportunity,
            contact_name=contact_name,
            signals=signals,
            assessment=assessment,
            llm_context=llm_context,
        )
        return card

    async def list_at_risk(
        self,
        workspace_id: uuid.UUID,
        *,
        limit: int = 25,
        min_risk_score: int = 25,
    ) -> AtRiskDealsResponse:
        """Rank open opportunities by deterministic risk score (most at-risk first)."""
        limit = max(1, min(limit, _MAX_AT_RISK))
        now = datetime.now(UTC)

        result = await self.db.execute(
            select(Opportunity)
            .where(Opportunity.workspace_id == workspace_id)
            .where(Opportunity.status == "open")
            .where(Opportunity.is_active.is_(True))
            .options(
                selectinload(Opportunity.stage),
                selectinload(Opportunity.primary_contact),
            )
        )
        opportunities = result.scalars().unique().all()

        ranked: list[AtRiskDeal] = []
        total_amount_at_risk = 0.0
        for opp in opportunities:
            contact = opp.primary_contact
            days_since = _days_since(contact.last_engaged_at if contact else None, now=now)
            days_in_stage = _days_since(opp.stage_changed_at, now=now)
            overdue = bool(
                opp.expected_close_date is not None and opp.expected_close_date < now.date()
            )
            assessment = assess_risk(
                days_since_last_contact=days_since,
                days_in_stage=days_in_stage,
                engagement_score=contact.engagement_score if contact else 0,
                lead_score=contact.lead_score if contact else 0,
                last_sentiment=None,
                awaiting_reply=False,
                objections=[],
                expected_close_overdue=overdue,
            )
            if assessment.risk_score < min_risk_score:
                continue

            amount = float(opp.amount) if opp.amount is not None else None
            amount_at_risk = (amount or 0.0) * (assessment.risk_score / 100.0)
            total_amount_at_risk += amount_at_risk
            ranked.append(
                AtRiskDeal(
                    opportunity_id=opp.id,
                    name=opp.name,
                    amount=amount,
                    currency=opp.currency,
                    primary_contact_id=opp.primary_contact_id,
                    contact_name=contact.full_name if contact else None,
                    stage_name=opp.stage.name if opp.stage else None,
                    deal_health=assessment.health,
                    health_score=assessment.health_score,
                    risk_score=assessment.risk_score,
                    top_risk=assessment.top_risk,
                    days_since_last_contact=days_since,
                    amount_at_risk=round(amount_at_risk, 2),
                )
            )

        ranked.sort(key=lambda d: (d.risk_score, d.amount or 0.0), reverse=True)
        trimmed = ranked[:limit]
        return AtRiskDealsResponse(
            items=trimmed,
            total=len(ranked),
            total_amount_at_risk=round(total_amount_at_risk, 2),
        )

    async def queue_drafted_action(
        self,
        workspace_id: uuid.UUID,
        opportunity_id: uuid.UUID,
        *,
        channel: str | None = None,
        body: str | None = None,
        description: str | None = None,
    ) -> tuple[str, uuid.UUID | None, str, str]:
        """Queue the coach's drafted action through the HITL approval gate.

        Returns ``(decision, pending_action_id, action_type, description)``.
        The drafted action is queued (not auto-executed) because the Deal Coach
        has no owning agent — ``require_approval_without_agent`` forces a
        PendingAction so a human always reviews it.
        """
        from app.services.approval.approval_gate_service import approval_gate_service

        card = await self.coach_opportunity(workspace_id, opportunity_id)
        draft = card.drafted_action

        final_channel = channel or draft.channel
        final_body = body if body is not None else draft.body
        final_description = description or draft.description

        action_payload: dict[str, Any] = {
            "opportunity_id": str(opportunity_id),
            "contact_id": card.primary_contact_id,
            "channel": final_channel,
            "body": final_body,
            "next_best_action": card.next_best_action.model_dump(mode="json"),
        }
        context: dict[str, Any] = {
            "source": "deal_coach",
            "opportunity_id": str(opportunity_id),
            "contact_id": card.primary_contact_id,
            "deal_health": card.deal_health,
            "top_risk": card.top_risk,
        }
        urgency = "high" if card.deal_health in ("at_risk", "critical") else "normal"

        decision, metadata = await approval_gate_service.check_and_execute_or_queue(
            db=self.db,
            agent_id=None,
            workspace_id=workspace_id,
            action_type=_DRAFT_ACTION_TYPE,
            action_payload=action_payload,
            description=final_description,
            context=context,
            urgency=urgency,
            require_approval_without_agent=True,
        )
        action_id: uuid.UUID | None = None
        if metadata and metadata.get("action_id"):
            action_id = uuid.UUID(str(metadata["action_id"]))
        return decision, action_id, _DRAFT_ACTION_TYPE, final_description

    # ------------------------------------------------------------------
    # Aggregation
    # ------------------------------------------------------------------

    async def _primary_contact(
        self,
        workspace_id: uuid.UUID,
        opportunity: Opportunity,
    ) -> Contact | None:
        """Resolve the deal's primary contact, scoped to the workspace."""
        contact_id = opportunity.primary_contact_id
        if contact_id is None:
            # Fall back to the first associated contact via the m2m table.
            assoc = await self.db.execute(
                select(opportunity_contact_table.c.contact_id)
                .where(opportunity_contact_table.c.opportunity_id == opportunity.id)
                .limit(1)
            )
            row = assoc.first()
            if row is None:
                return None
            contact_id = row[0]

        result = await self.db.execute(
            select(Contact).where(
                Contact.id == contact_id,
                Contact.workspace_id == workspace_id,
            )
        )
        return result.scalar_one_or_none()

    async def _aggregate_signals(
        self,
        workspace_id: uuid.UUID,
        opportunity: Opportunity,
        contact: Contact | None,
    ) -> tuple[DealSignals, dict[str, Any]]:
        """Aggregate calls (sentiment/objections), SMS cadence and scores."""
        now = datetime.now(UTC)
        stage_name = opportunity.stage.name if opportunity.stage else None

        signals = DealSignals(
            days_in_stage=_days_since(opportunity.stage_changed_at, now=now),
            lead_score=contact.lead_score if contact else 0,
            engagement_score=contact.engagement_score if contact else 0,
            stage_name=stage_name,
            probability=opportunity.probability,
            expected_close_overdue=bool(
                opportunity.expected_close_date is not None
                and opportunity.expected_close_date < now.date()
            ),
        )
        llm_context: dict[str, Any] = {
            "call_summaries": [],
            "recent_messages": [],
        }

        if contact is None:
            signals.days_since_last_contact = None
            return signals, llm_context

        signals.days_since_last_contact = _days_since(contact.last_engaged_at, now=now)

        # Pull qualification objections/next-steps captured on the contact.
        quals = contact.qualification_signals or {}
        objections = list(quals.get("objections") or [])
        next_step = quals.get("next_steps")

        # Load this contact's conversations + messages (workspace-scoped).
        conv_result = await self.db.execute(
            select(Conversation)
            .where(
                Conversation.workspace_id == workspace_id,
                Conversation.contact_id == contact.id,
            )
            .options(selectinload(Conversation.messages))
        )
        conversations = conv_result.scalars().unique().all()

        messages: list[Message] = []
        for conv in conversations:
            messages.extend(conv.messages)
        messages.sort(key=lambda m: m.created_at)

        call_message_ids = self._summarize_messages(messages, signals, llm_context)
        sentiments = await self._apply_call_outcomes(
            call_message_ids, objections, signals, llm_context
        )

        if next_step:
            if isinstance(next_step, str):
                signals.open_next_steps.insert(0, next_step)
            elif isinstance(next_step, list):
                signals.open_next_steps = [
                    *[s for s in next_step if isinstance(s, str)],
                    *signals.open_next_steps,
                ]

        signals.objections = objections[:5]
        signals.open_next_steps = signals.open_next_steps[:5]

        if sentiments:
            signals.last_call_sentiment = sentiments[-1][1]
            signals.sentiment_trend = _sentiment_trend(sentiments)

        return signals, llm_context

    @staticmethod
    def _summarize_messages(
        messages: list[Message],
        signals: DealSignals,
        llm_context: dict[str, Any],
    ) -> list[uuid.UUID]:
        """Count channels, derive awaiting-reply, collect call message ids."""
        last_inbound: datetime | None = None
        last_outbound: datetime | None = None
        call_message_ids: list[uuid.UUID] = []
        for msg in messages:
            if msg.channel == MessageChannel.VOICE:
                signals.call_count += 1
                call_message_ids.append(msg.id)
            elif msg.channel in (MessageChannel.SMS, MessageChannel.IMESSAGE):
                signals.sms_count += 1
            if msg.direction == MessageDirection.INBOUND:
                last_inbound = msg.created_at
            elif msg.direction == MessageDirection.OUTBOUND:
                last_outbound = msg.created_at

        signals.awaiting_reply = bool(
            last_outbound is not None and (last_inbound is None or last_outbound > last_inbound)
        )

        # Recent message previews (latest 6) for the LLM, redaction-light.
        for msg in messages[-6:]:
            llm_context["recent_messages"].append(
                {
                    "direction": str(msg.direction),
                    "channel": str(msg.channel),
                    "preview": (msg.body or "")[:240],
                    "at": msg.created_at.isoformat(),
                }
            )
        return call_message_ids

    async def _apply_call_outcomes(
        self,
        call_message_ids: list[uuid.UUID],
        objections: list[str],
        signals: DealSignals,
        llm_context: dict[str, Any],
    ) -> list[tuple[datetime, str]]:
        """Reuse per-call sentiment/objections from ``CallOutcome.signals``."""
        sentiments: list[tuple[datetime, str]] = []
        if not call_message_ids:
            return sentiments

        outcome_result = await self.db.execute(
            select(CallOutcome).where(CallOutcome.message_id.in_(call_message_ids))
        )
        outcomes = sorted(outcome_result.scalars().all(), key=lambda o: o.created_at)
        for outcome in outcomes:
            osignals = outcome.signals or {}
            sentiment = osignals.get("sentiment")
            if isinstance(sentiment, str):
                sentiments.append((outcome.created_at, sentiment))
            for obj in _str_list(osignals.get("objections")):
                if obj not in objections:
                    objections.append(obj)
            summary = osignals.get("summary")
            if isinstance(summary, str) and summary:
                llm_context["call_summaries"].append(
                    {
                        "at": outcome.created_at.isoformat(),
                        "sentiment": sentiment,
                        "summary": summary[:280],
                    }
                )
            signals.open_next_steps.extend(_str_list(osignals.get("next_steps")))
        return sentiments

    # ------------------------------------------------------------------
    # Synthesis (LLM with heuristic fallback)
    # ------------------------------------------------------------------

    async def _synthesize(
        self,
        *,
        workspace_id: uuid.UUID,
        opportunity: Opportunity,
        contact_name: str | None,
        signals: DealSignals,
        assessment: _RiskAssessment,
        llm_context: dict[str, Any],
    ) -> DealCoachCard:
        amount = float(opportunity.amount) if opportunity.amount is not None else None

        llm = await self._try_llm(
            opportunity=opportunity,
            contact_name=contact_name,
            signals=signals,
            assessment=assessment,
            llm_context=llm_context,
        )
        if llm is not None:
            body, generated_by = llm, "llm"
        else:
            body, generated_by = (
                _heuristic_card(
                    contact_name=contact_name,
                    signals=signals,
                    assessment=assessment,
                ),
                "heuristic",
            )

        return DealCoachCard(
            opportunity_id=opportunity.id,
            workspace_id=workspace_id,
            name=opportunity.name,
            amount=amount,
            currency=opportunity.currency,
            primary_contact_id=opportunity.primary_contact_id,
            contact_name=contact_name,
            deal_health=body.deal_health,
            health_score=body.health_score,
            health_summary=body.health_summary,
            top_risk=body.top_risk,
            risk_factors=body.risk_factors,
            next_best_action=body.next_best_action,
            drafted_action=body.drafted_action,
            signals=signals,
            generated_by=generated_by,  # type: ignore[arg-type]
            generated_at=datetime.now(UTC),
        )

    async def _try_llm(
        self,
        *,
        opportunity: Opportunity,
        contact_name: str | None,
        signals: DealSignals,
        assessment: _RiskAssessment,
        llm_context: dict[str, Any],
    ) -> _CardBody | None:
        """Call the LLM for narrative synthesis. Returns None on any failure."""
        from app.services.ai.openai_credentials import (
            create_openai_client,
            is_openai_configured,
        )

        if not is_openai_configured():
            return None

        payload = {
            "deal": {
                "name": opportunity.name,
                "amount": float(opportunity.amount) if opportunity.amount is not None else None,
                "currency": opportunity.currency,
                "stage": signals.stage_name,
                "probability": signals.probability,
                "contact_name": contact_name,
            },
            "signals": signals.model_dump(mode="json"),
            "heuristic_assessment": {
                "risk_score": assessment.risk_score,
                "health": assessment.health,
                "top_risk": assessment.top_risk,
                "risk_factors": assessment.risk_factors,
            },
            "call_summaries": llm_context.get("call_summaries", []),
            "recent_messages": llm_context.get("recent_messages", []),
        }

        try:
            client = create_openai_client()
            response = await client.chat.completions.create(
                model=_LLM_MODEL,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": _USER_PROMPT.format(payload=json.dumps(payload, default=str)),
                    },
                ],
                response_format={"type": "json_object"},
                temperature=0.3,
            )
            raw = json.loads(response.choices[0].message.content or "{}")
            return _parse_llm_card(raw, signals=signals, assessment=assessment)
        except Exception:
            self.log.warning("deal_coach_llm_failed", opportunity_id=str(opportunity.id))
            return None


def _sentiment_trend(
    sentiments: list[tuple[datetime, str]],
) -> Literal["improving", "declining", "flat", "unknown"]:
    """Classify call-sentiment trajectory from ordered (time, sentiment) pairs."""
    if len(sentiments) < 2:
        return "unknown"
    rank = {"negative": -1, "neutral": 0, "positive": 1}
    first = rank.get(sentiments[0][1], 0)
    last = rank.get(sentiments[-1][1], 0)
    if last > first:
        return "improving"
    if last < first:
        return "declining"
    return "flat"


def _build_drafted_action(
    *,
    contact_name: str | None,
    channel: str,
    body: str,
    description: str,
) -> DraftedAction:
    safe_channel = channel if channel in ("sms", "call", "email", "offer", "task") else "sms"
    return DraftedAction(
        action_type=_DRAFT_ACTION_TYPE,
        channel=safe_channel,  # type: ignore[arg-type]
        description=description,
        body=body,
        payload={"channel": safe_channel, "body": body},
    )


def _heuristic_card(
    *,
    contact_name: str | None,
    signals: DealSignals,
    assessment: _RiskAssessment,
) -> _CardBody:
    """Deterministic coaching card used when no LLM is available."""
    name = contact_name or "the contact"
    first_name = name.split(" ")[0]

    if signals.last_call_sentiment == "negative" or signals.objections:
        objection = signals.objections[0] if signals.objections else "their concern"
        action = NextBestAction(
            title="Send value recap, then book a call",
            rationale=(
                f"Last interaction surfaced an objection ({objection}). Address it directly "
                "with proof/financing, then lock a live conversation."
            ),
            channel="offer",
            timing="Today",
        )
        body = (
            f"Hi {first_name}, following up on {objection}. I put together options that should "
            "help — open to a quick call this week to walk through them?"
        )
        description = f"Drafted follow-up to {name} addressing '{objection}'."
    elif signals.awaiting_reply and (signals.days_since_last_contact or 0) >= 3:
        action = NextBestAction(
            title="Re-engage the silent champion",
            rationale=(
                f"You've been waiting {signals.days_since_last_contact} days on a reply. "
                "A light, value-led nudge re-opens the thread."
            ),
            channel="sms",
            timing="Today",
        )
        body = (
            f"Hi {first_name}, checking in — still happy to help you move forward. "
            "Want me to send next steps?"
        )
        description = f"Drafted re-engagement SMS to {name}."
    elif signals.days_in_stage is not None and signals.days_in_stage >= 14:
        action = NextBestAction(
            title="Advance the stalled deal",
            rationale=(
                f"This deal has sat {signals.days_in_stage} days in "
                f"{signals.stage_name or 'its current stage'}. Propose a concrete next step."
            ),
            channel="call",
            timing="Tomorrow AM",
        )
        body = (
            f"Hi {first_name}, I'd love to get you to the finish line. "
            "Do you have 10 minutes tomorrow morning to align on next steps?"
        )
        description = f"Drafted call-to-book outreach to {name}."
    else:
        action = NextBestAction(
            title="Keep momentum with a check-in",
            rationale="Deal looks healthy — a timely touch keeps it moving.",
            channel="sms",
            timing="This week",
        )
        body = f"Hi {first_name}, just checking in — anything I can do to help you decide?"
        description = f"Drafted check-in SMS to {name}."

    summary = (
        f"{assessment.health.replace('_', ' ').title()} "
        f"(score {assessment.health_score}/100). {assessment.top_risk}."
    )
    return _CardBody(
        deal_health=assessment.health,
        health_score=assessment.health_score,
        health_summary=summary,
        top_risk=assessment.top_risk,
        risk_factors=assessment.risk_factors,
        next_best_action=action,
        drafted_action=_build_drafted_action(
            contact_name=contact_name,
            channel=action.channel,
            body=body,
            description=description,
        ),
    )


def _parse_llm_card(
    raw: dict[str, Any],
    *,
    signals: DealSignals,
    assessment: _RiskAssessment,
) -> _CardBody:
    """Validate/normalize the LLM JSON into card fields, backfilling from heuristic."""
    valid_health = {"healthy", "watch", "at_risk", "critical"}
    valid_channels = {"sms", "call", "email", "offer", "task"}

    health = raw.get("deal_health")
    if health not in valid_health:
        health = assessment.health

    try:
        health_score = int(raw.get("health_score", assessment.health_score))
    except (TypeError, ValueError):
        health_score = assessment.health_score
    health_score = max(0, min(100, health_score))

    health_status: DealHealthStatus = health

    nba_raw = raw.get("next_best_action") or {}
    channel = nba_raw.get("channel")
    if channel not in valid_channels:
        channel = "sms"
    action = NextBestAction(
        title=str(nba_raw.get("title") or "Follow up")[:160],
        rationale=str(nba_raw.get("rationale") or assessment.top_risk)[:600],
        channel=channel,  # type: ignore[arg-type]
        timing=str(nba_raw.get("timing") or "Today")[:60],
    )

    draft_raw = raw.get("drafted_action") or {}
    draft_channel = draft_raw.get("channel")
    if draft_channel not in valid_channels:
        draft_channel = channel
    body = str(draft_raw.get("body") or "").strip()
    if not body:
        # No usable draft body — fall back to heuristic draft entirely.
        body = _heuristic_card(
            contact_name=None, signals=signals, assessment=assessment
        ).drafted_action.body
    description = str(draft_raw.get("description") or action.title)[:300]

    risk_factors = [str(f) for f in (raw.get("risk_factors") or assessment.risk_factors) if f][:6]

    return _CardBody(
        deal_health=health_status,
        health_score=health_score,
        health_summary=str(raw.get("health_summary") or assessment.top_risk)[:600],
        top_risk=str(raw.get("top_risk") or assessment.top_risk)[:300],
        risk_factors=risk_factors,
        next_best_action=action,
        drafted_action=_build_drafted_action(
            contact_name=None,
            channel=draft_channel,
            body=body[:1000],
            description=description,
        ),
    )


_SYSTEM_PROMPT = (
    "You are an elite B2B sales deal coach (think Gong/Clari deal boards). "
    "You receive pre-computed signals for a single sales opportunity and must "
    "return ONE concise coaching card as strict JSON. Be specific and "
    "actionable. Never invent facts not supported by the signals."
)

_USER_PROMPT = (
    "Synthesize this opportunity into a coaching card. Use the deterministic "
    "signals and heuristic_assessment as ground truth; do not contradict the "
    "numeric signals.\n\n"
    "Return a JSON object with exactly these fields:\n"
    '- "deal_health": one of "healthy", "watch", "at_risk", "critical"\n'
    '- "health_score": integer 0-100 (higher = healthier)\n'
    '- "health_summary": one sentence\n'
    '- "top_risk": the single biggest risk, concrete (e.g. "champion silent 10 days")\n'
    '- "risk_factors": array of short strings\n'
    '- "next_best_action": object with "title", "rationale", '
    '"channel" (one of sms|call|email|offer|task), "timing"\n'
    '- "drafted_action": object with "channel", "description", and "body" '
    "(the actual message/script to send, personalized, <= 60 words)\n\n"
    "DEAL DATA:\n{payload}"
)
