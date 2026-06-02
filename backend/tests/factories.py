"""factory_boy factories for SQLAlchemy models.

These factories let tests construct realistic model instances without
hand-rolling every field. Two usage modes:

1. **Build mode (no DB)** — ``WorkspaceFactory.build()`` returns a transient
   model instance. Use this in unit tests that mock the session. This is the
   default for the conftest fixtures (each factory has its session unset).
2. **Create mode (persisted)** — call
   :func:`bind_factories_to_session` from a DB-backed fixture to attach an
   ``AsyncSession``'s underlying sync session. Then ``WorkspaceFactory()`` /
   ``WorkspaceFactory.create()`` will ``add()`` to the session.

Relationships are wired with :class:`factory.SubFactory` so a child factory
auto-builds its parent (e.g., a ``ContactFactory`` builds a ``WorkspaceFactory``
unless ``workspace=`` is passed). Use the ``workspace_id=`` shortcut on
build calls to keep IDs consistent across siblings.

Example::

    workspace = WorkspaceFactory.build()
    contact = ContactFactory.build(workspace=workspace)
    assert contact.workspace_id == workspace.id

Post-generation hooks attach optional many-to-many relations — pass
``tag_objects=[tag1, tag2]`` to ``ContactFactory`` to wire up ``ContactTag`` rows.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import factory
from factory.alchemy import SQLAlchemyModelFactory
from faker import Faker

from app.core.encryption import hash_phone, hash_value
from app.models.agent import Agent
from app.models.appointment import Appointment, AppointmentStatus
from app.models.campaign import (
    Campaign,
    CampaignContact,
    CampaignContactStatus,
    CampaignStatus,
    CampaignType,
)
from app.models.contact import Contact
from app.models.conversation import (
    Conversation,
    ConversationStatus,
    Message,
    MessageChannel,
    MessageDirection,
    MessageStatus,
)
from app.models.opportunity import Opportunity
from app.models.phone_number import PhoneNumber, PhoneNumberHealthStatus, TrustTier
from app.models.pipeline import Pipeline, PipelineStage
from app.models.tag import ContactTag, Tag
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership

fake = Faker()


class BaseFactory(SQLAlchemyModelFactory):
    """Shared base. ``sqlalchemy_session`` is set by ``bind_factories_to_session``."""

    class Meta:
        abstract = True
        sqlalchemy_session = None  # set by bind_factories_to_session
        sqlalchemy_session_persistence = "flush"


def _now() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------------------
# User & Workspace
# ---------------------------------------------------------------------------


class UserFactory(BaseFactory):
    class Meta:
        model = User

    email = factory.Sequence(lambda n: f"user{n}@example.com")
    email_hash = factory.LazyAttribute(lambda obj: hash_value(obj.email))
    hashed_password = "$argon2id$v=19$m=65536,t=3,p=4$placeholderhashforfactorytests"
    full_name = factory.Faker("name")
    phone_number = factory.Sequence(lambda n: f"+1555000{n:04d}")
    phone_hash = factory.LazyAttribute(lambda obj: hash_phone(obj.phone_number))
    timezone = "America/New_York"
    is_active = True
    is_superuser = False
    notification_email = True
    notification_sms = True
    notification_push = True
    notification_push_calls = True
    notification_push_messages = True
    notification_push_voicemail = True
    notification_push_appointments = True
    created_at = factory.LazyFunction(_now)
    updated_at = factory.LazyFunction(_now)


class WorkspaceFactory(BaseFactory):
    class Meta:
        model = Workspace

    id = factory.LazyFunction(uuid.uuid4)
    name = factory.Faker("company")
    slug = factory.Sequence(lambda n: f"workspace-{n}")
    description = factory.Faker("sentence")
    settings = factory.LazyFunction(lambda: {"timezone": "America/New_York"})
    is_active = True
    created_at = factory.LazyFunction(_now)
    updated_at = factory.LazyFunction(_now)

    @factory.post_generation
    def members(self, create: bool, extracted: list[User] | None, **kwargs: Any) -> None:
        """Attach users as members. Usage: ``WorkspaceFactory(members=[user1, user2])``."""
        if not extracted:
            return
        for user in extracted:
            membership = WorkspaceMembershipFactory.build(
                user=user,
                workspace=self,
                role=kwargs.get("role", "member"),
            )
            if create and self._sa_instance_state.session is not None:
                self._sa_instance_state.session.add(membership)


class WorkspaceMembershipFactory(BaseFactory):
    class Meta:
        model = WorkspaceMembership

    id = factory.LazyFunction(uuid.uuid4)
    user = factory.SubFactory(UserFactory)
    workspace = factory.SubFactory(WorkspaceFactory)
    user_id = factory.SelfAttribute("user.id")
    workspace_id = factory.SelfAttribute("workspace.id")
    role = "member"
    is_default = False
    created_at = factory.LazyFunction(_now)


# ---------------------------------------------------------------------------
# Contact, Tag, ContactTag
# ---------------------------------------------------------------------------


class ContactFactory(BaseFactory):
    class Meta:
        model = Contact

    workspace = factory.SubFactory(WorkspaceFactory)
    workspace_id = factory.SelfAttribute("workspace.id")

    first_name = factory.Faker("first_name")
    last_name = factory.Faker("last_name")
    email = factory.Sequence(lambda n: f"contact{n}@example.com")
    email_hash = factory.LazyAttribute(lambda obj: hash_value(obj.email) if obj.email else None)
    phone_number = factory.Sequence(lambda n: f"+1555111{n:04d}")
    phone_hash = factory.LazyAttribute(lambda obj: hash_phone(obj.phone_number))
    company_name = factory.Faker("company")

    status = "new"
    lead_score = 0
    is_qualified = False
    qualification_signals = None
    qualified_at = None

    notes = None
    important_dates = None

    noshow_count = 0
    last_appointment_status = None
    source = None
    source_campaign_id = None

    last_engaged_at = None
    engagement_score = 0

    created_at = factory.LazyFunction(_now)
    updated_at = factory.LazyFunction(_now)

    @factory.post_generation
    def tag_objects(self, create: bool, extracted: list[Tag] | None, **kwargs: Any) -> None:
        """Wire up ContactTag rows. Usage: ``ContactFactory(tag_objects=[tag1, tag2])``."""
        if not extracted:
            return
        for tag in extracted:
            link = ContactTagFactory.build(contact=self, tag=tag)
            if create and self._sa_instance_state.session is not None:
                self._sa_instance_state.session.add(link)


class TagFactory(BaseFactory):
    """Tag has no ``workspace`` relationship, only ``workspace_id``.

    Pass ``workspace_id=`` directly, or let the factory generate a fresh UUID.
    """

    class Meta:
        model = Tag

    id = factory.LazyFunction(uuid.uuid4)
    workspace_id = factory.LazyFunction(uuid.uuid4)
    name = factory.Sequence(lambda n: f"tag-{n}")
    color = "#6366f1"
    created_at = factory.LazyFunction(_now)
    updated_at = factory.LazyFunction(_now)


class ContactTagFactory(BaseFactory):
    class Meta:
        model = ContactTag

    id = factory.LazyFunction(uuid.uuid4)
    contact = factory.SubFactory(ContactFactory)
    tag = factory.SubFactory(TagFactory)
    contact_id = factory.SelfAttribute("contact.id")
    tag_id = factory.SelfAttribute("tag.id")
    created_at = factory.LazyFunction(_now)


# ---------------------------------------------------------------------------
# Agent, PhoneNumber
# ---------------------------------------------------------------------------


class AgentFactory(BaseFactory):
    class Meta:
        model = Agent

    id = factory.LazyFunction(uuid.uuid4)
    workspace = factory.SubFactory(WorkspaceFactory)
    workspace_id = factory.SelfAttribute("workspace.id")

    name = factory.Faker("name")
    description = factory.Faker("sentence")
    channel_mode = "both"

    voice_provider = "openai"
    voice_id = "alloy"
    language = "en-US"

    turn_detection_mode = "server_vad"
    turn_detection_threshold = 0.5
    silence_duration_ms = 500

    system_prompt = "You are a helpful assistant."
    temperature = 0.7
    max_tokens = 2000

    initial_greeting = "Hello, how can I help you today?"
    text_response_delay_ms = 30_000
    text_max_context_messages = 20

    enabled_tools = factory.LazyFunction(list)
    tool_settings = factory.LazyFunction(dict)

    enable_ivr_navigation = False
    ivr_loop_threshold = 2
    ivr_silence_duration_ms = 3000
    ivr_post_dtmf_cooldown_ms = 3000
    ivr_menu_buffer_silence_ms = 2000

    enable_recording = True

    reminder_enabled = True
    reminder_minutes_before = 30
    reminder_offsets = factory.LazyFunction(lambda: [1440, 60])

    noshow_sms_enabled = False
    post_meeting_sms_enabled = False
    value_reinforcement_enabled = False
    value_reinforcement_offset_minutes = 60
    never_booked_reengagement_enabled = False
    never_booked_delay_days = 3
    never_booked_max_attempts = 3
    noshow_reengagement_enabled = False

    is_active = True
    public_id = None
    embed_enabled = False
    allowed_domains = factory.LazyFunction(list)
    embed_settings = factory.LazyFunction(dict)

    total_calls = 0
    total_messages = 0

    auto_suggest = False
    auto_activate = False
    auto_improve_min_calls = 10
    auto_evaluate = False

    created_at = factory.LazyFunction(_now)
    updated_at = factory.LazyFunction(_now)


class PhoneNumberFactory(BaseFactory):
    class Meta:
        model = PhoneNumber

    id = factory.LazyFunction(uuid.uuid4)
    workspace = factory.SubFactory(WorkspaceFactory)
    workspace_id = factory.SelfAttribute("workspace.id")

    phone_number = factory.Sequence(lambda n: f"+1555222{n:04d}")
    friendly_name = factory.Faker("city")

    sms_enabled = True
    voice_enabled = True
    mms_enabled = False

    assigned_agent_id = None
    is_active = True

    trust_tier = TrustTier.LOW_VOLUME
    daily_limit = 75
    hourly_limit = 10
    messages_per_second = 1.0

    health_status = PhoneNumberHealthStatus.HEALTHY

    messages_sent_7d = 0
    messages_delivered_7d = 0
    hard_bounces_7d = 0
    soft_bounces_7d = 0
    spam_complaints_7d = 0
    opt_outs_7d = 0

    delivery_rate = 0.0
    bounce_rate = 0.0
    complaint_rate = 0.0

    warming_stage = 0
    quarantine_reviewed = False

    created_at = factory.LazyFunction(_now)
    updated_at = factory.LazyFunction(_now)


# ---------------------------------------------------------------------------
# Conversation & Message
# ---------------------------------------------------------------------------


class ConversationFactory(BaseFactory):
    class Meta:
        model = Conversation

    id = factory.LazyFunction(uuid.uuid4)
    workspace = factory.SubFactory(WorkspaceFactory)
    workspace_id = factory.SelfAttribute("workspace.id")

    contact = factory.SubFactory(ContactFactory, workspace=factory.SelfAttribute("..workspace"))
    contact_id = factory.SelfAttribute("contact.id")

    workspace_phone = factory.Sequence(lambda n: f"+1555333{n:04d}")
    contact_phone = factory.Sequence(lambda n: f"+1555444{n:04d}")

    status = ConversationStatus.ACTIVE
    channel = "sms"

    ai_enabled = True
    ai_paused = False
    ai_paused_until = None

    unread_count = 0
    last_message_preview = None
    last_message_at = None
    last_message_direction = None

    initiated_by = "system"

    followup_enabled = False
    followup_delay_hours = 24
    followup_max_count = 3
    followup_count_sent = 0

    created_at = factory.LazyFunction(_now)
    updated_at = factory.LazyFunction(_now)

    @factory.post_generation
    def messages(self, create: bool, extracted: int | list[Message] | None, **kwargs: Any) -> None:
        """Attach messages.

        ``messages=3`` builds 3 inbound messages; ``messages=[m1, m2]`` attaches
        pre-built ones. Both modes set ``conversation_id`` to ``self.id``.
        """
        if not extracted:
            return
        items: list[Message]
        if isinstance(extracted, int):
            items = [MessageFactory.build(conversation=self) for _ in range(extracted)]
        else:
            for m in extracted:
                m.conversation_id = self.id
            items = list(extracted)
        if create and self._sa_instance_state.session is not None:
            for m in items:
                self._sa_instance_state.session.add(m)


class MessageFactory(BaseFactory):
    class Meta:
        model = Message

    id = factory.LazyFunction(uuid.uuid4)
    conversation = factory.SubFactory(ConversationFactory)
    conversation_id = factory.SelfAttribute("conversation.id")

    direction = MessageDirection.OUTBOUND
    channel = MessageChannel.SMS
    body = factory.Faker("sentence")
    subject = None
    recipient_email = None
    sender_email = None

    status = MessageStatus.SENT

    provider_message_id = None
    error_code = None
    error_message = None
    bounce_type = None
    bounce_category = None
    carrier_error_code = None
    carrier_name = None

    from_phone_number_id = None

    is_ai = False
    agent_id = None
    campaign_id = None

    duration_seconds = None
    recording_url = None
    transcript = None
    booking_outcome = None

    prompt_version_id = None

    sent_at = factory.LazyFunction(_now)
    delivered_at = None
    created_at = factory.LazyFunction(_now)


# ---------------------------------------------------------------------------
# Campaign & CampaignContact
# ---------------------------------------------------------------------------


class CampaignFactory(BaseFactory):
    class Meta:
        model = Campaign

    id = factory.LazyFunction(uuid.uuid4)
    workspace = factory.SubFactory(WorkspaceFactory)
    workspace_id = factory.SelfAttribute("workspace.id")

    agent_id = None
    offer_id = None
    voice_agent_id = None
    sms_fallback_agent_id = None

    name = factory.Faker("catch_phrase")
    description = factory.Faker("sentence")
    campaign_type = CampaignType.SMS
    status = CampaignStatus.DRAFT

    from_phone_number = factory.Sequence(lambda n: f"+1555555{n:04d}")
    use_number_pool = False

    initial_message = "Hello {first_name}, can we chat?"

    ai_enabled = True
    qualification_criteria = None

    scheduled_start = None
    scheduled_end = None
    sending_hours_start = None
    sending_hours_end = None
    sending_days = None
    timezone = "America/New_York"

    messages_per_minute = 10
    max_messages_per_contact = 5

    follow_up_enabled = False
    follow_up_delay_hours = 24
    follow_up_message = None
    max_follow_ups = 2

    voice_connection_id = None
    enable_machine_detection = True
    max_call_duration_seconds = 120
    calls_per_minute = 5

    sms_fallback_enabled = True
    sms_fallback_template = None
    sms_fallback_use_ai = False

    total_contacts = 0
    messages_sent = 0
    messages_delivered = 0
    messages_failed = 0
    replies_received = 0
    contacts_qualified = 0
    contacts_opted_out = 0
    appointments_booked = 0
    appointments_completed = 0
    links_clicked = 0

    guarantee_target = None
    guarantee_window_days = None
    guarantee_status = None

    calls_attempted = 0
    calls_answered = 0
    calls_no_answer = 0
    calls_busy = 0
    calls_voicemail = 0
    sms_fallbacks_sent = 0

    emails_sent = 0
    emails_delivered = 0
    emails_bounced = 0
    emails_opened = 0
    emails_clicked = 0
    emails_unsubscribed = 0

    last_error = None
    error_count = 0
    last_error_at = None

    started_at = None
    completed_at = None
    created_at = factory.LazyFunction(_now)
    updated_at = factory.LazyFunction(_now)

    @factory.post_generation
    def contacts(self, create: bool, extracted: list[Contact] | None, **kwargs: Any) -> None:
        """Attach contacts via CampaignContact rows. ``CampaignFactory(contacts=[c1, c2])``."""
        if not extracted:
            return
        for contact in extracted:
            link = CampaignContactFactory.build(campaign=self, contact=contact)
            if create and self._sa_instance_state.session is not None:
                self._sa_instance_state.session.add(link)


class CampaignContactFactory(BaseFactory):
    class Meta:
        model = CampaignContact

    id = factory.LazyFunction(uuid.uuid4)
    campaign = factory.SubFactory(CampaignFactory)
    campaign_id = factory.SelfAttribute("campaign.id")
    contact = factory.SubFactory(ContactFactory)
    contact_id = factory.SelfAttribute("contact.id")
    conversation_id = None

    status = CampaignContactStatus.PENDING

    messages_sent = 0
    messages_received = 0
    follow_ups_sent = 0

    first_sent_at = None
    last_sent_at = None
    last_reply_at = None
    next_follow_up_at = None

    is_qualified = False
    qualification_notes = None
    qualified_at = None

    opted_out = False
    opted_out_at = None

    priority = 0

    call_attempts = 0
    last_call_at = None
    last_call_status = None
    call_duration_seconds = None
    call_message_id = None

    sms_fallback_sent = False
    sms_fallback_sent_at = None
    sms_fallback_message_id = None

    last_error = None

    created_at = factory.LazyFunction(_now)
    updated_at = factory.LazyFunction(_now)


# ---------------------------------------------------------------------------
# Appointment
# ---------------------------------------------------------------------------


class AppointmentFactory(BaseFactory):
    class Meta:
        model = Appointment

    workspace = factory.SubFactory(WorkspaceFactory)
    workspace_id = factory.SelfAttribute("workspace.id")
    contact = factory.SubFactory(ContactFactory, workspace=factory.SelfAttribute("..workspace"))
    contact_id = factory.SelfAttribute("contact.id")

    agent_id = None
    message_id = None
    campaign_id = None

    scheduled_at = factory.LazyFunction(lambda: _now() + timedelta(days=1))
    duration_minutes = 30
    status = AppointmentStatus.SCHEDULED

    service_type = None
    notes = None

    calcom_booking_uid = None
    calcom_booking_id = None
    calcom_event_type_id = None
    sync_status = "pending"
    last_synced_at = None
    sync_error = None

    reminder_sent_at = None
    reminders_sent = factory.LazyFunction(list)

    created_at = factory.LazyFunction(_now)
    updated_at = factory.LazyFunction(_now)


# ---------------------------------------------------------------------------
# Pipeline, PipelineStage, Opportunity
# ---------------------------------------------------------------------------


class PipelineFactory(BaseFactory):
    class Meta:
        model = Pipeline

    id = factory.LazyFunction(uuid.uuid4)
    workspace = factory.SubFactory(WorkspaceFactory)
    workspace_id = factory.SelfAttribute("workspace.id")

    name = factory.Faker("bs")
    description = factory.Faker("sentence")
    is_active = True

    created_at = factory.LazyFunction(_now)
    updated_at = factory.LazyFunction(_now)

    @factory.post_generation
    def stages(
        self, create: bool, extracted: int | list[PipelineStage] | None, **kwargs: Any
    ) -> None:
        """Attach stages.

        ``stages=3`` builds 3 default stages; ``stages=[s1, s2]`` attaches given ones.
        """
        if not extracted:
            return
        items: list[PipelineStage]
        if isinstance(extracted, int):
            items = [
                PipelineStageFactory.build(pipeline=self, order=i, name=f"Stage {i + 1}")
                for i in range(extracted)
            ]
        else:
            for s in extracted:
                s.pipeline_id = self.id
            items = list(extracted)
        if create and self._sa_instance_state.session is not None:
            for s in items:
                self._sa_instance_state.session.add(s)


class PipelineStageFactory(BaseFactory):
    class Meta:
        model = PipelineStage

    id = factory.LazyFunction(uuid.uuid4)
    pipeline = factory.SubFactory(PipelineFactory)
    pipeline_id = factory.SelfAttribute("pipeline.id")

    name = factory.Sequence(lambda n: f"Stage {n}")
    description = None
    order = 0
    probability = 50
    stage_type = "active"

    created_at = factory.LazyFunction(_now)
    updated_at = factory.LazyFunction(_now)


class OpportunityFactory(BaseFactory):
    class Meta:
        model = Opportunity

    id = factory.LazyFunction(uuid.uuid4)
    workspace = factory.SubFactory(WorkspaceFactory)
    workspace_id = factory.SelfAttribute("workspace.id")

    pipeline = factory.SubFactory(PipelineFactory, workspace=factory.SelfAttribute("..workspace"))
    pipeline_id = factory.SelfAttribute("pipeline.id")
    stage = factory.SubFactory(PipelineStageFactory, pipeline=factory.SelfAttribute("..pipeline"))
    stage_id = factory.SelfAttribute("stage.id")

    primary_contact_id = None
    assigned_user_id = None

    name = factory.Faker("catch_phrase")
    description = factory.Faker("sentence")

    amount = factory.LazyFunction(lambda: Decimal("1000.00"))
    currency = "USD"
    probability = 50

    expected_close_date = factory.LazyFunction(lambda: date.today() + timedelta(days=30))
    closed_date = None
    closed_by_id = None

    stage_changed_at = factory.LazyFunction(_now)

    source = None
    status = "open"
    lost_reason = None
    is_active = True

    created_at = factory.LazyFunction(_now)
    updated_at = factory.LazyFunction(_now)


# ---------------------------------------------------------------------------
# Session binding
# ---------------------------------------------------------------------------


_ALL_FACTORIES: tuple[type[BaseFactory], ...] = (
    UserFactory,
    WorkspaceFactory,
    WorkspaceMembershipFactory,
    ContactFactory,
    TagFactory,
    ContactTagFactory,
    AgentFactory,
    PhoneNumberFactory,
    ConversationFactory,
    MessageFactory,
    CampaignFactory,
    CampaignContactFactory,
    AppointmentFactory,
    PipelineFactory,
    PipelineStageFactory,
    OpportunityFactory,
)


def bind_factories_to_session(session: Any) -> None:
    """Point every factory at ``session`` so ``.create()`` persists.

    Pass the *sync* SQLAlchemy session (or any object factory_boy can call
    ``.add()`` / ``.flush()`` on). For async tests, factories work best in
    ``.build()`` mode — keep the binding ``None`` and only persist explicitly.
    """
    for fact in _ALL_FACTORIES:
        fact._meta.sqlalchemy_session = session


def reset_factory_sequences() -> None:
    """Reset Sequence counters so tests in any order produce the same IDs."""
    for fact in _ALL_FACTORIES:
        fact.reset_sequence()
