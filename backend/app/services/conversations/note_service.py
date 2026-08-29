"""Conversation notes: rep-authored observations plus synced Quo summaries."""

import uuid
from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy import delete, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation_note import (
    NOTE_SOURCE_HUMAN,
    NOTE_SOURCE_QUO_SUMMARY,
    ConversationNote,
)
from app.models.human_nudge import HumanNudge
from app.models.user import User
from app.schemas.conversation_note import ConversationNoteResponse
from app.services.conversations.conversation_service import ConversationService

# Newest notes matter most mid-call, but a rail that reorders while a rep is
# reading it is worse than a long one, so this is a plain cap on history.
MAX_NOTES_RETURNED = 200

# Reminders set from a note are ordinary nudges, so they inherit the existing
# delivery worker, snooze, dismiss and list endpoints rather than growing a
# second reminder system beside them.
NOTE_REMINDER_NUDGE_TYPE = "note_followup"

# A nudge's title is what the rep sees in a push notification, so it carries the
# note's opening words rather than a generic "Reminder".
_REMINDER_TITLE_CHARS = 60


def _reminder_dedup_key(note_id: uuid.UUID) -> str:
    """Key one reminder to one note.

    ``HumanNudge.dedup_key`` is globally unique, so this both links the two rows
    without a schema change and makes re-setting a reminder an update rather
    than a second notification for the same note.
    """
    return f"{NOTE_REMINDER_NUDGE_TYPE}:{note_id}"


class ConversationNoteService:
    """Read and write the notes attached to one conversation."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        # Reused rather than re-implemented: it enforces workspace scoping *and*
        # the Quo-line visibility rule, so notes can never become a side door to
        # a conversation the caller cannot open.
        self._conversations = ConversationService(db)

    async def _assert_conversation_visible(
        self,
        conversation_id: uuid.UUID,
        workspace_id: uuid.UUID,
    ) -> None:
        await self._conversations._get_conversation(
            conversation_id=conversation_id,
            workspace_id=workspace_id,
        )

    @staticmethod
    def _to_response(
        note: ConversationNote,
        author_name: str | None,
        reminder: HumanNudge | None = None,
    ) -> ConversationNoteResponse:
        return ConversationNoteResponse(
            id=note.id,
            conversation_id=note.conversation_id,
            body=note.body,
            source=note.source,
            author_user_id=note.author_user_id,
            author_name=author_name,
            created_at=note.created_at,
            updated_at=note.updated_at,
            reminder_at=reminder.due_date if reminder else None,
            reminder_status=reminder.status if reminder else None,
        )

    async def _reminders_for(self, note_ids: list[uuid.UUID]) -> dict[uuid.UUID, HumanNudge]:
        """Load every note's reminder in one query.

        Keyed off the nudge's globally unique ``dedup_key``, so a note can only
        ever own one reminder. Batched deliberately: the rail renders up to
        MAX_NOTES_RETURNED notes, and a per-note lookup would be that many round
        trips on the conversation's hot path.
        """
        if not note_ids:
            return {}
        by_key = {_reminder_dedup_key(note_id): note_id for note_id in note_ids}
        result = await self.db.execute(
            select(HumanNudge).where(HumanNudge.dedup_key.in_(list(by_key)))
        )
        return {by_key[nudge.dedup_key]: nudge for nudge in result.scalars() if nudge.dedup_key}

    async def list_notes(
        self,
        conversation_id: uuid.UUID,
        workspace_id: uuid.UUID,
    ) -> list[ConversationNoteResponse]:
        """Return one conversation's notes, oldest first."""
        await self._assert_conversation_visible(conversation_id, workspace_id)

        # Left join: Quo summaries have no author, and a departed rep's notes
        # must keep rendering after users.id is nulled out.
        result = await self.db.execute(
            select(ConversationNote, User.full_name)
            .outerjoin(User, User.id == ConversationNote.author_user_id)
            .where(
                ConversationNote.workspace_id == workspace_id,
                ConversationNote.conversation_id == conversation_id,
            )
            .order_by(ConversationNote.created_at.asc())
            .limit(MAX_NOTES_RETURNED)
        )
        rows = result.all()
        reminders = await self._reminders_for([note.id for note, _ in rows])
        return [
            self._to_response(note, author_name, reminders.get(note.id))
            for note, author_name in rows
        ]

    async def create_note(
        self,
        conversation_id: uuid.UUID,
        workspace_id: uuid.UUID,
        author_user_id: int,
        body: str,
    ) -> ConversationNoteResponse:
        """Record a rep's note against a conversation."""
        await self._assert_conversation_visible(conversation_id, workspace_id)

        note = ConversationNote(
            workspace_id=workspace_id,
            conversation_id=conversation_id,
            author_user_id=author_user_id,
            source=NOTE_SOURCE_HUMAN,
            body=body,
        )
        self.db.add(note)
        await self.db.commit()
        await self.db.refresh(note)

        author = await self.db.get(User, author_user_id)
        return self._to_response(note, author.full_name if author else None)

    async def _get_owned_note(
        self,
        note_id: uuid.UUID,
        conversation_id: uuid.UUID,
        workspace_id: uuid.UUID,
        actor_user_id: int,
    ) -> ConversationNote:
        """Fetch a note the caller is allowed to modify.

        Editing is author-only: a note is a timestamped record of what one
        person observed, so letting a colleague rewrite it would quietly corrupt
        the account history. A non-author gets 404 rather than 403 so the
        existence of another rep's note is not disclosed.
        """
        result = await self.db.execute(
            select(ConversationNote).where(
                ConversationNote.id == note_id,
                ConversationNote.workspace_id == workspace_id,
                ConversationNote.conversation_id == conversation_id,
            )
        )
        note = result.scalar_one_or_none()
        if note is None or note.author_user_id != actor_user_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Note not found",
            )
        return note

    async def update_note(
        self,
        note_id: uuid.UUID,
        conversation_id: uuid.UUID,
        workspace_id: uuid.UUID,
        actor_user_id: int,
        body: str,
    ) -> ConversationNoteResponse:
        """Edit a note the caller wrote."""
        await self._assert_conversation_visible(conversation_id, workspace_id)
        note = await self._get_owned_note(note_id, conversation_id, workspace_id, actor_user_id)

        note.body = body
        await self.db.commit()
        await self.db.refresh(note)

        author = await self.db.get(User, actor_user_id)
        return self._to_response(note, author.full_name if author else None)

    async def delete_note(
        self,
        note_id: uuid.UUID,
        conversation_id: uuid.UUID,
        workspace_id: uuid.UUID,
        actor_user_id: int,
    ) -> None:
        """Delete a note the caller wrote."""
        await self._assert_conversation_visible(conversation_id, workspace_id)
        note = await self._get_owned_note(note_id, conversation_id, workspace_id, actor_user_id)

        await self.db.delete(note)
        await self.db.commit()

    async def record_quo_summary(
        self,
        conversation_id: uuid.UUID,
        workspace_id: uuid.UUID,
        call_id: str,
        body: str,
    ) -> None:
        """Persist a Quo call summary as a note, idempotently.

        Quo retries webhooks and may resend a call's summary after refining it,
        so this upserts on (workspace_id, source_ref): a redelivery updates the
        existing note in place instead of appending a duplicate recap to the
        rep's rail. Deliberately does not commit — the caller owns the
        transaction that also writes the call's message row, so a failure leaves
        neither behind.
        """
        statement = pg_insert(ConversationNote).values(
            id=uuid.uuid4(),
            workspace_id=workspace_id,
            conversation_id=conversation_id,
            author_user_id=None,
            source=NOTE_SOURCE_QUO_SUMMARY,
            source_ref=call_id,
            body=body,
        )
        await self.db.execute(
            statement.on_conflict_do_update(
                index_elements=[ConversationNote.workspace_id, ConversationNote.source_ref],
                index_where=text("source_ref IS NOT NULL"),
                set_={"body": statement.excluded.body},
            )
        )

    async def set_reminder(
        self,
        note_id: uuid.UUID,
        conversation_id: uuid.UUID,
        workspace_id: uuid.UUID,
        actor_user_id: int,
        due_at: datetime,
    ) -> ConversationNoteResponse:
        """Set (or move) the follow-up reminder on a note the caller wrote.

        Deliberately a ``HumanNudge`` rather than a column on the note: the
        delivery worker already claims any pending nudge whose due date has
        passed, and the nudge endpoints already implement snooze, dismiss, act
        and list. Reusing it means a note reminder is delivered and managed by
        machinery that is already in production.
        """
        await self._assert_conversation_visible(conversation_id, workspace_id)
        note = await self._get_owned_note(note_id, conversation_id, workspace_id, actor_user_id)
        conversation = await self._conversations._get_conversation(
            conversation_id=conversation_id,
            workspace_id=workspace_id,
        )

        summary = " ".join(note.body.split())
        if len(summary) > _REMINDER_TITLE_CHARS:
            summary = f"{summary[:_REMINDER_TITLE_CHARS].rstrip()}…"

        values = {
            "workspace_id": workspace_id,
            "contact_id": conversation.contact_id,
            "nudge_type": NOTE_REMINDER_NUDGE_TYPE,
            "title": f"Follow up: {summary}",
            "message": note.body,
            "due_date": due_at,
            # The rep who wrote the note is the one who wanted reminding; without
            # this the nudge falls back to broadcasting at every CRM writer.
            "assigned_to_user_id": actor_user_id,
            "dedup_key": _reminder_dedup_key(note_id),
        }
        statement = pg_insert(HumanNudge).values(id=uuid.uuid4(), **values)
        await self.db.execute(
            statement.on_conflict_do_update(
                index_elements=[HumanNudge.dedup_key],
                set_={
                    "due_date": statement.excluded.due_date,
                    "title": statement.excluded.title,
                    "message": statement.excluded.message,
                    "assigned_to_user_id": statement.excluded.assigned_to_user_id,
                    # Moving the date revives an already-fired or dismissed
                    # reminder; otherwise the worker would skip it forever.
                    "status": "pending",
                    "snoozed_until": None,
                },
            )
        )
        await self.db.commit()

        author = await self.db.get(User, actor_user_id)
        reminders = await self._reminders_for([note_id])
        return self._to_response(note, author.full_name if author else None, reminders.get(note_id))

    async def clear_reminder(
        self,
        note_id: uuid.UUID,
        conversation_id: uuid.UUID,
        workspace_id: uuid.UUID,
        actor_user_id: int,
    ) -> ConversationNoteResponse:
        """Cancel the reminder on a note the caller wrote, keeping the note."""
        await self._assert_conversation_visible(conversation_id, workspace_id)
        note = await self._get_owned_note(note_id, conversation_id, workspace_id, actor_user_id)

        # Scoped by workspace as well as key: dedup_key is globally unique, so
        # this refuses to delete another tenant's row even if a key ever collided.
        await self.db.execute(
            delete(HumanNudge).where(
                HumanNudge.workspace_id == workspace_id,
                HumanNudge.dedup_key == _reminder_dedup_key(note_id),
            )
        )
        await self.db.commit()

        author = await self.db.get(User, actor_user_id)
        return self._to_response(note, author.full_name if author else None, None)
