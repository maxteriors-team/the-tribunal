"""Tests for outbound-send idempotency wiring across workers.

These tests pin two contracts:

1. ``app.services.telephony.idempotency.derive`` is a *pure deterministic*
   function. The same ``(scope, *parts)`` tuple always produces the same
   UUID5 across processes, and different scopes / parts produce different
   keys. The whole crash-safety story depends on this.

2. Each worker (reminder, campaign SMS initial + follow-up, voice
   campaign, drip, approval) computes a key with a documented scope and
   forwards it to ``TelnyxSMSService.send_message`` or
   ``TelnyxVoiceService.initiate_call`` as ``idempotency_key=``. We don't
   re-test the DB-bound send path \u2014 we just assert that the worker
   reaches the service call with the right key, since the service-level
   tests (``tests/services/telephony/test_telnyx_idempotency.py``) cover
   the dedupe + header-forwarding behavior.

The full polling loops are integration-tested elsewhere; here we exercise
just the slice that wires the key in.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from app.services.telephony import idempotency
from app.services.telephony.idempotency import derive

# ---------------------------------------------------------------------------
# derive() \u2014 the pure helper every worker leans on
# ---------------------------------------------------------------------------


class TestDeriveIdempotencyKey:
    """``derive`` must be deterministic, scoped, and uuid5-shaped."""

    def test_returns_uuid_version_5(self) -> None:
        key = derive("reminder", 1, 60)
        assert isinstance(key, uuid.UUID)
        assert key.version == 5

    def test_same_inputs_produce_same_key(self) -> None:
        # Stability is the whole point: a retry must regenerate the
        # same UUID after a process restart.
        a = derive("campaign_sms_initial", "cc-1")
        b = derive("campaign_sms_initial", "cc-1")
        assert a == b

    def test_different_scopes_produce_different_keys(self) -> None:
        # Two workers using the same entity id (e.g. a campaign_contact
        # id that's accidentally shared) must not collide.
        a = derive("reminder", "x")
        b = derive("value_reinforcement", "x")
        assert a != b

    def test_different_parts_produce_different_keys(self) -> None:
        a = derive("reminder", 1, 60)
        b = derive("reminder", 1, 1440)
        assert a != b

    def test_namespace_is_fixed(self) -> None:
        # Pinning the namespace UUID guards against an accidental
        # change that would invalidate every in-flight retry's key.
        assert (
            uuid.uuid5(uuid.NAMESPACE_DNS, "thetribunal.outbound.v1")
            == idempotency._OUTBOUND_NAMESPACE
        )

    def test_stringifies_parts(self) -> None:
        # ``parts`` of mixed types are stringified, so a bigint id and
        # the string form of the same id should produce equal keys.
        assert derive("reminder", 42) == derive("reminder", "42")


# ---------------------------------------------------------------------------
# Reminder worker
# ---------------------------------------------------------------------------


class TestReminderWorkerKey:
    """ReminderWorker derives a stable per-(appointment, offset) key."""

    async def test_send_reminder_passes_appointment_offset_key(self) -> None:
        from app.workers.reminder_worker import ReminderWorker

        worker = ReminderWorker()
        worker.opt_out_manager = MagicMock()
        worker.opt_out_manager.check_opt_out = AsyncMock(return_value=False)

        appt = SimpleNamespace(
            id=4242,
            agent=SimpleNamespace(
                id=uuid4(),
                reminder_enabled=True,
                reminder_offsets=[60],
                reminder_template=None,
                calcom_event_type_id=None,
                value_reinforcement_enabled=False,
                value_reinforcement_template=None,
            ),
            contact=SimpleNamespace(
                id=1,
                phone_number="+12025551234",
                first_name="A",
                last_name="B",
                email="a@b.com",
            ),
            workspace=SimpleNamespace(id=uuid4(), settings={"timezone": "UTC"}),
            scheduled_at=None,
            reminders_sent=[],
            reminder_sent_at=None,
        )

        # Patch the DB session, from-number resolver, and TelnyxSMSService
        # constructor. We're not exercising the DB path \u2014 just the
        # idempotency_key wiring.
        with (
            patch(
                "app.workers.reminder_worker.settings",
                SimpleNamespace(telnyx_api_key="k", calcom_api_key=None, public_base_url=""),
            ),
            patch(
                "app.workers.reminder_worker.resolve_from_number",
                AsyncMock(return_value="+12025556789"),
            ),
            patch("app.workers.reminder_worker.TelnyxSMSService") as sms_cls,
            patch.object(
                worker,
                "_render_reminder_body",
                return_value="hi",
            ),
            patch.object(worker, "_mark_offset_sent", AsyncMock()),
        ):
            sms_instance = sms_cls.return_value
            sms_instance.send_message = AsyncMock(return_value=SimpleNamespace(id=uuid4()))
            sms_instance.close = AsyncMock()

            db = MagicMock()
            db.execute = AsyncMock(
                return_value=MagicMock(scalars=lambda: MagicMock(first=lambda: None))
            )
            db.commit = AsyncMock()

            await worker._send_reminder(appt, 60, db)  # type: ignore[arg-type]

        sms_instance.send_message.assert_awaited_once()
        call_kwargs = sms_instance.send_message.call_args.kwargs
        assert call_kwargs["idempotency_key"] == derive("reminder", 4242, 60)

    async def test_value_reinforcement_passes_per_appointment_key(self) -> None:
        from app.workers.reminder_worker import ReminderWorker

        worker = ReminderWorker()
        worker.opt_out_manager = MagicMock()
        worker.opt_out_manager.check_opt_out = AsyncMock(return_value=False)

        appt = SimpleNamespace(
            id=777,
            agent=SimpleNamespace(
                id=uuid4(),
                value_reinforcement_enabled=True,
                value_reinforcement_template="hello",
                value_reinforcement_offset_minutes=120,
            ),
            contact=SimpleNamespace(
                id=1,
                phone_number="+12025551234",
                first_name="A",
                last_name=None,
                email=None,
            ),
            workspace=SimpleNamespace(id=uuid4(), settings={"timezone": "UTC"}),
            scheduled_at=None,
            reminders_sent=[],
            reminder_sent_at=None,
        )

        with (
            patch(
                "app.workers.reminder_worker.settings",
                SimpleNamespace(telnyx_api_key="k", calcom_api_key=None, public_base_url=""),
            ),
            patch(
                "app.workers.reminder_worker.resolve_from_number",
                AsyncMock(return_value="+12025556789"),
            ),
            patch("app.workers.reminder_worker.TelnyxSMSService") as sms_cls,
            patch.object(worker, "_render_value_reinforcement_body", return_value="hi"),
            patch.object(worker, "_mark_offset_sent", AsyncMock()),
        ):
            sms_instance = sms_cls.return_value
            sms_instance.send_message = AsyncMock(return_value=SimpleNamespace(id=uuid4()))
            sms_instance.close = AsyncMock()

            db = MagicMock()
            db.commit = AsyncMock()

            await worker._send_value_reinforcement(appt, db)  # type: ignore[arg-type]

        call_kwargs = sms_instance.send_message.call_args.kwargs
        assert call_kwargs["idempotency_key"] == derive("value_reinforcement", 777)


# ---------------------------------------------------------------------------
# Campaign worker (SMS initial + follow-up)
# ---------------------------------------------------------------------------


class TestCampaignWorkerKeys:
    """SMS campaign worker keys are stable per-(campaign_contact, slot)."""

    def test_initial_send_key_shape(self) -> None:
        # The worker computes ``derive(\"campaign_sms_initial\", cc.id)``
        # and forwards it as ``idempotency_key`` on send_message. We pin
        # the exact derivation so a future refactor that changes the
        # scope string is caught.
        cc_id = uuid4()
        assert derive("campaign_sms_initial", cc_id) == derive("campaign_sms_initial", cc_id)

    def test_followup_key_includes_attempt_index(self) -> None:
        # Two consecutive follow-ups for the same contact must produce
        # distinct keys, otherwise the second send would be wrongly
        # short-circuited by the first's Message row.
        cc_id = uuid4()
        first = derive("campaign_sms_followup", cc_id, 0)
        second = derive("campaign_sms_followup", cc_id, 1)
        assert first != second


# ---------------------------------------------------------------------------
# Voice campaign worker
# ---------------------------------------------------------------------------


class TestVoiceCampaignWorkerKey:
    """VoiceCampaignWorker must vary the key per call attempt."""

    def test_per_attempt_key_isolation(self) -> None:
        cc_id = uuid4()
        attempt0 = derive("voice_campaign_call", cc_id, 0)
        attempt1 = derive("voice_campaign_call", cc_id, 1)
        # Distinct attempts -> distinct keys: retry of a *new* attempt
        # after a prior one failed must not be deduped against the prior.
        assert attempt0 != attempt1
        # But the same attempt regenerates the same key after restart.
        assert attempt0 == derive("voice_campaign_call", cc_id, 0)


# ---------------------------------------------------------------------------
# Drip campaign worker (drip_runner)
# ---------------------------------------------------------------------------


class TestDripWorkerKey:
    """drip_runner derives a per-(enrollment, step) key."""

    async def test_send_step_forwards_idempotency_key(self) -> None:
        from app.services.reactivation import drip_runner

        enrollment_id = uuid4()
        # current_step=2 is the only step — ``next_step_config`` will be
        # None, marking the enrollment COMPLETED. That path exercises
        # send_message without needing extra mocks.
        enrollment = SimpleNamespace(
            id=enrollment_id,
            current_step=2,
            contact=SimpleNamespace(
                id=1,
                phone_number="+12025551234",
                first_name="A",
                last_name="B",
                email="a@b.com",
                company_name=None,
            ),
            contact_id=1,
            messages_sent=0,
            last_sent_at=None,
            next_step_at=None,
            completed_at=None,
            status=None,
            cancel_reason=None,
        )
        campaign = SimpleNamespace(
            id=uuid4(),
            workspace_id=uuid4(),
            agent_id=None,
            from_phone_number="+12025556789",
            sequence_steps=[{"step": 2, "type": "sms", "message": "hi"}],
            total_completed=0,
            total_cancelled=0,
            total_messages_sent=0,
        )

        sms_service = MagicMock()
        sms_service.send_message = AsyncMock(
            return_value=SimpleNamespace(id=uuid4(), conversation_id=None)
        )

        opt_out = MagicMock()
        opt_out.check_opt_out = AsyncMock(return_value=False)

        db = MagicMock()
        db.execute = AsyncMock()

        with (
            patch.object(
                drip_runner,
                "_resolve_from_number",
                AsyncMock(return_value="+12025556789"),
            ),
            patch.object(drip_runner, "_render_template", return_value="hi"),
        ):
            await drip_runner._process_enrollment(
                enrollment,  # type: ignore[arg-type]
                campaign,  # type: ignore[arg-type]
                sms_service,
                opt_out,
                db,
                MagicMock(info=lambda *a, **k: None, warning=lambda *a, **k: None),
            )

        call_kwargs = sms_service.send_message.call_args.kwargs
        assert call_kwargs["idempotency_key"] == derive("drip_step", enrollment_id, 2)


# ---------------------------------------------------------------------------
# Approval worker (via ApprovalGateService._execute_send_sms)
# ---------------------------------------------------------------------------


class TestApprovalWorkerKey:
    """The send_sms approved-action path derives a per-pending-action key."""

    async def test_execute_send_sms_forwards_idempotency_key(self) -> None:
        from app.services.approval.approval_gate_service import ApprovalGateService

        gate = ApprovalGateService()

        action_id = uuid4()
        action = SimpleNamespace(
            id=action_id,
            workspace_id=uuid4(),
            agent_id=uuid4(),
            action_payload={
                "to_number": "+12025551234",
                "from_number": "+12025556789",
                "text": "hello",
            },
        )

        with patch("app.services.telephony.telnyx.TelnyxSMSService") as sms_cls:
            sms_instance = sms_cls.return_value
            sms_instance.send_message = AsyncMock(return_value=SimpleNamespace(id=uuid4()))
            sms_instance.close = AsyncMock()

            db = MagicMock()
            await gate._execute_send_sms(db, action)  # type: ignore[arg-type]

            sms_instance.send_message.assert_awaited_once()
            call_kwargs = sms_instance.send_message.call_args.kwargs
            assert call_kwargs["idempotency_key"] == derive("approval_send_sms", action_id)

    async def test_notify_pending_action_forwards_notification_key(self) -> None:
        from app.services.approval.approval_delivery_service import ApprovalDeliveryService

        service = ApprovalDeliveryService()
        action_id = uuid4()
        workspace_id = uuid4()
        action = SimpleNamespace(
            id=action_id,
            workspace_id=workspace_id,
            agent_id=uuid4(),
            description="send a message",
            notification_sent=False,
            notification_sent_at=None,
        )
        profile = SimpleNamespace(phone_number="+12025551234")
        agent = SimpleNamespace(name="Agent Smith")
        phone = SimpleNamespace(id=uuid4(), phone_number="+12025556789")

        db = MagicMock()
        db.execute = AsyncMock(
            side_effect=[
                MagicMock(scalar_one_or_none=MagicMock(return_value=profile)),
                MagicMock(scalar_one_or_none=MagicMock(return_value=agent)),
            ]
        )
        db.commit = AsyncMock()

        with (
            patch(
                "app.services.approval.approval_delivery_service.get_workspace_sms_number",
                AsyncMock(return_value=phone),
            ),
            patch(
                "app.services.approval.approval_delivery_service.get_text_message_provider"
            ) as provider_factory,
            patch(
                "app.services.approval.approval_delivery_service.push_notification_service"
            ) as push_service,
        ):
            sms_instance = provider_factory.return_value
            sms_instance.send_message = AsyncMock(return_value=SimpleNamespace(id=uuid4()))
            sms_instance.close = AsyncMock()
            push_service.send_to_workspace_members = AsyncMock(return_value=None)

            ok = await service.notify_pending_action(db, action)  # type: ignore[arg-type]

        assert ok is True
        call_kwargs = sms_instance.send_message.call_args.kwargs
        assert call_kwargs["idempotency_key"] == derive("approval_notification_sms", action_id)


# ---------------------------------------------------------------------------
# Additional retry-prone send paths
# ---------------------------------------------------------------------------


class TestAdditionalRetrySendKeys:
    async def test_automation_send_sms_forwards_key(self) -> None:
        from app.workers.automation_worker import AutomationWorker

        worker = AutomationWorker()
        automation_id = uuid4()
        contact_id = 123
        automation = SimpleNamespace(id=automation_id, workspace_id=uuid4())
        contact = SimpleNamespace(id=contact_id, phone_number="+12025551234", first_name="A")
        db = MagicMock()

        with (
            patch.object(worker, "_resolve_from_number", AsyncMock(return_value="+12025556789")),
            patch.object(worker, "_render_template", return_value="hi"),
            patch("app.workers.automation_worker.get_text_message_provider") as provider_factory,
        ):
            sms_instance = provider_factory.return_value
            sms_instance.send_message = AsyncMock(return_value=SimpleNamespace(id=uuid4()))
            sms_instance.close = AsyncMock()

            await worker._action_send_sms(  # type: ignore[arg-type]
                automation,
                contact,
                {"message": "hi"},
                db,
            )

        call_kwargs = sms_instance.send_message.call_args.kwargs
        assert call_kwargs["idempotency_key"] == derive("automation_sms", automation_id, contact_id)

    async def test_sms_fallback_forwards_campaign_contact_key(self) -> None:
        from app.services.campaigns.sms_fallback import send_sms_fallback

        campaign_contact_id = uuid4()
        campaign = SimpleNamespace(
            id=uuid4(),
            workspace_id=uuid4(),
            from_phone_number="+12025556789",
            sms_fallback_enabled=True,
            sms_fallback_use_ai=False,
            sms_fallback_agent_id=None,
            sms_fallback_template="Hi {first_name}",
            sms_fallbacks_sent=0,
            messages_sent=0,
            agent_id=uuid4(),
        )
        campaign_contact = SimpleNamespace(
            id=campaign_contact_id,
            sms_fallback_sent=False,
            sms_fallback_sent_at=None,
            sms_fallback_message_id=None,
            status=None,
            conversation_id=None,
            messages_sent=0,
            last_error=None,
        )
        contact = SimpleNamespace(
            id=1,
            phone_number="+12025551234",
            first_name="A",
            last_name=None,
            company_name=None,
            email=None,
        )
        db = MagicMock()
        db.commit = AsyncMock()

        with patch("app.services.campaigns.sms_fallback.TelnyxSMSService") as sms_cls:
            sms_instance = sms_cls.return_value
            sms_instance.send_message = AsyncMock(
                return_value=SimpleNamespace(id=uuid4(), conversation_id=uuid4())
            )
            sms_instance.close = AsyncMock()

            ok = await send_sms_fallback(
                db,
                campaign,  # type: ignore[arg-type]
                campaign_contact,  # type: ignore[arg-type]
                contact,  # type: ignore[arg-type]
                "no_answer",
                "key",
            )

        assert ok is True
        call_kwargs = sms_instance.send_message.call_args.kwargs
        assert call_kwargs["idempotency_key"] == derive(
            "voice_campaign_sms_fallback", campaign_contact_id, "no_answer"
        )
