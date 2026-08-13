"""Contact-level email opt-out: tokens, and the gate on the workflow send path.

The gate is the point. Before it, a workflow could email someone indefinitely
with no way for them to stop it, because the only email opt-out in the product
was scoped to a single campaign enrollment that workflow mail does not have.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.email_layout import EmailCategory
from app.services.email_opt_out import (
    build_email_unsubscribe_url,
    make_email_unsubscribe_token,
    verify_email_unsubscribe_token,
)


class TestTokens:
    def test_round_trips_a_contact_id(self):
        assert verify_email_unsubscribe_token(make_email_unsubscribe_token(4242)) == 4242

    def test_tampered_payload_is_rejected(self):
        token = make_email_unsubscribe_token(1)
        payload, signature = token.split(".", 1)
        forged = make_email_unsubscribe_token(999).split(".", 1)[0]
        assert verify_email_unsubscribe_token(f"{forged}.{signature}") is None

    def test_tampered_signature_is_rejected(self):
        payload = make_email_unsubscribe_token(1).split(".", 1)[0]
        assert verify_email_unsubscribe_token(f"{payload}.deadbeef") is None

    def test_garbage_is_rejected_without_raising(self):
        for bad in ("", ".", "no-separator", "a.b.c", "!!!.???"):
            assert verify_email_unsubscribe_token(bad) is None

    def test_campaign_token_cannot_be_replayed_here(self):
        """Both schemes share a signing key; scoping keeps them non-fungible."""
        from app.services.campaigns.email_unsubscribe import make_unsubscribe_token

        campaign_token = make_unsubscribe_token(uuid.uuid4())
        assert verify_email_unsubscribe_token(campaign_token) is None

    def test_url_contains_the_token(self, monkeypatch: pytest.MonkeyPatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "frontend_url", "https://app.example.com")
        url = build_email_unsubscribe_url(7)
        assert url is not None
        expected_origin = "https://app.example.com"
        assert url.removeprefix(expected_origin).startswith(
            "/api/v1/email/unsubscribe-contact?token="
        )

    def test_url_is_none_without_a_configured_origin(self, monkeypatch: pytest.MonkeyPatch):
        """Callers must treat this as 'cannot send', not 'send without footer'."""
        from app.core.config import settings

        monkeypatch.setattr(settings, "frontend_url", "")
        assert build_email_unsubscribe_url(7) is None


@pytest.mark.asyncio
class TestWorkflowSendGate:
    """``_action_send_email`` is the one path workflow email takes."""

    def _worker(self):
        from app.workers import automation_worker

        return automation_worker.AutomationWorker()

    def _contact(self):
        contact = MagicMock()
        contact.id = 55
        contact.email = "ada@example.com"
        contact.first_name = "Ada"
        # Real strings, not MagicMocks: the template renderer joins these.
        contact.last_name = "Lovelace"
        contact.company_name = "Analytical"
        contact.phone_number = "+15551230000"
        return contact

    def _automation(self):
        automation = MagicMock()
        automation.id = uuid.uuid4()
        automation.workspace_id = uuid.uuid4()
        automation.name = "Nurture"
        return automation

    async def _run(self, monkeypatch, config, *, suppressed=False, frontend="https://app.x.com"):
        from app.core.config import settings
        from app.workers import automation_worker

        monkeypatch.setattr(settings, "frontend_url", frontend)
        monkeypatch.setattr(
            automation_worker, "email_suppressed", AsyncMock(return_value=suppressed)
        )
        send = AsyncMock(return_value=True)
        monkeypatch.setattr(automation_worker, "send_automation_email", send)

        await self._worker()._action_send_email(
            self._automation(), self._contact(), config, {}, AsyncMock()
        )
        return send

    async def test_opted_out_contact_is_not_emailed(self, monkeypatch: pytest.MonkeyPatch):
        send = await self._run(
            monkeypatch,
            {"subject": "Hi", "message": "Body"},
            suppressed=True,
        )
        send.assert_not_awaited()

    async def test_commercial_send_carries_an_unsubscribe_url(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        send = await self._run(monkeypatch, {"subject": "Hi", "message": "Body"})
        send.assert_awaited_once()
        assert send.await_args.kwargs["unsubscribe_url"].startswith("https://app.x.com")
        assert send.await_args.kwargs["category"] is EmailCategory.MARKETING

    async def test_workflow_email_defaults_to_commercial(self, monkeypatch: pytest.MonkeyPatch):
        """The safe default for a miscategorised send is 'carries an opt-out'."""
        send = await self._run(monkeypatch, {"subject": "Hi", "message": "Body"})
        assert send.await_args.kwargs["category"] is EmailCategory.MARKETING

    async def test_explicit_transactional_step_has_no_unsubscribe(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """Opting out of a booking confirmation would suppress needed mail."""
        send = await self._run(
            monkeypatch,
            {"subject": "Confirmed", "message": "See you Monday", "transactional": True},
        )
        send.assert_awaited_once()
        assert send.await_args.kwargs["category"] is EmailCategory.TRANSACTIONAL
        assert send.await_args.kwargs["unsubscribe_url"] is None

    async def test_transactional_step_is_sent_even_when_opted_out(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """An email opt-out is not consent withdrawal for service mail."""
        send = await self._run(
            monkeypatch,
            {"subject": "Confirmed", "message": "See you", "transactional": True},
            suppressed=True,
        )
        send.assert_awaited_once()

    async def test_commercial_send_blocked_when_no_public_origin(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """A dead opt-out link is worse than an email that never went out."""
        send = await self._run(monkeypatch, {"subject": "Hi", "message": "B"}, frontend="")
        send.assert_not_awaited()
