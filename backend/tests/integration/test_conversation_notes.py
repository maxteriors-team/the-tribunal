"""Database-backed conversation note behavior and authorization boundaries."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, get_membership
from app.api.v1 import conversations
from app.core.encryption import EncryptedString
from app.db.session import AsyncSessionLocal, engine
from app.models.conversation import Conversation
from app.models.conversation_note import MAX_NOTE_BODY_CHARS, ConversationNote
from app.models.human_nudge import HumanNudge
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership
from app.services.conversations.note_service import ConversationNoteService

pytestmark = pytest.mark.integration


@dataclass
class Scenario:
    workspace_id: uuid.UUID
    other_workspace_id: uuid.UUID
    conversation_id: uuid.UUID
    other_workspace_conversation_id: uuid.UUID
    author: User
    colleague: User
    author_membership: WorkspaceMembership
    colleague_membership: WorkspaceMembership


def _conversation(workspace_id: uuid.UUID, suffix: str, marker: str) -> Conversation:
    return Conversation(
        workspace_id=workspace_id,
        workspace_phone=f"+1555{marker}0000",
        workspace_phone_hash=f"hash-ws-{marker}-{suffix}",
        contact_phone=f"+1555{marker}1111",
        contact_phone_hash=f"hash-contact-{marker}-{suffix}",
    )


@asynccontextmanager
async def _scenario() -> AsyncIterator[Scenario]:
    await engine.dispose()
    suffix = uuid.uuid4().hex
    async with AsyncSessionLocal() as db:
        workspace = Workspace(name="Notes", slug=f"notes-{suffix}")
        other_workspace = Workspace(name="Other notes", slug=f"other-notes-{suffix}")
        author = User(
            email=f"notes-author-{suffix}@example.com",
            full_name="Note Author",
            hashed_password="not-used",
        )
        colleague = User(
            email=f"notes-colleague-{suffix}@example.com",
            full_name="Note Colleague",
            hashed_password="not-used",
        )
        db.add_all([workspace, other_workspace, author, colleague])
        await db.flush()

        author_membership = WorkspaceMembership(
            workspace_id=workspace.id, user_id=author.id, role="sales_rep"
        )
        colleague_membership = WorkspaceMembership(
            workspace_id=workspace.id, user_id=colleague.id, role="sales_rep"
        )
        conversation = _conversation(workspace.id, suffix, "1")
        other_conversation = _conversation(other_workspace.id, suffix, "2")
        db.add_all([author_membership, colleague_membership, conversation, other_conversation])
        await db.commit()

        scenario = Scenario(
            workspace_id=workspace.id,
            other_workspace_id=other_workspace.id,
            conversation_id=conversation.id,
            other_workspace_conversation_id=other_conversation.id,
            author=author,
            colleague=colleague,
            author_membership=author_membership,
            colleague_membership=colleague_membership,
        )

    try:
        yield scenario
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(Workspace).where(
                    Workspace.id.in_([scenario.workspace_id, scenario.other_workspace_id])
                )
            )
            await db.execute(delete(User).where(User.id.in_([author.id, colleague.id])))
            await db.commit()
        await engine.dispose()


def _make_app(scenario: Scenario, *, as_colleague: bool = False) -> FastAPI:
    app = FastAPI()
    app.include_router(
        conversations.router,
        prefix="/api/v1/workspaces/{workspace_id}/conversations",
    )
    user = scenario.colleague if as_colleague else scenario.author
    membership = scenario.colleague_membership if as_colleague else scenario.author_membership

    async def override_db() -> AsyncIterator[AsyncSession]:
        async with AsyncSessionLocal() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_membership] = lambda: membership
    return app


def _notes_url(workspace_id: uuid.UUID, conversation_id: uuid.UUID) -> str:
    return f"/api/v1/workspaces/{workspace_id}/conversations/{conversation_id}/notes"


async def _client(app: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_notes_round_trip_and_attribute_their_author() -> None:
    async with _scenario() as scenario, await _client(_make_app(scenario)) as client:
        url = _notes_url(scenario.workspace_id, scenario.conversation_id)

        created = await client.post(url, json={"body": "Roof is 2 storey, steep gable"})
        assert created.status_code == 201
        payload = created.json()
        assert payload["body"] == "Roof is 2 storey, steep gable"
        assert payload["source"] == "human"
        assert payload["author_user_id"] == scenario.author.id
        assert payload["author_name"] == "Note Author"

        listed = await client.get(url)
        assert listed.status_code == 200
        assert [note["body"] for note in listed.json()] == ["Roof is 2 storey, steep gable"]


@pytest.mark.asyncio
async def test_notes_are_not_readable_across_workspaces() -> None:
    """A caller scoped to one workspace cannot reach another's conversation."""
    async with _scenario() as scenario:
        async with await _client(_make_app(scenario)) as client:
            leaked = await client.get(
                _notes_url(scenario.workspace_id, scenario.other_workspace_conversation_id)
            )
            assert leaked.status_code == 404

            written = await client.post(
                _notes_url(scenario.workspace_id, scenario.other_workspace_conversation_id),
                json={"body": "should never land"},
            )
            assert written.status_code == 404

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(ConversationNote).where(
                    ConversationNote.conversation_id == scenario.other_workspace_conversation_id
                )
            )
            assert result.scalars().all() == []


@pytest.mark.asyncio
async def test_only_the_author_can_edit_or_delete_a_note() -> None:
    """A note records who observed what; a colleague must not rewrite it."""
    async with _scenario() as scenario:
        url = _notes_url(scenario.workspace_id, scenario.conversation_id)
        async with await _client(_make_app(scenario)) as client:
            created = await client.post(url, json={"body": "Original observation"})
            note_id = created.json()["id"]

        async with await _client(_make_app(scenario, as_colleague=True)) as colleague:
            edited = await colleague.patch(
                f"{url}/{note_id}", json={"body": "Rewritten by someone else"}
            )
            assert edited.status_code == 404
            removed = await colleague.delete(f"{url}/{note_id}")
            assert removed.status_code == 404

        async with AsyncSessionLocal() as db:
            note = await db.get(ConversationNote, uuid.UUID(note_id))
            assert note is not None
            assert note.body == "Original observation"

        # The author still controls their own note.
        async with await _client(_make_app(scenario)) as client:
            edited = await client.patch(f"{url}/{note_id}", json={"body": "Corrected observation"})
            assert edited.status_code == 200
            assert edited.json()["body"] == "Corrected observation"
            # Hoisted out of the assert: `python -O` strips assert statements,
            # so a request made inside one would silently never run.
            removed = await client.delete(f"{url}/{note_id}")
            assert removed.status_code == 204

            remaining = await client.get(url)
            assert remaining.status_code == 200
            assert remaining.json() == []


@pytest.mark.asyncio
@pytest.mark.parametrize("body", ["", "   ", "\n\t "])
async def test_blank_notes_are_rejected(body: str) -> None:
    """A whitespace-only note reads as data loss in the timeline."""
    async with _scenario() as scenario, await _client(_make_app(scenario)) as client:
        response = await client.post(
            _notes_url(scenario.workspace_id, scenario.conversation_id),
            json={"body": body},
        )
        assert response.status_code == 422


@pytest.mark.asyncio
async def test_oversized_notes_are_rejected_before_the_database() -> None:
    async with _scenario() as scenario, await _client(_make_app(scenario)) as client:
        response = await client.post(
            _notes_url(scenario.workspace_id, scenario.conversation_id),
            json={"body": "x" * (MAX_NOTE_BODY_CHARS + 1)},
        )
        assert response.status_code == 422


@pytest.mark.asyncio
async def test_note_bodies_are_encrypted_at_rest() -> None:
    """Notes describe customers, so the plaintext must never sit in the column."""
    async with _scenario() as scenario:
        secret = "Customer gate code is 4471"
        async with await _client(_make_app(scenario)) as client:
            await client.post(
                _notes_url(scenario.workspace_id, scenario.conversation_id),
                json={"body": secret},
            )

        async with AsyncSessionLocal() as db:
            # Read the raw column, bypassing the EncryptedString decoder.
            raw = await db.execute(
                select(ConversationNote.body.cast(EncryptedString().impl)).where(
                    ConversationNote.conversation_id == scenario.conversation_id
                )
            )
            stored = raw.scalars().one()
        assert secret not in stored
        assert stored.startswith("gAAAAA")


@pytest.mark.asyncio
async def test_quo_summary_is_stored_once_across_webhook_redeliveries() -> None:
    """Quo retries webhooks; a redelivery must refine the note, not duplicate it."""
    async with _scenario() as scenario:
        call_id = f"quo-call-{uuid.uuid4().hex}"
        async with AsyncSessionLocal() as db:
            service = ConversationNoteService(db)
            await service.record_quo_summary(
                conversation_id=scenario.conversation_id,
                workspace_id=scenario.workspace_id,
                call_id=call_id,
                body="Customer wants a gutter quote. Next steps: call Tuesday",
            )
            await db.commit()

            await service.record_quo_summary(
                conversation_id=scenario.conversation_id,
                workspace_id=scenario.workspace_id,
                call_id=call_id,
                body="Customer wants a gutter quote. Next steps: call Wednesday",
            )
            await db.commit()

        async with await _client(_make_app(scenario)) as client:
            notes = (
                await client.get(_notes_url(scenario.workspace_id, scenario.conversation_id))
            ).json()

        assert len(notes) == 1
        assert notes[0]["source"] == "quo_summary"
        # The refined summary wins, and an AI note has no human author.
        assert notes[0]["body"].endswith("call Wednesday")
        assert notes[0]["author_user_id"] is None
        assert notes[0]["author_name"] is None


@pytest.mark.asyncio
async def test_a_reps_note_and_a_quo_summary_coexist_on_one_conversation() -> None:
    async with _scenario() as scenario:
        async with await _client(_make_app(scenario)) as client:
            await client.post(
                _notes_url(scenario.workspace_id, scenario.conversation_id),
                json={"body": "Rep typed this"},
            )

        async with AsyncSessionLocal() as db:
            await ConversationNoteService(db).record_quo_summary(
                conversation_id=scenario.conversation_id,
                workspace_id=scenario.workspace_id,
                call_id=f"quo-call-{uuid.uuid4().hex}",
                body="Quo recapped this",
            )
            await db.commit()

        async with await _client(_make_app(scenario)) as client:
            notes = (
                await client.get(_notes_url(scenario.workspace_id, scenario.conversation_id))
            ).json()

        assert {note["source"] for note in notes} == {"human", "quo_summary"}
        assert len(notes) == 2


@pytest.mark.asyncio
async def test_a_reminder_is_a_real_nudge_the_delivery_worker_will_claim() -> None:
    """The point of reusing HumanNudge is that delivery already works.

    Asserting the row shape is not enough: this checks the reminder satisfies
    the delivery worker's own claim query (pending, due, assigned), so the
    reminder actually fires instead of sitting in a table nobody polls.
    """
    async with _scenario() as scenario:
        url = _notes_url(scenario.workspace_id, scenario.conversation_id)
        due = datetime.now(UTC) + timedelta(days=2)

        async with await _client(_make_app(scenario)) as client:
            note_id = (await client.post(url, json={"body": "Call back re gutters"})).json()["id"]
            response = await client.put(
                f"{url}/{note_id}/reminder", json={"due_at": due.isoformat()}
            )
            assert response.status_code == 200
            assert response.json()["reminder_status"] == "pending"

        async with AsyncSessionLocal() as db:
            nudge = (
                await db.execute(
                    select(HumanNudge).where(HumanNudge.dedup_key == f"note_followup:{note_id}")
                )
            ).scalar_one()
            assert nudge.assigned_to_user_id == scenario.author.id
            assert nudge.workspace_id == scenario.workspace_id

            # The delivery worker's own predicate, with the clock moved past the
            # due date rather than the row hand-crafted to match.
            claimable = (
                (
                    await db.execute(
                        select(HumanNudge).where(
                            HumanNudge.workspace_id == scenario.workspace_id,
                            HumanNudge.status == "pending",
                            HumanNudge.due_date <= due + timedelta(minutes=1),
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert nudge.id in {claimed.id for claimed in claimable}


@pytest.mark.asyncio
async def test_resetting_a_reminder_moves_it_instead_of_adding_a_second() -> None:
    """Re-setting must not leave the rep with two notifications for one note."""
    async with _scenario() as scenario:
        url = _notes_url(scenario.workspace_id, scenario.conversation_id)
        first = datetime.now(UTC) + timedelta(days=1)
        second = datetime.now(UTC) + timedelta(days=5)

        async with await _client(_make_app(scenario)) as client:
            note_id = (await client.post(url, json={"body": "Send the quote"})).json()["id"]
            await client.put(f"{url}/{note_id}/reminder", json={"due_at": first.isoformat()})
            moved = await client.put(
                f"{url}/{note_id}/reminder", json={"due_at": second.isoformat()}
            )
            assert moved.status_code == 200

        async with AsyncSessionLocal() as db:
            nudges = (
                (
                    await db.execute(
                        select(HumanNudge).where(HumanNudge.dedup_key == f"note_followup:{note_id}")
                    )
                )
                .scalars()
                .all()
            )
            assert len(nudges) == 1
            assert nudges[0].due_date.replace(microsecond=0) == second.replace(microsecond=0)


@pytest.mark.asyncio
async def test_a_past_due_reminder_is_rejected() -> None:
    """A past due date fires on the next poll, which reads as spam not a typo."""
    async with _scenario() as scenario:
        url = _notes_url(scenario.workspace_id, scenario.conversation_id)
        async with await _client(_make_app(scenario)) as client:
            note_id = (await client.post(url, json={"body": "Past due"})).json()["id"]
            response = await client.put(
                f"{url}/{note_id}/reminder",
                json={"due_at": (datetime.now(UTC) - timedelta(hours=1)).isoformat()},
            )
            assert response.status_code == 422

        async with AsyncSessionLocal() as db:
            assert (
                await db.execute(
                    select(HumanNudge).where(HumanNudge.dedup_key == f"note_followup:{note_id}")
                )
            ).scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_only_the_author_can_set_or_clear_a_reminder() -> None:
    """A reminder is the author's own follow-up, not a colleague's to reassign."""
    async with _scenario() as scenario:
        url = _notes_url(scenario.workspace_id, scenario.conversation_id)
        due = datetime.now(UTC) + timedelta(days=3)

        async with await _client(_make_app(scenario)) as client:
            note_id = (await client.post(url, json={"body": "Owned note"})).json()["id"]
            await client.put(f"{url}/{note_id}/reminder", json={"due_at": due.isoformat()})

        async with await _client(_make_app(scenario, as_colleague=True)) as colleague:
            hijacked = await colleague.put(
                f"{url}/{note_id}/reminder",
                json={"due_at": (due + timedelta(days=9)).isoformat()},
            )
            assert hijacked.status_code == 404
            cancelled = await colleague.delete(f"{url}/{note_id}/reminder")
            assert cancelled.status_code == 404

        async with AsyncSessionLocal() as db:
            nudge = (
                await db.execute(
                    select(HumanNudge).where(HumanNudge.dedup_key == f"note_followup:{note_id}")
                )
            ).scalar_one()
            assert nudge.assigned_to_user_id == scenario.author.id
            assert nudge.due_date.replace(microsecond=0) == due.replace(microsecond=0)


@pytest.mark.asyncio
async def test_clearing_a_reminder_keeps_the_note() -> None:
    """Cancelling a follow-up must not discard what the rep observed."""
    async with _scenario() as scenario:
        url = _notes_url(scenario.workspace_id, scenario.conversation_id)
        async with await _client(_make_app(scenario)) as client:
            note_id = (await client.post(url, json={"body": "Keep me"})).json()["id"]
            await client.put(
                f"{url}/{note_id}/reminder",
                json={"due_at": (datetime.now(UTC) + timedelta(days=1)).isoformat()},
            )
            cleared = await client.delete(f"{url}/{note_id}/reminder")
            assert cleared.status_code == 200
            assert cleared.json()["reminder_at"] is None
            assert cleared.json()["body"] == "Keep me"

            listed = await client.get(url)
            assert [note["body"] for note in listed.json()] == ["Keep me"]

        async with AsyncSessionLocal() as db:
            assert (
                await db.execute(
                    select(HumanNudge).where(HumanNudge.dedup_key == f"note_followup:{note_id}")
                )
            ).scalar_one_or_none() is None
