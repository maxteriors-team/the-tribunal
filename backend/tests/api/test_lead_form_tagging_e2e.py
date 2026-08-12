"""End-to-end proof that a public lead-form submission auto-tags the new lead.

Models the real operator scenario behind the automations-builder change: a
"Perm Lighting" form and a "Landscape Lighting" form, each with its own
``lead_created`` automation narrowed to that form via ``lead_source_public_key``
and applying a distinct tag. A lead submitted to one form must receive that
form's tag and never the other's.

The whole chain runs for real: an HTTP POST to ``/api/v1/p/leads/{public_key}``
against the actual ASGI app -> contact creation -> ``lead_created`` event emit
-> ``AutomationWorker`` event drain -> ``ContactTag`` written. That is exactly
what the builder's new tag-name + lead-source fields configure.

Marked ``integration`` (real Postgres + real app); run with ``-m integration``.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app.core.encryption import hash_phone
from app.db.session import AsyncSessionLocal, engine
from app.main import app
from app.models.automation import Automation
from app.models.contact import Contact
from app.models.lead_source import LeadSource
from app.models.tag import ContactTag, Tag
from app.models.workspace import Workspace
from app.services.automations.events import EVENT_LEAD_CREATED
from app.workers.automation_worker import AutomationWorker

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture(autouse=True)
async def _fresh_engine_pool():
    """Dispose the shared asyncpg pool around each test.

    pytest-asyncio gives each test a fresh event loop; disposing before and
    after keeps a pooled connection bound to a closed loop from surfacing as
    ``Event loop is closed`` when integration tests run back-to-back.
    """
    await engine.dispose()
    yield
    await engine.dispose()


async def _seed_form(
    db,
    workspace_id: uuid.UUID,
    *,
    name: str,
    domain: str,
    tag: str,
) -> str:
    """Create one enabled lead source + its tagging automation; return its key."""
    public_key = f"ls_{uuid.uuid4().hex[:8]}"
    db.add(
        LeadSource(
            workspace_id=workspace_id,
            name=name,
            public_key=public_key,
            allowed_domains=[domain],
            enabled=True,
        )
    )
    db.add(
        Automation(
            workspace_id=workspace_id,
            name=f"Tag {name} leads",
            trigger_type=EVENT_LEAD_CREATED,
            trigger_config={"lead_source_public_key": public_key},
            actions=[{"type": "apply_tag", "config": {"tag": tag}}],
            is_active=True,
        )
    )
    return public_key


async def _submit_lead(
    public_key: str,
    domain: str,
    *,
    first_name: str,
    phone: str,
    source_detail: str | None = None,
):
    """POST a lead to the public form endpoint through the real ASGI app."""
    body: dict[str, str] = {"first_name": first_name, "phone_number": phone}
    if source_detail is not None:
        body["source_detail"] = source_detail
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.post(
            f"/api/v1/p/leads/{public_key}",
            headers={"Origin": f"https://{domain}"},
            json=body,
        )


async def _drain(db) -> None:
    """Run the worker's event-draining path against the open session."""
    await AutomationWorker()._process_events(db)
    await db.flush()


async def _tags_for_phone(db, workspace_id: uuid.UUID, phone: str) -> set[str]:
    """Return the set of tag names on the contact deduped by this phone."""
    result = await db.execute(
        select(Tag.name)
        .join(ContactTag, ContactTag.tag_id == Tag.id)
        .join(Contact, Contact.id == ContactTag.contact_id)
        .where(
            Contact.workspace_id == workspace_id,
            Contact.phone_hash == hash_phone(phone),
        )
    )
    return set(result.scalars().all())


async def test_lead_form_submission_auto_tags_by_source() -> None:
    """Each form tags its own leads; neither form's tag leaks to the other."""
    perm_domain = "permlights.example.com"
    land_domain = "landscapelights.example.com"
    perm_tag = "Perm Lighting"
    land_tag = "Landscape Lighting"
    perm_phone = "+15550100001"
    land_phone = "+15550100002"

    async with AsyncSessionLocal() as db:
        workspace = Workspace(
            id=uuid.uuid4(),
            name="Lights Co",
            slug=f"lights-{uuid.uuid4().hex[:8]}",
        )
        db.add(workspace)
        await db.flush()
        perm_key = await _seed_form(
            db, workspace.id, name="Perm Lighting Form", domain=perm_domain, tag=perm_tag
        )
        land_key = await _seed_form(
            db, workspace.id, name="Landscape Lighting Form", domain=land_domain, tag=land_tag
        )
        await db.commit()
        workspace_id = workspace.id

    try:
        # A lead comes in from the perm-lighting form.
        perm_resp = await _submit_lead(perm_key, perm_domain, first_name="Pam", phone=perm_phone)
        assert perm_resp.status_code == 200, perm_resp.text
        assert perm_resp.json()["success"] is True

        # And a separate lead comes in from the landscape-lighting form.
        land_resp = await _submit_lead(land_key, land_domain, first_name="Larry", phone=land_phone)
        assert land_resp.status_code == 200, land_resp.text
        assert land_resp.json()["success"] is True

        # Drain the queued lead_created events through the worker once.
        async with AsyncSessionLocal() as db:
            await _drain(db)
            await db.commit()

        # Each contact carries exactly its own form's tag — no cross-tagging.
        async with AsyncSessionLocal() as db:
            perm_tags = await _tags_for_phone(db, workspace_id, perm_phone)
            land_tags = await _tags_for_phone(db, workspace_id, land_phone)

        assert perm_tags == {perm_tag}, perm_tags
        assert land_tags == {land_tag}, land_tags
    finally:
        # Best-effort cleanup: workspace FKs cascade to lead sources,
        # automations, contacts, and tags, so this leaves no test residue.
        async with AsyncSessionLocal() as db:
            await db.execute(delete(Workspace).where(Workspace.id == workspace_id))
            await db.commit()


async def test_source_detail_fallback_tags_lead_from_an_unlisted_form() -> None:
    """The permholidaylights funnel rule, matched by ``source_detail`` alone.

    The instant-quote page can post through a form whose public key the
    automation was never told about (a rebuilt embed, a second landing page).
    The ``source_detail`` selector is the safety net that still classifies those
    leads — tagged for the operator, Facebook recorded as the channel — and it
    has to survive the operator's own casing/whitespace.
    """
    domain = "permholidaylights.example.com"
    phone = "+15550100004"
    source_detail = "permholidaylights instant quote"

    async with AsyncSessionLocal() as db:
        workspace = Workspace(
            id=uuid.uuid4(),
            name="Perm Holiday Lights",
            slug=f"perm-{uuid.uuid4().hex[:8]}",
        )
        db.add(workspace)
        await db.flush()
        public_key = f"ls_{uuid.uuid4().hex[:8]}"
        db.add(
            LeadSource(
                workspace_id=workspace.id,
                name="Instant Quote",
                public_key=public_key,
                allowed_domains=[domain],
                enabled=True,
            )
        )
        db.add(
            Automation(
                workspace_id=workspace.id,
                name="Perm Light Lead — auto text",
                trigger_type=EVENT_LEAD_CREATED,
                # Deliberately a *different* form key: only source_detail can match.
                trigger_config={
                    "lead_source_public_key": f"ls_{uuid.uuid4().hex[:8]}",
                    "source_detail": source_detail,
                },
                actions=[
                    {"type": "add_tag", "config": {"tag": "Perm Light Lead"}},
                    {"type": "add_tag", "config": {"tag": "Facebook"}},
                ],
                is_active=True,
            )
        )
        await db.commit()
        workspace_id = workspace.id

    try:
        resp = await _submit_lead(
            public_key,
            domain,
            first_name="Pat",
            phone=phone,
            source_detail="  PermHolidayLights Instant Quote  ",
        )
        assert resp.status_code == 200, resp.text

        async with AsyncSessionLocal() as db:
            await _drain(db)
            await db.commit()

        async with AsyncSessionLocal() as db:
            tags = await _tags_for_phone(db, workspace_id, phone)

        assert tags == {"Perm Light Lead", "Facebook"}, tags
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(delete(Workspace).where(Workspace.id == workspace_id))
            await db.commit()


async def test_lead_form_without_automation_creates_untagged_lead() -> None:
    """A form with no tagging automation still captures the lead — just untagged.

    Guards the negative half of the contract: tagging is opt-in per form, so a
    plain "collect" form must not invent tags.
    """
    domain = "plainform.example.com"
    phone = "+15550100003"

    async with AsyncSessionLocal() as db:
        workspace = Workspace(
            id=uuid.uuid4(),
            name="Plain Co",
            slug=f"plain-{uuid.uuid4().hex[:8]}",
        )
        db.add(workspace)
        await db.flush()
        public_key = f"ls_{uuid.uuid4().hex[:8]}"
        db.add(
            LeadSource(
                workspace_id=workspace.id,
                name="Plain Form",
                public_key=public_key,
                allowed_domains=[domain],
                enabled=True,
            )
        )
        await db.commit()
        workspace_id = workspace.id

    try:
        resp = await _submit_lead(public_key, domain, first_name="Nora", phone=phone)
        assert resp.status_code == 200, resp.text

        async with AsyncSessionLocal() as db:
            await _drain(db)
            await db.commit()

        async with AsyncSessionLocal() as db:
            # Contact exists...
            contact = await db.execute(
                select(Contact.id).where(
                    Contact.workspace_id == workspace_id,
                    Contact.phone_hash == hash_phone(phone),
                )
            )
            assert contact.scalar_one_or_none() is not None
            # ...and carries no tags.
            assert await _tags_for_phone(db, workspace_id, phone) == set()
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(delete(Workspace).where(Workspace.id == workspace_id))
            await db.commit()
