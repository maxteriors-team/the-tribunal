"""Tests for conversation response serialization."""

import uuid
from datetime import UTC, datetime

from app.models.contact import Contact
from app.models.conversation import Conversation, ConversationStatus
from app.services.conversations.conversation_service import serialize_conversation
from tests.factories import ContactFactory, ConversationFactory


class TestSerializeConversation:
    """The chat list labels threads by contact name, not phone number."""

    def test_includes_contact_full_name(self) -> None:
        """A loaded contact surfaces as ``contact_name``."""
        contact = ContactFactory.build(first_name="Robin", last_name="Stevanovich")
        conversation = ConversationFactory.build(contact=contact, workspace=contact.workspace)

        response = serialize_conversation(conversation)

        assert response.contact_name == "Robin Stevanovich"
        assert response.contact_phone == conversation.contact_phone

    def test_first_name_only_contact(self) -> None:
        """Contacts without a last name still get a usable label."""
        contact: Contact = ContactFactory.build(first_name="Robin", last_name=None)
        conversation = ConversationFactory.build(contact=contact, workspace=contact.workspace)

        assert serialize_conversation(conversation).contact_name == "Robin"

    def test_unlinked_conversation_has_no_name(self) -> None:
        """Threads with no contact fall back to ``None`` so clients show the phone."""
        conversation = ConversationFactory.build(contact=None, contact_id=None)

        assert serialize_conversation(conversation).contact_name is None

    def test_unloaded_contact_does_not_lazy_load(self) -> None:
        """An un-eager-loaded relationship yields ``None`` instead of emitting IO.

        A lazy load here would raise ``MissingGreenlet`` on the async session and
        take down the whole response over a display label.
        """
        conversation = Conversation(
            id=uuid.uuid4(),
            workspace_id=uuid.uuid4(),
            contact_id=42,
            workspace_phone="+15550000000",
            contact_phone="+15551234567",
            status=ConversationStatus.ACTIVE,
            channel="sms",
            ai_enabled=True,
            ai_paused=False,
            unread_count=0,
            created_at=datetime.now(UTC),
        )

        response = serialize_conversation(conversation)

        assert response.contact_name is None
        assert response.contact_id == 42
