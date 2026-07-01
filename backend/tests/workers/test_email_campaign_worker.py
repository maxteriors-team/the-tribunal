"""Email campaign worker tests.

Covers the send path (render + Resend dispatch + status/stat transitions), the
no-email failure branch, and the signed unsubscribe token round-trip. Uses
in-memory factory builds with a mocked DB session, matching the SMS worker tests.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from app.models.campaign import CampaignContactStatus, CampaignType
from app.services.campaigns.email_unsubscribe import (
    make_unsubscribe_token,
    verify_unsubscribe_token,
)
from app.workers.email_campaign_worker import EmailCampaignWorker, _render_template
from tests.factories import (
    CampaignContactFactory,
    CampaignFactory,
    ContactFactory,
)


class _PendingResult:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def scalars(self) -> _PendingResult:
        return self

    def all(self) -> list[object]:
        return self._rows


def _make_worker() -> EmailCampaignWorker:
    worker = EmailCampaignWorker()
    # Isolate the send path from completion/report generation.
    worker._check_completion = AsyncMock()  # type: ignore[method-assign]
    return worker


async def test_email_campaign_sends_to_pending_contact() -> None:
    workspace_id = uuid.uuid4()
    campaign = CampaignFactory.build(
        workspace_id=workspace_id,
        campaign_type=CampaignType.EMAIL,
        from_phone_number=None,
        email_subject="Hi {first_name}, a note from us",
        initial_message="Hello {first_name}, welcome aboard.",
        emails_sent=0,
    )
    contact = ContactFactory.build(
        id=501,
        workspace_id=workspace_id,
        first_name="Ava",
        email="ava@example.com",
    )
    campaign_contact = CampaignContactFactory.build(
        campaign=campaign,
        campaign_id=campaign.id,
        contact=contact,
        contact_id=contact.id,
        status=CampaignContactStatus.PENDING,
    )

    db = MagicMock()
    db.execute = AsyncMock(return_value=_PendingResult([campaign_contact]))
    db.commit = AsyncMock()

    worker = _make_worker()
    # Track ordering: completion status must be set before the final commit,
    # otherwise a COMPLETED transition would never persist.
    order = MagicMock()
    order.attach_mock(worker._check_completion, "check_completion")
    order.attach_mock(db.commit, "commit")

    with patch(
        "app.workers.email_campaign_worker.send_campaign_email",
        AsyncMock(return_value="resend-msg-1"),
    ) as send_email:
        await worker._process_campaign_contacts(campaign, db, MagicMock())

    assert [c[0] for c in order.mock_calls] == ["check_completion", "commit"]
    send_email.assert_awaited_once()
    kwargs = send_email.await_args.kwargs
    assert kwargs["to_email"] == "ava@example.com"
    assert kwargs["subject"] == "Hi Ava, a note from us"
    assert kwargs["body"] == "Hello Ava, welcome aboard."
    assert kwargs["unsubscribe_url"] and str(campaign_contact.id) not in kwargs["unsubscribe_url"]
    assert campaign_contact.status == CampaignContactStatus.SENT
    assert campaign.emails_sent == 1
    db.commit.assert_awaited()


async def test_email_campaign_marks_failed_when_contact_has_no_email() -> None:
    workspace_id = uuid.uuid4()
    campaign = CampaignFactory.build(
        workspace_id=workspace_id,
        campaign_type=CampaignType.EMAIL,
        from_phone_number=None,
        email_subject="Subject",
        initial_message="Body",
        messages_failed=0,
    )
    contact = ContactFactory.build(
        id=502, workspace_id=workspace_id, first_name="NoEmail", email=None
    )
    campaign_contact = CampaignContactFactory.build(
        campaign=campaign,
        campaign_id=campaign.id,
        contact=contact,
        contact_id=contact.id,
        status=CampaignContactStatus.PENDING,
    )

    db = MagicMock()
    db.execute = AsyncMock(return_value=_PendingResult([campaign_contact]))
    db.commit = AsyncMock()

    worker = _make_worker()
    with patch(
        "app.workers.email_campaign_worker.send_campaign_email",
        AsyncMock(return_value="unused"),
    ) as send_email:
        await worker._process_campaign_contacts(campaign, db, MagicMock())

    send_email.assert_not_awaited()
    assert campaign_contact.status == CampaignContactStatus.FAILED
    assert campaign.messages_failed == 1
    # Missing address is a send failure, not a provider bounce.
    assert campaign.emails_bounced == 0


async def test_email_campaign_skips_when_subject_or_body_missing() -> None:
    campaign = CampaignFactory.build(
        campaign_type=CampaignType.EMAIL,
        from_phone_number=None,
        email_subject=None,
        initial_message="Body",
    )
    db = MagicMock()
    db.execute = AsyncMock()
    worker = _make_worker()

    await worker._process_campaign_contacts(campaign, db, MagicMock())

    db.execute.assert_not_awaited()


def test_render_template_substitutes_placeholders() -> None:
    contact = ContactFactory.build(first_name="Sam", last_name="Lee", company_name="Acme")
    assert _render_template("Hi {first_name} {last_name} at {company_name}", contact) == (
        "Hi Sam Lee at Acme"
    )
    assert _render_template("Hi {FIRST_NAME}", contact) == "Hi Sam"


def test_unsubscribe_token_roundtrip_and_tamper() -> None:
    cc_id = uuid.uuid4()
    token = make_unsubscribe_token(cc_id)
    assert verify_unsubscribe_token(token) == cc_id
    assert verify_unsubscribe_token(token + "x") is None
    assert verify_unsubscribe_token("garbage") is None
    assert verify_unsubscribe_token("") is None
