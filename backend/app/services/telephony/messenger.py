"""Outbound Messenger and Instagram Direct sender.

Reuses the Telnyx SMS send pipeline (idempotency, link shortening, message
persistence, SLA first-response tracking) and swaps only the three things that
actually differ on Meta: the thread is keyed on a Page-Scoped ID rather than a
phone pair, the credentials are per-workspace and live in the database, and the
send is only legal inside Meta's 24-hour messaging window.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import hash_value
from app.models.conversation import Conversation, Message, MessageChannel
from app.services.lead_sources.meta_lead_ads_service import (
    MetaLeadAdsClient,
    MetaLeadAdsValidationError,
    MetaMessagingWindowClosedError,
)
from app.services.messaging.outbound_media import OutboundMedia
from app.services.telephony.telnyx import TelnyxSMSService

logger = structlog.get_logger()

#: Sentinel "from" address. A DM thread has no workspace phone; the real sender
#: is the workspace's Page, resolved from its integration at send time.
MESSENGER_SENDER_PLACEHOLDER = ""


@dataclass(frozen=True, slots=True)
class _PageCredentials:
    account_id: str
    access_token: str


class MessengerMessageService(TelnyxSMSService):
    """Text sender that delivers through Meta's Send API.

    One instance serves exactly one :meth:`send_message` call. The factory
    builds a fresh service per send, and the resolved Page credentials are held
    on the instance only for the duration of that call, because the Telnyx
    template method that does the sending is synchronous and has no session to
    look them up from.
    """

    def __init__(self, *, channel: MessageChannel = MessageChannel.MESSENGER) -> None:
        """Initialize a single-send Messenger provider for ``channel``."""
        super().__init__(
            api_key="",  # Meta authenticates per-Page, not with a service key.
            message_channel=channel,
            conversation_channel=channel.value,
            service_name="meta_messenger",
            provider_payload_type="messenger",
        )
        self._credentials: _PageCredentials | None = None
        self._graph = MetaLeadAdsClient()

    async def send_message(
        self,
        to_number: str,
        from_number: str,
        body: str,
        db: AsyncSession,
        workspace_id: uuid.UUID,
        agent_id: uuid.UUID | None = None,
        campaign_id: uuid.UUID | None = None,
        phone_number_id: uuid.UUID | None = None,
        idempotency_key: uuid.UUID | None = None,
        media: tuple[OutboundMedia, ...] = (),
        sender_user_id: int | None = None,
        sender_display_name: str | None = None,
    ) -> Message:
        """Send one DM, refusing before the API call when the window has closed.

        ``to_number`` is the recipient's Page-Scoped ID; ``from_number`` is
        ignored because the sending Page comes from the workspace integration.
        """
        if media:
            raise MetaLeadAdsValidationError("Attachments are not supported on Messenger")

        self._credentials = await _page_credentials(db, workspace_id)
        await self._reject_if_window_closed(db, workspace_id=workspace_id, psid=to_number)

        return await super().send_message(
            to_number=to_number,
            from_number=from_number,
            body=body,
            db=db,
            workspace_id=workspace_id,
            agent_id=agent_id,
            campaign_id=campaign_id,
            phone_number_id=phone_number_id,
            idempotency_key=idempotency_key,
            sender_user_id=sender_user_id,
            sender_display_name=sender_display_name,
        )

    async def _reject_if_window_closed(
        self,
        db: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        psid: str,
    ) -> None:
        """Fail loudly before spending a Graph call on a send Meta will reject.

        Checking locally is not merely an optimization: a rejected send would
        otherwise be recorded as a generic provider failure, and a thread that
        can never be reopened by us would look exactly like a flaky API.
        """
        expires_at = (
            await db.execute(
                select(Conversation.messenger_window_expires_at).where(
                    Conversation.workspace_id == workspace_id,
                    Conversation.messenger_psid_hash == hash_value(psid),
                )
            )
        ).scalar_one_or_none()
        if expires_at is not None and expires_at <= datetime.now(UTC):
            raise MetaMessagingWindowClosedError(
                "Meta's 24h messaging window has closed for this conversation"
            )

    def _normalize_outbound_to(self, to_number: str) -> str:
        """Validate the recipient PSID; it is an opaque id, not a phone number."""
        psid = to_number.strip()
        if not psid.isdigit() or len(psid) > 64:
            raise MetaLeadAdsValidationError("Invalid Messenger recipient id")
        return psid

    def _normalize_outbound_from(self, from_number: str) -> str:
        """Return the workspace's Page ID, ignoring the caller's placeholder."""
        return self._require_credentials().account_id

    async def _get_or_create_conversation(
        self,
        db: AsyncSession,
        workspace_phone: str,
        contact_phone: str,
        workspace_id: uuid.UUID,
    ) -> Conversation:
        """Return the existing PSID-keyed thread; never open one on an outbound.

        A business cannot start a Messenger conversation — Meta only permits a
        reply inside a window the person opened — so an outbound send with no
        thread is a bug, not a new thread.
        """
        conversation = (
            await db.execute(
                select(Conversation).where(
                    Conversation.workspace_id == workspace_id,
                    Conversation.messenger_psid_hash == hash_value(contact_phone),
                )
            )
        ).scalar_one_or_none()
        if conversation is None:
            raise MetaLeadAdsValidationError(
                "Cannot start a Messenger conversation; the person must message first"
            )
        return conversation

    def _build_message_payload(
        self,
        *,
        to_number: str,
        from_number: str,
        body: str,
        idempotency_key: uuid.UUID,
        media_urls: list[str] | None = None,
    ) -> dict[str, Any]:
        """Build the Send API arguments consumed by :meth:`_post_message`."""
        if media_urls:
            raise MetaLeadAdsValidationError("Attachments are not supported on Messenger")
        return {"account_id": from_number, "psid": to_number, "text": body}

    async def _post_message(
        self,
        payload: dict[str, Any],
        idempotency_key: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        """Deliver through Meta's Send API, normalized to the Telnyx shape.

        Meta has no idempotency key, so a retry after a lost response can
        duplicate a DM. Upstream ``resolve_message_idempotency`` is what stops
        that: it only resumes rows still marked queued.
        """
        credentials = self._require_credentials()
        message_id = await self._graph.send_message(
            account_id=payload["account_id"],
            psid=payload["psid"],
            text=payload["text"],
            access_token=credentials.access_token,
        )
        return {"data": {"id": message_id}}

    def _require_credentials(self) -> _PageCredentials:
        """Return this send's Page credentials, or fail rather than send blind."""
        if self._credentials is None:
            raise MetaLeadAdsValidationError("Meta Page credentials were not resolved")
        return self._credentials


async def _page_credentials(db: AsyncSession, workspace_id: uuid.UUID) -> _PageCredentials:
    """Load the workspace's own Page credentials.

    Scoped to the workspace rather than looked up by Page ID so an outbound send
    can only ever leave through the tenant's own Page.
    """
    from app.models.workspace import WorkspaceIntegration
    from app.services.lead_sources.meta_lead_ads_service import (
        META_LEAD_ADS_INTEGRATION,
        validate_meta_credentials,
    )

    integration = (
        await db.execute(
            select(WorkspaceIntegration).where(
                WorkspaceIntegration.workspace_id == workspace_id,
                WorkspaceIntegration.integration_type == META_LEAD_ADS_INTEGRATION,
                WorkspaceIntegration.is_active.is_(True),
            )
        )
    ).scalar_one_or_none()
    if integration is None:
        raise MetaLeadAdsValidationError("This workspace has no connected Meta Page")
    account_id, access_token = validate_meta_credentials(integration.credentials)
    return _PageCredentials(account_id=account_id, access_token=access_token)
