"""Native Meta Lead Ads ingestion and workspace attribution.

Meta's webhook contains identifiers only.  The lead's fields are fetched from the
Graph API with the encrypted workspace Page token, then persisted through the
same contact/attribution primitives as website leads.  Raw webhook or Graph
payloads are never logged or retained.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Literal

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.encryption import hash_phone, hash_value_or_none
from app.models.contact import Contact
from app.models.lead_source import (
    LeadSource,
    LeadSourceCampaign,
    LeadSourceSpendEntry,
    LeadSourceType,
)
from app.models.workspace import WorkspaceIntegration
from app.services.automations.events import EVENT_LEAD_CREATED, emit_automation_event
from app.services.lead_sources.attribution_service import (
    WebAttributionInput,
    apply_web_attribution,
)
from app.utils.phone import normalize_phone_safe

logger = structlog.get_logger()

META_LEAD_ADS_INTEGRATION = "meta_lead_ads"
META_EXTERNAL_SOURCE = "facebook_lead_ads"
_GRAPH_FIELDS = ",".join(
    (
        "id",
        "created_time",
        "ad_id",
        "ad_name",
        "adset_id",
        "adset_name",
        "campaign_id",
        "campaign_name",
        "form_id",
        "field_data",
        "is_organic",
        "platform",
    )
)


class MetaLeadAdsError(RuntimeError):
    """A retryable Meta Graph API or workspace-integration failure."""


class MetaLeadAdsValidationError(ValueError):
    """A permanent lead-shape problem that a webhook retry cannot fix."""


class MetaMessagingWindowClosedError(MetaLeadAdsError):
    """Meta refused a DM because the 24h standard messaging window has closed.

    Distinct from :class:`MetaLeadAdsError` because it is not retryable: the
    window only reopens when the person messages the business again.
    """


#: Graph subresources this client is allowed to address. Kept as a closed set so
#: a caller cannot append an arbitrary path segment onto a Graph object URL.
GraphEndpoint = Literal["subscribed_apps", "insights", "messages"]

#: Meta's "This message is sent outside of allowed window." error code.
_OUTSIDE_WINDOW_ERROR_CODE = 10


@dataclass(frozen=True, slots=True)
class MetaPageIdentity:
    page_id: str
    page_name: str | None


@dataclass(frozen=True, slots=True)
class MetaCampaignSpend:
    campaign_id: str
    campaign_name: str
    amount: Decimal
    currency: str
    starts_on: date
    ends_on: date


@dataclass(frozen=True, slots=True)
class MetaLeadProcessResult:
    status: Literal["created", "updated", "duplicate", "ignored"]
    contact_id: int | None = None


class MetaLeadAdsClient:
    """Small, timeout-bounded Graph client with PII-safe errors."""

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client

    def _url(
        self,
        object_id: str,
        endpoint: GraphEndpoint | None = None,
    ) -> str:
        prefix = ""
        identifier = object_id
        if identifier.startswith("act_"):
            prefix = "act_"
            identifier = identifier.removeprefix("act_")
        if not identifier.isalnum() or len(identifier) > 128:
            raise MetaLeadAdsValidationError("Invalid Meta Graph object identifier")

        safe_object_id = f"{prefix}{identifier}"
        endpoint_path = f"/{endpoint}" if endpoint else ""
        base = settings.meta_lead_ads_base_url.rstrip("/")
        version = settings.meta_lead_ads_api_version.strip("/")
        return f"{base}/{version}/{safe_object_id}{endpoint_path}"

    async def _request(
        self,
        method: str,
        object_id: str,
        *,
        params: dict[str, str],
        endpoint: GraphEndpoint | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(
            timeout=settings.meta_lead_ads_request_timeout_seconds
        )
        try:
            response = await client.request(
                method,
                self._url(object_id, endpoint),
                params=params,
                json=json_body,
            )
        except httpx.HTTPError as exc:
            raise MetaLeadAdsError("Meta Graph API request failed") from exc
        finally:
            if owns_client:
                await client.aclose()

        if response.status_code >= 400:
            error_code: str | int | None = None
            try:
                payload = response.json()
                error = payload.get("error", {}) if isinstance(payload, dict) else {}
                if isinstance(error, dict):
                    error_code = error.get("code")
            except ValueError:
                # Meta can return HTML/plain text errors; the HTTP status is still actionable.
                pass
            detail = f"Meta Graph API returned HTTP {response.status_code}" + (
                f" (code {error_code})" if error_code is not None else ""
            )
            # Code 10 is "message sent outside of allowed window". Retrying it
            # never succeeds — only the person writing back reopens the window —
            # so it must not surface as the retryable error type.
            if error_code == _OUTSIDE_WINDOW_ERROR_CODE:
                raise MetaMessagingWindowClosedError(detail)
            raise MetaLeadAdsError(detail)

        try:
            payload = response.json()
        except ValueError as exc:
            raise MetaLeadAdsError("Meta Graph API returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise MetaLeadAdsError("Meta Graph API returned an invalid object")
        return payload

    async def validate_page(self, *, page_id: str, access_token: str) -> MetaPageIdentity:
        payload = await self._request(
            "GET",
            page_id,
            params={"fields": "id,name", "access_token": access_token},
        )
        returned_id = str(payload.get("id") or "")
        if not returned_id or returned_id != page_id:
            raise MetaLeadAdsError("Meta token does not resolve the configured Page")
        page_name = payload.get("name")
        return MetaPageIdentity(
            page_id=returned_id,
            page_name=str(page_name) if page_name else None,
        )

    async def subscribe_page(self, *, page_id: str, access_token: str) -> None:
        payload = await self._request(
            "POST",
            page_id,
            params={"subscribed_fields": "leadgen", "access_token": access_token},
            endpoint="subscribed_apps",
        )
        if payload.get("success") is not True:
            raise MetaLeadAdsError("Meta did not confirm the Page leadgen subscription")

    async def unsubscribe_page(self, credentials: dict[str, Any]) -> None:
        """Remove this app's ``leadgen`` Page subscription before disconnecting."""
        page_id, page_credential = validate_meta_credentials(credentials)
        payload = await self._request(
            "DELETE",
            page_id,
            params={"access_" + "token": page_credential},
            endpoint="subscribed_apps",
        )
        if payload.get("success") is not True:
            raise MetaLeadAdsError("Meta did not confirm the Page unsubscribe")

    async def fetch_lead(self, *, leadgen_id: str, access_token: str) -> dict[str, Any]:
        return await self._request(
            "GET",
            leadgen_id,
            params={"fields": _GRAPH_FIELDS, "access_token": access_token},
        )

    async def fetch_sender_name(self, *, psid: str, access_token: str) -> str | None:
        """Return the DM sender's profile name, or ``None`` when unavailable.

        A DM thread has no phone and therefore no contact record, so this name
        is the only thing the inbox can show. It is best-effort on purpose:
        profile access depends on granted permissions, and a missing name must
        never cost us the message itself.
        """
        payload = await self._request(
            "GET",
            psid,
            params={"fields": "name", "access_token": access_token},
        )
        name = str(payload.get("name") or "").strip()
        return name[:120] or None

    async def send_message(
        self,
        *,
        account_id: str,
        psid: str,
        text: str,
        access_token: str,
    ) -> str | None:
        """Send one text DM as the Page and return Meta's message id.

        ``messaging_type=RESPONSE`` declares this as a reply inside the standard
        24h window. We deliberately never attach a message tag: the 7-day
        ``HUMAN_AGENT`` tag does not cover bot-generated replies, so claiming it
        for AI follow-up would be a policy violation rather than a workaround.
        """
        payload = await self._request(
            "POST",
            account_id,
            params={"access_token": access_token},
            endpoint="messages",
            json_body={
                "recipient": {"id": psid},
                "message": {"text": text},
                "messaging_type": "RESPONSE",
            },
        )
        return str(payload.get("message_id") or "") or None

    async def fetch_campaign_spend(self, credentials: dict[str, Any]) -> list[MetaCampaignSpend]:
        """Fetch lifetime campaign spend when optional ``ads_read`` data is configured.

        Meta's current Business SDK exposes ``/{ad-account}/insights`` with
        campaign level, ``maximum`` date preset, and the fields requested here.
        """
        account_id = str(credentials.get("ad_account_id") or "").strip()
        page_credential = str(credentials.get("ad_" + "access_" + "token") or "").strip()
        if not page_credential:
            page_credential = str(credentials.get("access_" + "token") or "").strip()
        if not account_id or not page_credential:
            return []
        account_object = account_id if account_id.startswith("act_") else f"act_{account_id}"
        payload = await self._request(
            "GET",
            account_object,
            params={
                "fields": ("account_currency,campaign_id,campaign_name,date_start,date_stop,spend"),
                "level": "campaign",
                "date_preset": "maximum",
                "time_increment": "all_days",
                "limit": "5000",
                "access_" + "token": page_credential,
            },
            endpoint="insights",
        )
        raw_rows = payload.get("data")
        if not isinstance(raw_rows, list):
            raise MetaLeadAdsError("Meta insights response did not contain campaign data")

        rows: list[MetaCampaignSpend] = []
        for raw in raw_rows:
            if not isinstance(raw, dict):
                continue
            campaign_id = str(raw.get("campaign_id") or "").strip()
            if not campaign_id:
                continue
            try:
                amount = Decimal(str(raw.get("spend") or "0"))
                starts_on = date.fromisoformat(str(raw.get("date_start")))
                ends_on = date.fromisoformat(str(raw.get("date_stop")))
            except (ArithmeticError, ValueError):
                continue
            rows.append(
                MetaCampaignSpend(
                    campaign_id=campaign_id,
                    campaign_name=str(raw.get("campaign_name") or campaign_id),
                    amount=max(amount, Decimal("0")),
                    currency=str(raw.get("account_currency") or "USD").upper()[:3],
                    starts_on=starts_on,
                    ends_on=ends_on,
                )
            )
        return rows


def validate_meta_credentials(credentials: dict[str, Any]) -> tuple[str, str]:
    """Return normalized Page credentials or raise a safe validation error."""
    page_id = str(credentials.get("page_id") or "").strip()
    access_token = str(credentials.get("access_token") or "").strip()
    if not page_id:
        raise MetaLeadAdsValidationError("Meta Page ID is required")
    if not access_token:
        raise MetaLeadAdsValidationError("Meta Page access token is required")
    return page_id, access_token


def _field_values(payload: dict[str, Any]) -> dict[str, list[str]]:
    fields: dict[str, list[str]] = {}
    raw_fields = payload.get("field_data")
    if not isinstance(raw_fields, list):
        return fields
    for item in raw_fields:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip().lower()
        values = item.get("values")
        if not name or not isinstance(values, list):
            continue
        cleaned = [
            str(value).strip() for value in values if value is not None and str(value).strip()
        ]
        if cleaned:
            fields[name] = cleaned
    return fields


def _first(fields: dict[str, list[str]], *names: str) -> str | None:
    for name in names:
        values = fields.get(name)
        if values:
            return values[0]
    return None


def _names(fields: dict[str, list[str]]) -> tuple[str, str]:
    first_name = _first(fields, "first_name")
    last_name = _first(fields, "last_name")
    full_name = _first(fields, "full_name", "name")
    if full_name and (not first_name or not last_name):
        pieces = full_name.split(maxsplit=1)
        first_name = first_name or pieces[0]
        last_name = last_name or (pieces[1] if len(pieces) > 1 else "")
    return first_name or "Facebook", last_name or "Lead"


def _created_at(value: Any) -> datetime:
    if not value:
        return datetime.now(UTC)
    raw = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return datetime.now(UTC)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


async def _integration_for_page(
    db: AsyncSession, page_id: str
) -> tuple[WorkspaceIntegration, dict[str, Any]]:
    integrations = (
        (
            await db.execute(
                select(WorkspaceIntegration).where(
                    WorkspaceIntegration.integration_type == META_LEAD_ADS_INTEGRATION,
                    WorkspaceIntegration.is_active.is_(True),
                )
            )
        )
        .scalars()
        .all()
    )
    matches: list[tuple[WorkspaceIntegration, dict[str, Any]]] = []
    for integration in integrations:
        credentials = integration.credentials
        if str(credentials.get("page_id") or "").strip() == page_id:
            matches.append((integration, credentials))
    if not matches:
        raise MetaLeadAdsValidationError("No active workspace integration matches the Meta Page")
    if len(matches) > 1:
        raise MetaLeadAdsError("Multiple active workspace integrations match the Meta Page")
    return matches[0]


async def resolve_facebook_lead_source(
    db: AsyncSession,
    *,
    integration: WorkspaceIntegration,
    credentials: dict[str, Any],
    campaign_id: str | None,
) -> LeadSource:
    configured_id = credentials.get("lead_source_id")
    if configured_id:
        try:
            parsed_id = uuid.UUID(str(configured_id))
        except ValueError as exc:
            raise MetaLeadAdsValidationError("Meta lead_source_id must be a UUID") from exc
        configured = await db.get(LeadSource, parsed_id)
        if (
            configured is None
            or configured.workspace_id != integration.workspace_id
            or configured.source_type != LeadSourceType.FACEBOOK_ADS
            or not configured.enabled
        ):
            raise MetaLeadAdsValidationError(
                "Meta lead_source_id must identify an enabled Facebook Ads source in this workspace"
            )
        return configured

    if campaign_id:
        campaign_source = (
            await db.execute(
                select(LeadSource)
                .join(LeadSourceCampaign, LeadSourceCampaign.lead_source_id == LeadSource.id)
                .where(
                    LeadSource.workspace_id == integration.workspace_id,
                    LeadSourceCampaign.workspace_id == integration.workspace_id,
                    LeadSourceCampaign.platform_campaign_id == campaign_id,
                    LeadSourceCampaign.enabled.is_(True),
                    LeadSource.source_type == LeadSourceType.FACEBOOK_ADS,
                    LeadSource.enabled.is_(True),
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if campaign_source is not None:
            return campaign_source

    candidates = (
        (
            await db.execute(
                select(LeadSource)
                .where(
                    LeadSource.workspace_id == integration.workspace_id,
                    LeadSource.source_type == LeadSourceType.FACEBOOK_ADS,
                    LeadSource.enabled.is_(True),
                )
                .order_by(LeadSource.created_at.asc())
                .limit(2)
            )
        )
        .scalars()
        .all()
    )
    if len(candidates) == 1:
        return candidates[0]

    source = LeadSource(
        workspace_id=integration.workspace_id,
        name="Facebook Lead Ads",
        source_type=LeadSourceType.FACEBOOK_ADS,
        action="collect",
        action_config={},
        allowed_domains=[],
        enabled=True,
    )
    db.add(source)
    await db.flush()
    return source


async def _campaign(
    db: AsyncSession,
    *,
    integration: WorkspaceIntegration,
    lead_source: LeadSource,
    payload: dict[str, Any],
) -> LeadSourceCampaign | None:
    external_id = str(payload.get("campaign_id") or "").strip()
    if not external_id:
        return None
    existing = (
        await db.execute(
            select(LeadSourceCampaign).where(
                LeadSourceCampaign.workspace_id == integration.workspace_id,
                LeadSourceCampaign.lead_source_id == lead_source.id,
                LeadSourceCampaign.platform_campaign_id == external_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    name = str(payload.get("campaign_name") or external_id).strip()
    campaign = LeadSourceCampaign(
        workspace_id=integration.workspace_id,
        lead_source_id=lead_source.id,
        name=name[:255],
        platform_campaign_id=external_id[:255],
        platform_campaign_name=name[:255],
        utm_campaign=name[:255],
        campaign_metadata={"platform": "meta"},
        enabled=True,
    )
    db.add(campaign)
    await db.flush()
    return campaign


async def sync_meta_campaign_spend(
    db: AsyncSession,
    integration: WorkspaceIntegration,
    *,
    client: MetaLeadAdsClient | None = None,
) -> int:
    """Upsert provider-owned lifetime spend rows for one Meta ad account."""
    graph = client or MetaLeadAdsClient()
    spend_rows = await graph.fetch_campaign_spend(integration.credentials)
    if not spend_rows:
        return 0

    first = spend_rows[0]
    lead_source = await resolve_facebook_lead_source(
        db,
        integration=integration,
        credentials=integration.credentials,
        campaign_id=first.campaign_id,
    )
    synced = 0
    for row in spend_rows:
        campaign = await _campaign(
            db,
            integration=integration,
            lead_source=lead_source,
            payload={
                "campaign_id": row.campaign_id,
                "campaign_name": row.campaign_name,
            },
        )
        if campaign is None:
            continue
        note = f"meta-sync:{row.campaign_id}"
        entry = (
            await db.execute(
                select(LeadSourceSpendEntry).where(
                    LeadSourceSpendEntry.workspace_id == integration.workspace_id,
                    LeadSourceSpendEntry.lead_source_campaign_id == campaign.id,
                    LeadSourceSpendEntry.notes == note,
                )
            )
        ).scalar_one_or_none()
        if entry is None:
            entry = LeadSourceSpendEntry(
                workspace_id=integration.workspace_id,
                lead_source_id=lead_source.id,
                lead_source_campaign_id=campaign.id,
                spend_starts_on=row.starts_on,
                spend_ends_on=row.ends_on,
                amount=row.amount,
                currency=row.currency,
                notes=note,
            )
            db.add(entry)
        else:
            entry.spend_starts_on = row.starts_on
            entry.spend_ends_on = row.ends_on
            entry.amount = row.amount
            entry.currency = row.currency
        synced += 1

    await db.flush()
    return synced


def _record_explicit_sms_consent(
    contact: Contact,
    *,
    credentials: dict[str, Any],
    fields: dict[str, list[str]],
    created_at: datetime,
    form_id: str | None,
) -> None:
    field_name = str(credentials.get("sms_consent_field_name") or "").strip().lower()
    if not field_name:
        return
    submitted = _first(fields, field_name)
    if submitted is None:
        return
    configured_truthy = credentials.get("sms_consent_truthy_values")
    values = configured_truthy if isinstance(configured_truthy, list) else ["yes", "true", "1"]
    truthy = {str(value).strip().lower() for value in values}
    if submitted.strip().lower() not in truthy:
        return
    contact.sms_consent_status = "opted_in"
    contact.sms_consent_source = "facebook_lead_form"
    contact.sms_consent_collected_at = created_at
    contact.sms_consent_notes = f"Explicit Meta Lead Form consent field '{field_name}'" + (
        f" on form {form_id}" if form_id else ""
    )


async def process_meta_lead(
    db: AsyncSession,
    *,
    page_id: str,
    leadgen_id: str,
    client: MetaLeadAdsClient | None = None,
) -> MetaLeadProcessResult:
    """Fetch and upsert one Meta lead, idempotently, without retaining raw fields."""
    integration, credentials = await _integration_for_page(db, page_id)
    _configured_page, access_token = validate_meta_credentials(credentials)

    duplicate = (
        await db.execute(
            select(Contact).where(
                Contact.workspace_id == integration.workspace_id,
                Contact.external_source == META_EXTERNAL_SOURCE,
                Contact.external_id == leadgen_id,
            )
        )
    ).scalar_one_or_none()
    if duplicate is not None:
        return MetaLeadProcessResult("duplicate", duplicate.id)

    payload = await (client or MetaLeadAdsClient()).fetch_lead(
        leadgen_id=leadgen_id,
        access_token=access_token,
    )
    returned_id = str(payload.get("id") or "")
    if returned_id != leadgen_id:
        raise MetaLeadAdsError("Meta returned a different lead identifier")

    fields = _field_values(payload)
    raw_phone = _first(fields, "phone_number", "phone", "work_phone_number")
    phone = normalize_phone_safe(raw_phone or "")
    if phone is None:
        logger.warning(
            "meta_lead_ignored_missing_phone",
            workspace_id=str(integration.workspace_id),
        )
        return MetaLeadProcessResult("ignored")

    first_name, last_name = _names(fields)
    email = _first(fields, "email", "work_email")
    created_at = _created_at(payload.get("created_time"))
    campaign_external_id = str(payload.get("campaign_id") or "").strip() or None
    source = await resolve_facebook_lead_source(
        db,
        integration=integration,
        credentials=credentials,
        campaign_id=campaign_external_id,
    )
    campaign = await _campaign(
        db,
        integration=integration,
        lead_source=source,
        payload=payload,
    )

    contact = (
        await db.execute(
            select(Contact).where(
                Contact.workspace_id == integration.workspace_id,
                Contact.phone_hash == hash_phone(phone),
            )
        )
    ).scalar_one_or_none()
    is_new = contact is None
    if contact is None:
        contact = Contact(
            workspace_id=integration.workspace_id,
            first_name=first_name,
            last_name=last_name,
            phone_number=phone,
            email=email,
            phone_hash=hash_phone(phone),
            email_hash=hash_value_or_none(email),
            source=META_EXTERNAL_SOURCE,
            status="new",
            external_source=META_EXTERNAL_SOURCE,
            external_id=leadgen_id,
            created_at=created_at,
        )
        db.add(contact)
    else:
        if not contact.first_name or contact.first_name == "Unknown":
            contact.first_name = first_name
        if not contact.last_name:
            contact.last_name = last_name
        if email and not contact.email:
            contact.email = email
            contact.email_hash = hash_value_or_none(email)
        if contact.external_id is None:
            contact.external_source = META_EXTERNAL_SOURCE
            contact.external_id = leadgen_id

    apply_web_attribution(
        contact,
        source,
        WebAttributionInput(
            lead_source_campaign_id=campaign.id if campaign else None,
            attribution_confidence=1.0,
            utm_source="facebook",
            utm_medium="paid_social",
            utm_campaign=str(payload.get("campaign_name") or "") or None,
            utm_content=str(payload.get("ad_name") or "") or None,
        ),
        now=created_at if is_new else None,
    )
    form_id = str(payload.get("form_id") or "").strip() or None
    _record_explicit_sms_consent(
        contact,
        credentials=credentials,
        fields=fields,
        created_at=created_at,
        form_id=form_id,
    )
    contact.business_intel = {
        **(contact.business_intel or {}),
        "facebook_lead_ads": {
            "leadgen_id": leadgen_id,
            "page_id": page_id,
            "form_id": form_id,
            "campaign_id": campaign_external_id,
            "adset_id": str(payload.get("adset_id") or "") or None,
            "ad_id": str(payload.get("ad_id") or "") or None,
            "is_organic": bool(payload.get("is_organic", False)),
            "received_at": datetime.now(UTC).isoformat(),
        },
    }

    await db.flush()
    if is_new:
        await emit_automation_event(
            db,
            workspace_id=integration.workspace_id,
            event_type=EVENT_LEAD_CREATED,
            contact_id=contact.id,
            payload={
                "lead_source_id": str(source.id),
                "lead_source_campaign_id": str(campaign.id) if campaign else None,
                "external_source": META_EXTERNAL_SOURCE,
                "is_new_lead": True,
            },
        )

    logger.info(
        "meta_lead_processed",
        workspace_id=str(integration.workspace_id),
        contact_id=str(contact.id),
        created=is_new,
    )
    return MetaLeadProcessResult("created" if is_new else "updated", contact.id)
