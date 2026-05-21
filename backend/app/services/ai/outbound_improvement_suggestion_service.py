"""Automated outbound campaign improvement suggestions.

Analyzes recent completed campaign reports and queues follow-up campaign
recommendations as PendingAction rows for human approval.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Literal

import structlog
from openai import AsyncOpenAI
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.campaign import Campaign, CampaignStatus
from app.models.campaign_report import CampaignReport
from app.models.pending_action import PendingAction
from app.services.ai.openai_credentials import create_openai_client
from app.services.approval.approval_gate_service import ApprovalGateService

logger = structlog.get_logger()

OUTBOUND_FOLLOW_UP_ACTION_TYPE = "outbound_improvement.follow_up_campaign"
OUTBOUND_SUGGESTION_SOURCE = "outbound_improvement_suggestions"
MIN_SOURCE_REPORTS = 1
MAX_SUGGESTIONS_PER_WORKSPACE_PERIOD = 1

PeriodName = Literal["daily", "weekly"]


@dataclass(slots=True, frozen=True)
class PeriodWindow:
    """UTC period covered by one suggestion generation run."""

    name: PeriodName
    starts_at: datetime
    ends_at: datetime

    @property
    def label(self) -> str:
        return f"{self.name}:{self.starts_at.date().isoformat()}:{self.ends_at.date().isoformat()}"

    def to_payload(self) -> dict[str, str]:
        return {
            "name": self.name,
            "starts_at": self.starts_at.isoformat(),
            "ends_at": self.ends_at.isoformat(),
            "label": self.label,
        }


@dataclass(slots=True, frozen=True)
class CampaignEvidence:
    """Source campaign/report evidence used to synthesize a recommendation."""

    campaign_id: uuid.UUID
    report_id: uuid.UUID
    campaign_name: str
    campaign_type: str
    responder_agent_id: uuid.UUID | None
    initial_message: str | None
    sms_fallback_template: str | None
    metrics: dict[str, Any]
    recommendations: list[dict[str, Any]]
    segment_analysis: list[dict[str, Any]]
    timing_analysis: dict[str, Any]
    prompt_performance: list[dict[str, Any]]
    key_findings: list[dict[str, Any]]
    what_worked: list[dict[str, Any]]

    @property
    def source_agent_id(self) -> uuid.UUID | None:
        return self.responder_agent_id


@dataclass(slots=True, frozen=True)
class BestPerformerSummary:
    """Deterministic best-performing outbound dimensions."""

    best_campaign: dict[str, Any] | None
    best_segment: dict[str, Any] | None
    best_angle: dict[str, Any] | None
    best_message: dict[str, Any] | None
    best_responder_agent: dict[str, Any] | None
    best_timing: dict[str, Any] | None
    best_prompt: dict[str, Any] | None


@dataclass(slots=True, frozen=True)
class OutboundRecommendation:
    """Generated follow-up campaign recommendation."""

    title: str
    rationale: str
    target_segment: str | None
    angle: str | None
    message: str | None
    responder_agent_id: uuid.UUID | None
    confidence: float
    expected_outcome: str | None


def period_window(period: PeriodName, today: date | None = None) -> PeriodWindow:
    """Return the UTC window for a daily or weekly run."""
    anchor = today or datetime.now(UTC).date()
    end_day = anchor
    start_day = anchor - timedelta(days=1 if period == "daily" else 7)
    return PeriodWindow(
        name=period,
        starts_at=datetime.combine(start_day, time.min, tzinfo=UTC),
        ends_at=datetime.combine(end_day, time.min, tzinfo=UTC),
    )


def safe_rate(numerator: int | float | None, denominator: int | float | None) -> float:
    """Calculate a bounded rate, returning 0 when the denominator is missing."""
    if denominator is None or denominator <= 0 or numerator is None:
        return 0.0
    return round(float(numerator) / float(denominator), 4)


def normalize_json_list(value: Any) -> list[dict[str, Any]]:
    """Coerce loose JSON report fields to a list of dictionaries."""
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def normalize_json_dict(value: Any) -> dict[str, Any]:
    """Coerce loose JSON report fields to a dictionary."""
    return value if isinstance(value, dict) else {}


def number_from_mapping(data: dict[str, Any], keys: tuple[str, ...]) -> float:
    """Extract the first numeric value for a list of possible keys."""
    for key in keys:
        value = data.get(key)
        if isinstance(value, int | float):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value.rstrip("%"))
            except ValueError:
                continue
    return 0.0


def text_from_mapping(data: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    """Extract the first non-empty string for a list of possible keys."""
    for key in keys:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def campaign_performance_score(metrics: dict[str, Any]) -> float:
    """Score campaign performance by booked, qualified, and reply rates."""
    total_contacts = number_from_mapping(metrics, ("total_contacts", "contacts", "sent"))
    sent = number_from_mapping(metrics, ("messages_sent", "calls_attempted", "total_contacts"))
    booked = number_from_mapping(metrics, ("appointments_booked", "booked"))
    qualified = number_from_mapping(metrics, ("contacts_qualified", "leads_qualified", "qualified"))
    replies = number_from_mapping(metrics, ("replies_received", "replies"))
    opt_outs = number_from_mapping(metrics, ("contacts_opted_out", "opt_outs", "unsubscribed"))

    positive_score = (
        safe_rate(booked, total_contacts) * 4.0
        + safe_rate(qualified, total_contacts) * 2.5
        + safe_rate(replies, sent) * 1.5
    )
    penalty = safe_rate(opt_outs, total_contacts)
    return round(positive_score - penalty, 4)


def extract_best_campaign(evidence: list[CampaignEvidence]) -> dict[str, Any] | None:
    """Find the highest-scoring source campaign."""
    if not evidence:
        return None
    ranked = sorted(
        evidence,
        key=lambda item: (campaign_performance_score(item.metrics), item.campaign_name),
        reverse=True,
    )
    best = ranked[0]
    return {
        "campaign_id": str(best.campaign_id),
        "report_id": str(best.report_id),
        "name": best.campaign_name,
        "campaign_type": best.campaign_type,
        "score": campaign_performance_score(best.metrics),
        "metrics": best.metrics,
    }


def extract_best_segment(evidence: list[CampaignEvidence]) -> dict[str, Any] | None:
    """Infer the best segment from campaign report segment_analysis fields."""
    candidates: list[dict[str, Any]] = []
    for item in evidence:
        for segment in item.segment_analysis:
            label = text_from_mapping(segment, ("segment", "name", "label", "audience"))
            score = number_from_mapping(
                segment,
                (
                    "conversion_rate",
                    "appointment_rate",
                    "qualification_rate",
                    "response_rate",
                    "success_rate",
                    "score",
                ),
            )
            candidates.append(
                {
                    "segment": label or "Unspecified segment",
                    "score": score,
                    "source_campaign_id": str(item.campaign_id),
                    "evidence": segment,
                }
            )
    if not candidates:
        return None
    return max(candidates, key=lambda item: (item["score"], item["segment"]))


def extract_best_angle(evidence: list[CampaignEvidence]) -> dict[str, Any] | None:
    """Infer the strongest angle from what_worked, key_findings, and recommendations."""
    candidates: list[dict[str, Any]] = []
    fields: tuple[tuple[str, list[dict[str, Any]]], ...]
    for item in evidence:
        fields = (
            ("what_worked", item.what_worked),
            ("key_findings", item.key_findings),
            ("recommendations", item.recommendations),
        )
        for source, entries in fields:
            for entry in entries:
                angle = text_from_mapping(
                    entry,
                    ("angle", "theme", "finding", "title", "recommendation", "summary", "message"),
                )
                if angle is None:
                    continue
                candidates.append(
                    {
                        "angle": angle,
                        "source": source,
                        "source_campaign_id": str(item.campaign_id),
                        "evidence": entry,
                    }
                )
    if not candidates:
        return None
    return sorted(candidates, key=lambda item: (item["source"], item["angle"]))[0]


def extract_best_message(evidence: list[CampaignEvidence]) -> dict[str, Any] | None:
    """Choose the highest-scoring available initial or fallback message."""
    candidates: list[dict[str, Any]] = []
    for item in evidence:
        score = campaign_performance_score(item.metrics)
        for source, message in (
            ("initial_message", item.initial_message),
            ("sms_fallback_template", item.sms_fallback_template),
        ):
            if message and message.strip():
                candidates.append(
                    {
                        "message": message.strip(),
                        "source": source,
                        "score": score,
                        "source_campaign_id": str(item.campaign_id),
                    }
                )
    if not candidates:
        return None
    return max(candidates, key=lambda item: (item["score"], item["message"]))


def extract_best_responder_agent(evidence: list[CampaignEvidence]) -> dict[str, Any] | None:
    """Find the agent associated with the strongest source campaign."""
    agent_scores: dict[uuid.UUID, float] = {}
    campaign_ids: dict[uuid.UUID, list[str]] = {}
    for item in evidence:
        if item.source_agent_id is None:
            continue
        agent_scores[item.source_agent_id] = agent_scores.get(item.source_agent_id, 0.0) + (
            campaign_performance_score(item.metrics) or 0.001
        )
        campaign_ids.setdefault(item.source_agent_id, []).append(str(item.campaign_id))
    if not agent_scores:
        return None
    agent_id = max(agent_scores, key=lambda key: (agent_scores[key], str(key)))
    return {
        "agent_id": str(agent_id),
        "score": round(agent_scores[agent_id], 4),
        "source_campaign_ids": sorted(campaign_ids[agent_id]),
    }


def extract_best_timing(evidence: list[CampaignEvidence]) -> dict[str, Any] | None:
    """Infer timing recommendations from report timing_analysis fields."""
    candidates: list[dict[str, Any]] = []
    for item in evidence:
        timing = item.timing_analysis
        if not timing:
            continue
        label = text_from_mapping(
            timing,
            ("best_time", "best_day", "recommended_time", "recommended_window", "summary"),
        )
        score = number_from_mapping(timing, ("response_rate", "success_rate", "score"))
        candidates.append(
            {
                "timing": label or "Use timing from source report",
                "score": score,
                "source_campaign_id": str(item.campaign_id),
                "evidence": timing,
            }
        )
    if not candidates:
        return None
    return max(candidates, key=lambda item: (item["score"], item["timing"]))


def extract_best_prompt(evidence: list[CampaignEvidence]) -> dict[str, Any] | None:
    """Infer best prompt version from report prompt_performance fields."""
    candidates: list[dict[str, Any]] = []
    for item in evidence:
        for prompt in item.prompt_performance:
            version_id = text_from_mapping(prompt, ("version_id", "prompt_version_id", "id"))
            score = number_from_mapping(
                prompt,
                ("success_rate", "booking_rate", "qualification_rate", "conversion_rate", "score"),
            )
            candidates.append(
                {
                    "prompt_version_id": version_id,
                    "score": score,
                    "source_campaign_id": str(item.campaign_id),
                    "evidence": prompt,
                }
            )
    if not candidates:
        return None
    return max(candidates, key=lambda item: (item["score"], item.get("prompt_version_id") or ""))


def summarize_best_performers(evidence: list[CampaignEvidence]) -> BestPerformerSummary:
    """Build deterministic best performer summary from available evidence."""
    return BestPerformerSummary(
        best_campaign=extract_best_campaign(evidence),
        best_segment=extract_best_segment(evidence),
        best_angle=extract_best_angle(evidence),
        best_message=extract_best_message(evidence),
        best_responder_agent=extract_best_responder_agent(evidence),
        best_timing=extract_best_timing(evidence),
        best_prompt=extract_best_prompt(evidence),
    )


def parse_llm_recommendation(
    raw_text: str,
    fallback: OutboundRecommendation,
) -> OutboundRecommendation:
    """Parse an LLM JSON recommendation, falling back safely on malformed output."""
    try:
        parsed = json.loads(raw_text or "{}")
    except json.JSONDecodeError:
        return fallback
    if not isinstance(parsed, dict):
        return fallback

    responder_agent_id = fallback.responder_agent_id
    raw_agent_id = parsed.get("responder_agent_id")
    if isinstance(raw_agent_id, str) and raw_agent_id:
        try:
            responder_agent_id = uuid.UUID(raw_agent_id)
        except ValueError:
            responder_agent_id = fallback.responder_agent_id

    confidence = parsed.get("confidence", fallback.confidence)
    if not isinstance(confidence, int | float):
        confidence = fallback.confidence

    return OutboundRecommendation(
        title=str(parsed.get("title") or fallback.title),
        rationale=str(parsed.get("rationale") or fallback.rationale),
        target_segment=_optional_string(parsed.get("target_segment"), fallback.target_segment),
        angle=_optional_string(parsed.get("angle"), fallback.angle),
        message=_optional_string(parsed.get("message"), fallback.message),
        responder_agent_id=responder_agent_id,
        confidence=max(0.0, min(float(confidence), 1.0)),
        expected_outcome=_optional_string(
            parsed.get("expected_outcome"),
            fallback.expected_outcome,
        ),
    )


def build_dedupe_key(
    workspace_id: uuid.UUID,
    window: PeriodWindow,
    report_ids: list[uuid.UUID],
) -> str:
    """Build a stable dedupe key for a workspace/period/source report set."""
    source = {
        "workspace_id": str(workspace_id),
        "period": window.label,
        "report_ids": sorted(str(report_id) for report_id in report_ids),
    }
    encoded = json.dumps(source, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:24]
    return f"{OUTBOUND_SUGGESTION_SOURCE}:{digest}"


def build_pending_action_payload(
    window: PeriodWindow,
    evidence: list[CampaignEvidence],
    summary: BestPerformerSummary,
    recommendation: OutboundRecommendation,
) -> dict[str, Any]:
    """Build the reviewable, execution-safe PendingAction payload."""
    return {
        "period": window.to_payload(),
        "source_campaign_ids": [str(item.campaign_id) for item in evidence],
        "source_report_ids": [str(item.report_id) for item in evidence],
        "best_segment": summary.best_segment,
        "best_angle": summary.best_angle,
        "best_message": summary.best_message,
        "best_responder_agent": summary.best_responder_agent,
        "recommended_campaign": {
            "title": recommendation.title,
            "rationale": recommendation.rationale,
            "target_segment": recommendation.target_segment,
            "angle": recommendation.angle,
            "message": recommendation.message,
            "responder_agent_id": str(recommendation.responder_agent_id)
            if recommendation.responder_agent_id
            else None,
            "expected_outcome": recommendation.expected_outcome,
        },
        "evidence": {
            "best_campaign": summary.best_campaign,
            "best_timing": summary.best_timing,
            "best_prompt": summary.best_prompt,
            "source_campaigns": [
                {
                    "campaign_id": str(item.campaign_id),
                    "report_id": str(item.report_id),
                    "name": item.campaign_name,
                    "campaign_type": item.campaign_type,
                    "metrics": item.metrics,
                    "recommendations": item.recommendations[:3],
                    "what_worked": item.what_worked[:3],
                }
                for item in evidence
            ],
        },
        "confidence": recommendation.confidence,
    }


def _optional_string(value: Any, fallback: str | None) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return fallback


def _fallback_recommendation(summary: BestPerformerSummary) -> OutboundRecommendation:
    best_segment = summary.best_segment or {}
    best_angle = summary.best_angle or {}
    best_message = summary.best_message or {}
    best_agent = summary.best_responder_agent or {}

    responder_agent_id: uuid.UUID | None = None
    raw_agent_id = best_agent.get("agent_id")
    if isinstance(raw_agent_id, str) and raw_agent_id:
        try:
            responder_agent_id = uuid.UUID(raw_agent_id)
        except ValueError:
            responder_agent_id = None

    target_segment = text_from_mapping(best_segment, ("segment",))
    angle = text_from_mapping(best_angle, ("angle",))
    message = text_from_mapping(best_message, ("message",))

    return OutboundRecommendation(
        title="Run a follow-up campaign based on recent outbound winners",
        rationale=(
            "Recent completed campaign reports contain enough evidence to replicate the strongest "
            "segment, message, and responder patterns."
        ),
        target_segment=target_segment,
        angle=angle,
        message=message,
        responder_agent_id=responder_agent_id,
        confidence=0.65,
        expected_outcome=(
            "Improve reply, qualification, or booking rates by reusing the strongest observed "
            "outbound pattern."
        ),
    )


class OutboundImprovementSuggestionService:
    """Generate outbound follow-up campaign suggestions for approval."""

    def __init__(self, approval_gate: ApprovalGateService | None = None) -> None:
        self._client: AsyncOpenAI | None = None
        self._approval_gate = approval_gate or ApprovalGateService()

    def _get_client(self) -> AsyncOpenAI:
        if self._client is None:
            self._client = create_openai_client()
        return self._client

    async def generate_for_workspace_period(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID,
        period: PeriodName,
        today: date | None = None,
    ) -> list[PendingAction]:
        """Generate pending outbound suggestions for one workspace and period."""
        window = period_window(period, today)
        log = logger.bind(
            workspace_id=str(workspace_id),
            period=window.label,
            source=OUTBOUND_SUGGESTION_SOURCE,
        )
        evidence = await self.load_evidence(db, workspace_id, window)
        if len(evidence) < MIN_SOURCE_REPORTS:
            log.debug(
                "Skipping outbound suggestions; not enough completed reports",
                count=len(evidence),
            )
            return []

        report_ids = [item.report_id for item in evidence]
        dedupe_key = build_dedupe_key(workspace_id, window, report_ids)
        if await self.pending_action_exists(db, workspace_id, dedupe_key):
            log.debug(
                "Skipping outbound suggestions; dedupe key already exists",
                dedupe_key=dedupe_key,
            )
            return []

        summary = summarize_best_performers(evidence)
        recommendation = await self.synthesize_recommendation(evidence, summary)
        payload = build_pending_action_payload(window, evidence, summary, recommendation)
        context = {
            "source": OUTBOUND_SUGGESTION_SOURCE,
            "period": window.to_payload(),
            "source_campaign_ids": [str(item.campaign_id) for item in evidence],
            "source_report_ids": [str(item.report_id) for item in evidence],
            "dedupe_key": dedupe_key,
        }
        description = f"Review follow-up outbound campaign suggestion: {recommendation.title}"

        decision, metadata = await self._approval_gate.check_and_execute_or_queue(
            db=db,
            agent_id=recommendation.responder_agent_id,
            workspace_id=workspace_id,
            action_type=OUTBOUND_FOLLOW_UP_ACTION_TYPE,
            action_payload=payload,
            description=description,
            context=context,
            urgency="normal",
            require_approval_without_agent=True,
        )
        if decision != "pending" or not metadata:
            log.info("Outbound suggestion was not queued", decision=decision)
            return []

        action_id = uuid.UUID(str(metadata["action_id"]))
        action_result = await db.execute(select(PendingAction).where(PendingAction.id == action_id))
        action = action_result.scalar_one()
        await self.mark_reports_with_suggestion(db, report_ids, action.id)
        log.info("Queued outbound improvement suggestion", action_id=str(action.id))
        return [action]

    async def generate_for_period(
        self,
        db: AsyncSession,
        period: PeriodName,
        today: date | None = None,
    ) -> list[PendingAction]:
        """Generate outbound suggestions for all workspaces with evidence in the period."""
        window = period_window(period, today)
        workspace_result = await db.execute(self.workspace_evidence_query(window))
        workspace_ids = [row[0] for row in workspace_result.all()]
        actions: list[PendingAction] = []
        for workspace_id in workspace_ids:
            workspace_actions = await self.generate_for_workspace_period(
                db,
                workspace_id,
                period,
                today,
            )
            actions.extend(workspace_actions[:MAX_SUGGESTIONS_PER_WORKSPACE_PERIOD])
        return actions

    def workspace_evidence_query(self, window: PeriodWindow) -> Select[tuple[uuid.UUID]]:
        """Build the query for workspaces with completed campaign reports in a window."""
        return (
            select(CampaignReport.workspace_id)
            .join(Campaign, Campaign.id == CampaignReport.campaign_id)
            .where(
                CampaignReport.status == "completed",
                Campaign.status == CampaignStatus.COMPLETED,
                Campaign.completed_at >= window.starts_at,
                Campaign.completed_at < window.ends_at,
            )
            .distinct()
        )

    async def load_evidence(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID,
        window: PeriodWindow,
    ) -> list[CampaignEvidence]:
        """Load completed campaign report evidence for a workspace and window."""
        result = await db.execute(
            select(Campaign, CampaignReport)
            .join(CampaignReport, CampaignReport.campaign_id == Campaign.id)
            .where(
                Campaign.workspace_id == workspace_id,
                CampaignReport.workspace_id == workspace_id,
                Campaign.status == CampaignStatus.COMPLETED,
                CampaignReport.status == "completed",
                Campaign.completed_at >= window.starts_at,
                Campaign.completed_at < window.ends_at,
            )
            .order_by(Campaign.completed_at.desc(), Campaign.name.asc())
            .limit(25)
        )
        evidence: list[CampaignEvidence] = []
        for campaign, report in result.all():
            agent_id = (
                campaign.voice_agent_id or campaign.sms_fallback_agent_id or campaign.agent_id
            )
            evidence.append(
                CampaignEvidence(
                    campaign_id=campaign.id,
                    report_id=report.id,
                    campaign_name=campaign.name,
                    campaign_type=str(campaign.campaign_type),
                    responder_agent_id=agent_id,
                    initial_message=campaign.initial_message,
                    sms_fallback_template=campaign.sms_fallback_template,
                    metrics=normalize_json_dict(report.metrics_snapshot),
                    recommendations=normalize_json_list(report.recommendations),
                    segment_analysis=normalize_json_list(report.segment_analysis),
                    timing_analysis=normalize_json_dict(report.timing_analysis),
                    prompt_performance=normalize_json_list(report.prompt_performance),
                    key_findings=normalize_json_list(report.key_findings),
                    what_worked=normalize_json_list(report.what_worked),
                )
            )
        return evidence

    async def pending_action_exists(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID,
        dedupe_key: str,
    ) -> bool:
        """Return true when a matching pending/approved/executed action already exists."""
        result = await db.execute(
            select(PendingAction.id).where(
                PendingAction.workspace_id == workspace_id,
                PendingAction.action_type == OUTBOUND_FOLLOW_UP_ACTION_TYPE,
                PendingAction.status.in_(["pending", "approved", "executed"]),
                PendingAction.context["dedupe_key"].astext == dedupe_key,
            )
        )
        return result.scalar_one_or_none() is not None

    async def synthesize_recommendation(
        self,
        evidence: list[CampaignEvidence],
        summary: BestPerformerSummary,
    ) -> OutboundRecommendation:
        """Use OpenAI to synthesize a concise follow-up campaign recommendation."""
        fallback = _fallback_recommendation(summary)
        prompt = self._build_synthesis_prompt(evidence, summary)
        try:
            client = self._get_client()
            response = await client.chat.completions.create(
                model="gpt-5.4-mini",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You analyze outbound sales campaign performance and return one "
                            "safe follow-up campaign recommendation as JSON only. Do not "
                            "create or execute campaigns."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.2,
            )
        except Exception:
            logger.exception("Failed to synthesize outbound recommendation with OpenAI")
            return fallback
        content = response.choices[0].message.content or "{}"
        return parse_llm_recommendation(content, fallback)

    async def mark_reports_with_suggestion(
        self,
        db: AsyncSession,
        report_ids: list[uuid.UUID],
        action_id: uuid.UUID,
    ) -> None:
        """Append the generated PendingAction ID to source reports."""
        result = await db.execute(select(CampaignReport).where(CampaignReport.id.in_(report_ids)))
        action_id_text = str(action_id)
        for report in result.scalars().all():
            existing = list(report.generated_suggestion_ids or [])
            if action_id_text not in existing:
                existing.append(action_id_text)
                report.generated_suggestion_ids = existing
        await db.flush()

    def _build_synthesis_prompt(
        self,
        evidence: list[CampaignEvidence],
        summary: BestPerformerSummary,
    ) -> str:
        source = {
            "best_performers": asdict(summary),
            "source_campaigns": [
                {
                    "campaign_id": str(item.campaign_id),
                    "campaign_name": item.campaign_name,
                    "campaign_type": item.campaign_type,
                    "metrics": item.metrics,
                    "recommendations": item.recommendations[:5],
                    "segment_analysis": item.segment_analysis[:5],
                    "timing_analysis": item.timing_analysis,
                    "prompt_performance": item.prompt_performance[:5],
                    "what_worked": item.what_worked[:5],
                    "initial_message": item.initial_message,
                    "sms_fallback_template": item.sms_fallback_template,
                    "responder_agent_id": str(item.responder_agent_id)
                    if item.responder_agent_id
                    else None,
                }
                for item in evidence
            ],
        }
        return (
            "Return JSON with keys: title, rationale, target_segment, angle, message, "
            "responder_agent_id, confidence (0-1), expected_outcome. Base the recommendation "
            "only on this evidence and keep it human-reviewable. Evidence:\n"
            f"{json.dumps(source, sort_keys=True, default=str)}"
        )
