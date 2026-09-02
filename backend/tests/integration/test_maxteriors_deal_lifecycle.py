"""Production-shaped proof for the Maxteriors lifecycle setup and workflow."""

from __future__ import annotations

import importlib.util
import sys
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.models.contact import Contact
from app.models.field_service import Job, JobStatus
from app.models.human_nudge import HumanNudge
from app.models.invoice import Invoice
from app.models.opportunity import Opportunity, OpportunityTask
from app.models.pipeline import Pipeline, PipelineStage
from app.models.quote import Quote
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership
from app.services.jobs.job_service import JobService
from app.services.opportunities.deal_lifecycle_maintenance import (
    NEW_LEAD_NUDGE_TYPE,
    run_deal_lifecycle_maintenance,
)
from app.services.opportunities.invoice_lifecycle import (
    FOLLOW_UP_DELAYS_HOURS,
    transition_invoice_opportunity,
)

pytestmark = pytest.mark.integration

_SCRIPT_PATH = (
    Path(__file__).resolve().parents[3] / "scripts" / "ops" / "setup_maxteriors_deal_lifecycle.py"
)


@pytest.fixture(scope="module")
def setup_script() -> Any:
    spec = importlib.util.spec_from_file_location("setup_maxteriors_deal_lifecycle", _SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def database_url() -> str:
    return (
        make_url(settings.database_url)
        .set(drivername="postgresql+asyncpg")
        .render_as_string(hide_password=False)
    )


@dataclass(slots=True)
class SeededLifecycle:
    db: AsyncSession
    workspace: Workspace
    user: User
    email: str
    pipeline: Pipeline
    stages: dict[str, PipelineStage]
    cleanup_workspace_ids: list[uuid.UUID]


@pytest_asyncio.fixture
async def seeded_lifecycle(
    database_url: str,
    setup_script: Any,
) -> SeededLifecycle:
    engine = create_async_engine(database_url)
    async with engine.begin() as connection:
        await connection.execute(text("SELECT 1"))
        has_schema = await connection.run_sync(
            lambda sync_connection: inspect(sync_connection).has_table("workspaces")
        )
    assert has_schema, "Database schema is not initialized; run migrations first"

    session_factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    unique = uuid.uuid4().hex

    async with session_factory() as db:
        workspace = Workspace(
            name=f"Lifecycle integration {unique}",
            slug=f"lifecycle-integration-{unique}",
            settings={"unrelated": {"preserved": True}},
        )
        user = User(
            email=f"lifecycle-{unique}@example.com",
            hashed_password="not-used",
            full_name="Lifecycle Admin",
            is_active=True,
        )
        db.add_all([workspace, user])
        await db.flush()
        db.add(
            WorkspaceMembership(
                workspace_id=workspace.id,
                user_id=user.id,
                role="admin",
            )
        )
        pipeline = Pipeline(
            workspace_id=workspace.id,
            name="Lifecycle Pipeline",
            is_active=True,
        )
        db.add(pipeline)
        await db.flush()

        stages: dict[str, PipelineStage] = {}
        for order, stage_name in enumerate(setup_script.STAGE_NAMES.values()):
            stage_type = "won" if stage_name == "Won" else "active"
            stage = PipelineStage(
                pipeline_id=pipeline.id,
                name=stage_name,
                order=order,
                probability=100 if stage_type == "won" else 0,
                stage_type=stage_type,
            )
            db.add(stage)
            stages[stage_name] = stage
        await db.commit()

        seeded = SeededLifecycle(
            db=db,
            workspace=workspace,
            user=user,
            email=user.email,
            pipeline=pipeline,
            stages=stages,
            cleanup_workspace_ids=[workspace.id],
        )
        user_id = user.id
        try:
            yield seeded
        finally:
            await db.rollback()
            await db.execute(
                delete(Workspace).where(Workspace.id.in_(seeded.cleanup_workspace_ids))
            )
            await db.execute(delete(User).where(User.id == user_id))
            await db.commit()
    await engine.dispose()


async def test_setup_is_dry_run_idempotent_and_exactly_reversible(
    setup_script: Any,
    seeded_lifecycle: SeededLifecycle,
) -> None:
    seeded = seeded_lifecycle

    preview = await setup_script.build_plan(seeded.db, member_email=seeded.email)
    assert preview.changed is True
    assert seeded.workspace.settings == {"unrelated": {"preserved": True}}

    first_apply = await setup_script.apply_setup(seeded.db, member_email=seeded.email)
    await seeded.db.refresh(seeded.workspace)
    configured = seeded.workspace.settings[setup_script.CONFIG_KEY]
    assert first_apply.changed is True
    assert configured["pipeline_id"] == str(seeded.pipeline.id)
    assert configured["follow_up_assignee_user_id"] == seeded.user.id
    assert seeded.workspace.settings["unrelated"] == {"preserved": True}

    second_apply = await setup_script.apply_setup(seeded.db, member_email=seeded.email)
    assert second_apply.changed is False

    rollback = await setup_script.apply_setup(
        seeded.db,
        member_email=seeded.email,
        rollback=True,
    )
    await seeded.db.refresh(seeded.workspace)
    assert rollback.changed is True
    assert seeded.workspace.settings == {"unrelated": {"preserved": True}}

    repeated_rollback = await setup_script.apply_setup(
        seeded.db,
        member_email=seeded.email,
        rollback=True,
    )
    assert repeated_rollback.changed is False


def _opportunity(
    seeded: SeededLifecycle,
    contact_id: int,
    name: str,
    stage_name: str,
    *,
    status: str = "open",
) -> Opportunity:
    stage = seeded.stages[stage_name]
    return Opportunity(
        workspace_id=seeded.workspace.id,
        pipeline_id=seeded.pipeline.id,
        stage_id=stage.id,
        primary_contact_id=contact_id,
        name=name,
        status=status,
        probability=stage.probability,
    )


async def _verify_invoice_flow(
    seeded: SeededLifecycle,
    contact_id: int,
    now: datetime,
) -> Opportunity:
    db = seeded.db
    deal = _opportunity(seeded, contact_id, "Invoice lifecycle", "Qualified and No Show")
    db.add(deal)
    await db.flush()
    invoice = Invoice(
        workspace_id=seeded.workspace.id,
        contact_id=contact_id,
        opportunity_id=deal.id,
        number="INV-E2E-SENT",
        status="sent",
        subtotal=1000,
        total=1000,
        amount_paid=0,
        sent_at=now,
    )
    db.add(invoice)
    await db.flush()

    assert await transition_invoice_opportunity(db, invoice, transition="sent") is True
    assert await transition_invoice_opportunity(db, invoice, transition="sent") is False
    await db.flush()
    await db.refresh(deal)
    assert deal.stage_id == seeded.stages["Quote Sent / Follow Up"].id
    tasks = list(
        (
            await db.scalars(
                select(OpportunityTask)
                .where(OpportunityTask.opportunity_id == deal.id)
                .order_by(OpportunityTask.due_at)
            )
        ).all()
    )
    assert len(tasks) == 2
    assert [int((task.due_at - now).total_seconds() / 3600) for task in tasks] == list(
        FOLLOW_UP_DELAYS_HOURS
    )
    assert all(task.assigned_user_id == seeded.user.id for task in tasks)

    invoice.status = "paid"
    invoice.amount_paid = invoice.total
    invoice.paid_at = now + timedelta(hours=1)
    assert await transition_invoice_opportunity(db, invoice, transition="paid") is True
    await db.flush()
    await db.refresh(deal)
    assert deal.stage_id == seeded.stages["Won"].id
    assert deal.status == "won"
    assert all(task.completed_at == invoice.paid_at for task in tasks)
    return deal


async def _verify_unpaid_expiry_and_cleanup(
    seeded: SeededLifecycle,
    contact_id: int,
    now: datetime,
) -> None:
    db = seeded.db
    unpaid_deal = _opportunity(seeded, contact_id, "Unpaid lifecycle", "Quote Sent / Follow Up")
    new_lead = _opportunity(seeded, contact_id, "Daily cleanup", "New Lead")
    db.add_all([unpaid_deal, new_lead])
    await db.flush()
    db.add(
        Invoice(
            workspace_id=seeded.workspace.id,
            contact_id=contact_id,
            opportunity_id=unpaid_deal.id,
            number="INV-E2E-UNPAID",
            status="sent",
            subtotal=500,
            total=500,
            amount_paid=0,
            sent_at=now - timedelta(days=7),
        )
    )
    await db.flush()

    first_run = await run_deal_lifecycle_maintenance(db, now=now)
    await db.flush()
    await db.refresh(unpaid_deal)
    assert first_run.expired_invoices == 1
    assert unpaid_deal.stage_id == seeded.stages["Unqualified (archived)"].id
    assert unpaid_deal.status == "lost"
    assert first_run.nudges_created == 1
    nudge = await db.scalar(
        select(HumanNudge).where(
            HumanNudge.workspace_id == seeded.workspace.id,
            HumanNudge.nudge_type == NEW_LEAD_NUDGE_TYPE,
        )
    )
    assert nudge is not None and nudge.status == "pending"

    new_lead.stage_id = seeded.stages["Contacted (No Answer)"].id
    await db.flush()
    second_run = await run_deal_lifecycle_maintenance(db, now=now)
    await db.flush()
    await db.refresh(nudge)
    assert second_run.expired_invoices == 0
    assert second_run.nudges_created == 0
    assert second_run.nudges_resolved == 1
    assert nudge.status == "acted"
    assert nudge.acted_at == now


async def _verify_installation_completion(
    seeded: SeededLifecycle,
    contact_id: int,
    now: datetime,
) -> None:
    db = seeded.db
    deal = _opportunity(
        seeded,
        contact_id,
        "Installation lifecycle",
        "Won",
        status="won",
    )
    db.add(deal)
    await db.flush()
    quote = Quote(
        workspace_id=seeded.workspace.id,
        contact_id=contact_id,
        opportunity_id=deal.id,
        number="QUO-E2E-INSTALL",
        title="Install lighting",
        status="approved",
        subtotal=1500,
        total=1500,
    )
    db.add(quote)
    await db.flush()
    job = Job(
        workspace_id=seeded.workspace.id,
        contact_id=contact_id,
        source_quote_id=quote.id,
        title="Scheduled installation",
        status=JobStatus.SCHEDULED,
        scheduled_start=now + timedelta(days=1),
        scheduled_end=now + timedelta(days=1, hours=4),
    )
    db.add(job)
    await db.flush()

    await JobService(db).update(
        job.id,
        seeded.workspace.id,
        {"status": JobStatus.COMPLETED},
    )
    await db.flush()
    await db.refresh(deal)
    assert deal.stage_id == seeded.stages["Job Completed"].id
    assert deal.status == "won"


async def test_configured_lifecycle_workflow_end_to_end(
    setup_script: Any,
    seeded_lifecycle: SeededLifecycle,
) -> None:
    seeded = seeded_lifecycle
    now = datetime(2026, 9, 2, 22, tzinfo=UTC)
    await setup_script.apply_setup(seeded.db, member_email=seeded.email)
    contact = Contact(
        workspace_id=seeded.workspace.id,
        first_name="Lifecycle",
        last_name="Customer",
        email=f"customer-{uuid.uuid4().hex}@example.com",
        phone_number="+15555550199",
    )
    seeded.db.add(contact)
    await seeded.db.flush()

    invoice_deal = await _verify_invoice_flow(seeded, contact.id, now)
    await _verify_unpaid_expiry_and_cleanup(seeded, contact.id, now)
    await _verify_installation_completion(seeded, contact.id, now)
    assert (
        await seeded.db.scalar(
            select(func.count(OpportunityTask.id)).where(
                OpportunityTask.opportunity_id == invoice_deal.id
            )
        )
        == 2
    )


async def test_setup_aborts_when_workspace_match_is_missing(
    setup_script: Any,
    seeded_lifecycle: SeededLifecycle,
) -> None:
    with pytest.raises(setup_script.ScriptAbortError, match="found 0"):
        await setup_script.build_plan(
            seeded_lifecycle.db,
            member_email=f"missing-{uuid.uuid4().hex}@example.com",
        )


async def test_setup_ignores_inactive_workspace_membership(
    setup_script: Any,
    seeded_lifecycle: SeededLifecycle,
) -> None:
    seeded = seeded_lifecycle
    archived = Workspace(
        name="Archived workspace",
        slug=f"archived-lifecycle-{uuid.uuid4().hex}",
        settings={},
        is_active=False,
    )
    seeded.db.add(archived)
    await seeded.db.flush()
    seeded.db.add(
        WorkspaceMembership(
            workspace_id=archived.id,
            user_id=seeded.user.id,
            role="owner",
        )
    )
    await seeded.db.commit()
    seeded.cleanup_workspace_ids.append(archived.id)

    plan = await setup_script.build_plan(seeded.db, member_email=seeded.email)
    assert plan.workspace.id == seeded.workspace.id


async def test_setup_aborts_when_workspace_match_is_ambiguous(
    setup_script: Any,
    seeded_lifecycle: SeededLifecycle,
) -> None:
    seeded = seeded_lifecycle
    other = Workspace(
        name="Other active workspace",
        slug=f"other-lifecycle-{uuid.uuid4().hex}",
        settings={},
    )
    seeded.db.add(other)
    await seeded.db.flush()
    seeded.db.add(
        WorkspaceMembership(
            workspace_id=other.id,
            user_id=seeded.user.id,
            role="member",
        )
    )
    await seeded.db.commit()
    seeded.cleanup_workspace_ids.append(other.id)

    with pytest.raises(setup_script.ScriptAbortError, match="found 2"):
        await setup_script.build_plan(seeded.db, member_email=seeded.email)


async def test_setup_aborts_when_required_stage_is_missing(
    setup_script: Any,
    seeded_lifecycle: SeededLifecycle,
) -> None:
    seeded = seeded_lifecycle
    won = seeded.stages["Won"]
    won.name = "Won (renamed)"
    await seeded.db.commit()

    with pytest.raises(setup_script.ScriptAbortError, match="'Won'.*found 0"):
        await setup_script.build_plan(seeded.db, member_email=seeded.email)


async def test_setup_aborts_when_required_stage_is_ambiguous(
    setup_script: Any,
    seeded_lifecycle: SeededLifecycle,
) -> None:
    seeded = seeded_lifecycle
    duplicate = PipelineStage(
        pipeline_id=seeded.pipeline.id,
        name="Won",
        order=99,
        probability=100,
        stage_type="won",
    )
    seeded.db.add(duplicate)
    await seeded.db.commit()

    with pytest.raises(setup_script.ScriptAbortError, match="'Won'.*found 2"):
        await setup_script.build_plan(seeded.db, member_email=seeded.email)
