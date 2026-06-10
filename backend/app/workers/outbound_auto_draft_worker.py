"""Outbound autopilot draft worker.

Once a day, for each workspace that opted in (workspace setting
``outbound_autopilot.enabled``, default **off**):

1. Find ad-library contacts never enrolled in any campaign.
2. Ensure the managed "Ad library — fresh" segment exists.
3. Resolve the configured default offer (``outbound_autopilot.offer_id``);
   if missing, emit a workspace-level nudge instead of guessing.
4. Reuse :class:`OutboundGrowthWorkflowService` to draft the campaign
   (copy, previews, responder resolution), then enroll the full batch.
5. Park an ``outbound.launch_campaign`` PendingAction so the draft lands in
   the existing approval pipe (web + SMS/push) — nothing sends without a
   human approving it.

Idempotent per workspace per day: skips when an unexpired launch approval is
already pending or one was already created today.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.models.campaign import CampaignContact
from app.models.contact import Contact
from app.models.human_nudge import HumanNudge
from app.models.offer import Offer
from app.models.pending_action import PendingAction
from app.models.segment import Segment
from app.models.workspace import Workspace
from app.services.approval.approval_gate_service import approval_gate_service
from app.services.outbound.growth_workflow import OutboundGrowthWorkflowService
from app.workers.base import BaseWorker, WorkerRegistry

AUTOPILOT_SETTINGS_KEY = "outbound_autopilot"
LAUNCH_ACTION_TYPE = "outbound.launch_campaign"
MANAGED_SEGMENT_NAME = "Ad library — fresh"

# Don't draft a campaign for a trickle; wait for a meaningful batch.
MIN_BATCH_SIZE = 5
# Max previews embedded in the approval description.
MAX_PREVIEWS_IN_DESCRIPTION = 3


class OutboundAutoDraftWorker(BaseWorker):
    """Draft tomorrow-morning's outbound campaign from fresh ad-library contacts."""

    POLL_INTERVAL_SECONDS = 86400  # daily; do not lower (one draft per day max)
    COMPONENT_NAME = "outbound_auto_draft_worker"
    MAX_CONCURRENCY = 1

    async def _process_items(self) -> None:
        async with AsyncSessionLocal() as db:
            # Snapshot scalar values up front: mid-loop commits/rollbacks may
            # expire or detach ORM instances.
            result = await db.execute(
                select(Workspace.id, Workspace.settings).where(Workspace.is_active.is_(True))
            )
            candidates = [
                (workspace_id, settings.get(AUTOPILOT_SETTINGS_KEY, {}))
                for workspace_id, settings in result.all()
            ]
            for workspace_id, autopilot in candidates:
                if not isinstance(autopilot, dict) or not autopilot.get("enabled", False):
                    continue
                try:
                    await self._process_workspace(db, workspace_id, autopilot)
                except Exception:
                    self.logger.exception(
                        "auto_draft_workspace_failed", workspace_id=str(workspace_id)
                    )
                    await db.rollback()

    async def _process_workspace(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID,
        autopilot: dict[str, Any],
    ) -> None:
        log = self.logger.bind(workspace_id=str(workspace_id))

        if await self._already_drafted(db, workspace_id):
            log.debug("auto_draft_skipped_already_drafted")
            return

        batch_contact_ids = await self._uncampaigned_ad_library_contact_ids(db, workspace_id)
        if len(batch_contact_ids) < MIN_BATCH_SIZE:
            log.debug("auto_draft_skipped_small_batch", batch_size=len(batch_contact_ids))
            return

        offer = await self._resolve_offer(db, workspace_id, autopilot.get("offer_id"))
        if offer is None:
            await self._nudge_missing_offer(db, workspace_id)
            log.info("auto_draft_missing_offer_nudged")
            return

        segment = await self._ensure_managed_segment(db, workspace_id)

        workflow = OutboundGrowthWorkflowService(db, workspace_id)
        plan_result = await workflow.plan(
            {
                "intent": "Autopilot: outreach to fresh ad-library advertisers",
                "offer_id": str(offer.id),
                "segment_id": str(segment.id),
                "create_draft": True,
            }
        )
        if plan_result.get("status") != "draft_ready":
            # Remaining inputs (e.g. no SMS number) surface as Today-queue
            # setup gaps; don't guess here.
            log.info(
                "auto_draft_needs_input",
                missing=[m["field"] for m in plan_result.get("missing_inputs", [])],
            )
            await db.rollback()
            return

        campaign_id = uuid.UUID(plan_result["draft"]["campaign_id"])
        enrolled = await self._enroll_batch(db, campaign_id, batch_contact_ids)

        description = _build_description(plan_result, enrolled)
        decision, metadata = await approval_gate_service.check_and_execute_or_queue(
            db,
            agent_id=None,
            workspace_id=workspace_id,
            action_type=LAUNCH_ACTION_TYPE,
            action_payload={"campaign_id": str(campaign_id)},
            description=description,
            context={"source": "outbound_auto_draft", "segment_id": str(segment.id)},
            urgency="high",
            require_approval_without_agent=True,
        )
        await db.commit()
        self.record_items_processed(1)
        log.info(
            "auto_draft_created",
            campaign_id=str(campaign_id),
            enrolled=enrolled,
            decision=decision,
            action_id=(metadata or {}).get("action_id"),
        )

    async def _already_drafted(self, db: AsyncSession, workspace_id: uuid.UUID) -> bool:
        """True when a launch approval is still pending or was created today."""
        now = datetime.now(UTC)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        pending = await db.execute(
            select(PendingAction.id)
            .where(
                PendingAction.workspace_id == workspace_id,
                PendingAction.action_type == LAUNCH_ACTION_TYPE,
                PendingAction.status == "pending",
                (PendingAction.expires_at.is_(None)) | (PendingAction.expires_at > now),
            )
            .limit(1)
        )
        if pending.scalar_one_or_none() is not None:
            return True

        today = await db.execute(
            select(PendingAction.id)
            .where(
                PendingAction.workspace_id == workspace_id,
                PendingAction.action_type == LAUNCH_ACTION_TYPE,
                PendingAction.created_at >= today_start,
            )
            .limit(1)
        )
        return today.scalar_one_or_none() is not None

    async def _uncampaigned_ad_library_contact_ids(
        self, db: AsyncSession, workspace_id: uuid.UUID
    ) -> list[int]:
        enrolled = select(CampaignContact.contact_id)
        result = await db.execute(
            select(Contact.id).where(
                Contact.workspace_id == workspace_id,
                Contact.source == "ad_library",
                Contact.id.notin_(enrolled),
            )
        )
        return [row[0] for row in result.all()]

    async def _resolve_offer(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID,
        raw_offer_id: Any,
    ) -> Offer | None:
        try:
            offer_id = uuid.UUID(str(raw_offer_id))
        except (TypeError, ValueError):
            return None
        result = await db.execute(
            select(Offer).where(Offer.id == offer_id, Offer.workspace_id == workspace_id)
        )
        return result.scalar_one_or_none()

    async def _nudge_missing_offer(self, db: AsyncSession, workspace_id: uuid.UUID) -> None:
        """Workspace-level nudge: autopilot is on but has no offer configured."""
        now = datetime.now(UTC)
        dedup_key = f"{workspace_id}:autopilot_offer_missing:{now.date().isoformat()}"
        existing = await db.execute(
            select(HumanNudge.id).where(HumanNudge.dedup_key == dedup_key).limit(1)
        )
        if existing.scalar_one_or_none() is not None:
            return
        db.add(
            HumanNudge(
                workspace_id=workspace_id,
                contact_id=None,
                nudge_type="monitor_idle",
                title="\u2699\ufe0f Autopilot needs an offer",
                message=(
                    "\u2699\ufe0f Outbound autopilot is on, but no default offer is "
                    "configured. Pick one in settings so morning drafts can be created."
                ),
                priority="high",
                due_date=now,
                status="pending",
                dedup_key=dedup_key,
            )
        )
        await db.commit()

    async def _ensure_managed_segment(self, db: AsyncSession, workspace_id: uuid.UUID) -> Segment:
        result = await db.execute(
            select(Segment).where(
                Segment.workspace_id == workspace_id,
                Segment.name == MANAGED_SEGMENT_NAME,
            )
        )
        segment = result.scalar_one_or_none()
        if segment is not None:
            return segment

        segment = Segment(
            workspace_id=workspace_id,
            name=MANAGED_SEGMENT_NAME,
            description="Managed by outbound autopilot: contacts promoted from the ad library.",
            definition={
                "rules": [{"field": "source", "operator": "equals", "value": "ad_library"}],
                "logic": "and",
            },
        )
        db.add(segment)
        await db.flush()
        return segment

    async def _enroll_batch(
        self,
        db: AsyncSession,
        campaign_id: uuid.UUID,
        contact_ids: list[int],
    ) -> int:
        """Enroll the full batch into the draft (previews are already enrolled)."""
        existing = await db.execute(
            select(CampaignContact.contact_id).where(CampaignContact.campaign_id == campaign_id)
        )
        already = {row[0] for row in existing.all()}
        added = 0
        for contact_id in contact_ids:
            if contact_id in already:
                continue
            db.add(CampaignContact(campaign_id=campaign_id, contact_id=contact_id))
            added += 1
        await db.flush()
        return len(already) + added


def _build_description(plan_result: dict[str, Any], enrolled: int) -> str:
    """Approval description embedding the draft name and sample messages."""
    draft = plan_result.get("draft", {})
    previews = plan_result.get("previews", [])[:MAX_PREVIEWS_IN_DESCRIPTION]
    lines = [
        f'Launch outbound campaign "{draft.get("name", "Autopilot draft")}" '
        f"to {enrolled} ad-library contact{'s' if enrolled != 1 else ''}.",
    ]
    if previews:
        lines.append("Sample messages:")
        lines.extend(
            f"- {p.get('contact_name') or 'Contact'}: {p.get('message')}" for p in previews
        )
    return "\n".join(lines)


_registry = WorkerRegistry(OutboundAutoDraftWorker)
start_outbound_auto_draft_worker = _registry.start
stop_outbound_auto_draft_worker = _registry.stop
get_outbound_auto_draft_worker = _registry.get
