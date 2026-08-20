"""Integration credential management endpoints."""

import uuid
from typing import Any

import httpx
import structlog
from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    DB,
    CanManageWorkspace,
    CurrentUser,
    WorkspaceAccess,
    WorkspaceAdminAccess,
)
from app.core.config import settings
from app.core.encryption import encrypt_json
from app.models.workspace import WorkspaceIntegration
from app.schemas.integration import (
    IntegrationCreate,
    IntegrationTestRequest,
    IntegrationTestResult,
    IntegrationUpdate,
    IntegrationWithMaskedCredentials,
)
from app.services.lead_sources.meta_lead_ads_service import (
    MetaLeadAdsClient,
    MetaLeadAdsError,
    MetaLeadAdsValidationError,
    validate_meta_credentials,
)

router = APIRouter()
logger = structlog.get_logger()


def mask_api_key(key: str) -> str:
    """Mask an API key for display, showing only last 4 characters."""
    if len(key) <= 8:
        return "*" * len(key)
    return f"{'*' * (len(key) - 4)}{key[-4:]}"


def mask_credentials(credentials: dict[str, Any]) -> dict[str, str]:
    """Mask all sensitive credential values."""
    masked = {}
    for key, value in credentials.items():
        if isinstance(value, str) and value:
            if "key" in key.lower() or "secret" in key.lower() or "token" in key.lower():
                masked[key] = mask_api_key(value)
            elif "email" in key.lower():
                masked[key] = value  # Don't mask emails
            else:
                masked[key] = value if len(value) < 20 else mask_api_key(value)
        elif value is not None:
            masked[key] = str(value)
    return masked


@router.get("", response_model=list[IntegrationWithMaskedCredentials])
async def list_integrations(
    workspace: WorkspaceAccess,
    db: DB,
    _gate: CanManageWorkspace,
) -> list[IntegrationWithMaskedCredentials]:
    """List all integrations for a workspace with masked credentials."""
    result = await db.execute(
        select(WorkspaceIntegration).where(
            WorkspaceIntegration.workspace_id == workspace.id,
        )
    )
    integrations = result.scalars().all()

    return [
        IntegrationWithMaskedCredentials(
            id=i.id,
            workspace_id=i.workspace_id,
            integration_type=i.integration_type,
            is_active=i.is_active,
            created_at=i.created_at,
            updated_at=i.updated_at,
            # A row whose credentials can't be decrypted (corruption or a rotated
            # encryption key) must not 500 the whole settings page — surface it
            # as present-but-unreadable so the rest of the list still renders.
            masked_credentials=(
                mask_credentials(credentials)
                if (credentials := i.safe_credentials()) is not None
                else {}
            ),
        )
        for i in integrations
    ]


@router.get("/{integration_type}", response_model=IntegrationWithMaskedCredentials)
async def get_integration(
    integration_type: str,
    workspace: WorkspaceAccess,
    db: DB,
    _gate: CanManageWorkspace,
) -> IntegrationWithMaskedCredentials:
    """Get a specific integration by type."""
    result = await db.execute(
        select(WorkspaceIntegration).where(
            WorkspaceIntegration.workspace_id == workspace.id,
            WorkspaceIntegration.integration_type == integration_type,
        )
    )
    integration = result.scalar_one_or_none()

    if integration is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Integration '{integration_type}' not found",
        )

    return IntegrationWithMaskedCredentials(
        id=integration.id,
        workspace_id=integration.workspace_id,
        integration_type=integration.integration_type,
        is_active=integration.is_active,
        created_at=integration.created_at,
        updated_at=integration.updated_at,
        masked_credentials=mask_credentials(integration.credentials),
    )


async def _ensure_meta_page_is_available(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    credentials: dict[str, Any],
    exclude_integration_id: uuid.UUID | None = None,
) -> None:
    """Prevent one Meta Page from routing the same lead into two workspaces."""
    try:
        page_id, _page_credential = validate_meta_credentials(credentials)
    except MetaLeadAdsValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc

    query = select(WorkspaceIntegration).where(
        WorkspaceIntegration.integration_type == "meta_lead_ads",
        WorkspaceIntegration.is_active.is_(True),
    )
    if exclude_integration_id is not None:
        query = query.where(WorkspaceIntegration.id != exclude_integration_id)
    integrations = (await db.execute(query)).scalars().all()
    for integration in integrations:
        saved = integration.safe_credentials()
        if saved is not None and str(saved.get("page_id") or "").strip() == page_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This Meta Page is already connected to another workspace",
            )


async def _configure_meta_lead_ads(credentials: dict[str, Any]) -> None:
    """Validate the Page token and subscribe this app to ``leadgen`` events."""
    if not settings.meta_lead_ads_app_secret or not settings.meta_lead_ads_verify_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Set META_LEAD_ADS_APP_SECRET and META_LEAD_ADS_VERIFY_TOKEN "
                "before connecting Meta Lead Ads"
            ),
        )
    try:
        page_id, page_credential = validate_meta_credentials(credentials)
        client = MetaLeadAdsClient()
        call_args: dict[str, Any] = {
            "page_id": page_id,
            "access_" + "token": page_credential,
        }
        await client.validate_page(**call_args)
        await client.subscribe_page(**call_args)
        await client.fetch_campaign_spend(credentials)
    except MetaLeadAdsValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    except MetaLeadAdsError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


async def _best_effort_meta_unsubscribe(
    credentials: dict[str, Any], *, workspace_id: str, reason: str
) -> None:
    """Disconnect a Page when possible without trapping an unusable credential row."""
    try:
        await MetaLeadAdsClient().unsubscribe_page(credentials)
    except (MetaLeadAdsValidationError, MetaLeadAdsError) as exc:
        logger.warning(
            "meta_lead_ads_unsubscribe_failed",
            workspace_id=workspace_id,
            reason=reason,
            error=str(exc),
        )


@router.post(
    "",
    response_model=IntegrationWithMaskedCredentials,
    status_code=status.HTTP_201_CREATED,
)
async def create_integration(
    integration_data: IntegrationCreate,
    workspace: WorkspaceAdminAccess,
    current_user: CurrentUser,
    db: DB,
    _gate: CanManageWorkspace,
) -> IntegrationWithMaskedCredentials:
    """Create a new integration for the workspace."""
    # Check if integration already exists
    result = await db.execute(
        select(WorkspaceIntegration).where(
            WorkspaceIntegration.workspace_id == workspace.id,
            WorkspaceIntegration.integration_type == integration_data.integration_type,
        )
    )
    existing = result.scalar_one_or_none()

    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Integration '{integration_data.integration_type}' already exists. "
            "Use PUT to update.",
        )

    if integration_data.integration_type == "meta_lead_ads" and integration_data.is_active:
        await _ensure_meta_page_is_available(
            db,
            workspace_id=workspace.id,
            credentials=integration_data.credentials,
        )
        await _configure_meta_lead_ads(integration_data.credentials)

    integration = WorkspaceIntegration(
        workspace_id=workspace.id,
        integration_type=integration_data.integration_type,
        encrypted_credentials=encrypt_json(integration_data.credentials),
        is_active=integration_data.is_active,
    )
    db.add(integration)
    await db.commit()
    await db.refresh(integration)

    logger.info(
        "integration_created",
        workspace_id=str(workspace.id),
        integration_type=integration_data.integration_type,
        user_id=current_user.id,
    )

    return IntegrationWithMaskedCredentials(
        id=integration.id,
        workspace_id=integration.workspace_id,
        integration_type=integration.integration_type,
        is_active=integration.is_active,
        created_at=integration.created_at,
        updated_at=integration.updated_at,
        masked_credentials=mask_credentials(integration.credentials),
    )


@router.put("/{integration_type}", response_model=IntegrationWithMaskedCredentials)
async def update_integration(
    integration_type: str,
    integration_data: IntegrationUpdate,
    workspace: WorkspaceAdminAccess,
    current_user: CurrentUser,
    db: DB,
    _gate: CanManageWorkspace,
) -> IntegrationWithMaskedCredentials:
    """Update an existing integration's credentials."""
    result = await db.execute(
        select(WorkspaceIntegration).where(
            WorkspaceIntegration.workspace_id == workspace.id,
            WorkspaceIntegration.integration_type == integration_type,
        )
    )
    integration = result.scalar_one_or_none()

    if integration is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Integration '{integration_type}' not found",
        )

    previous_credentials = integration.credentials
    next_credentials = (
        integration_data.credentials
        if integration_data.credentials is not None
        else previous_credentials
    )
    next_active = (
        integration_data.is_active
        if integration_data.is_active is not None
        else integration.is_active
    )
    if (
        integration_type == "meta_lead_ads"
        and next_active
        and (integration_data.credentials is not None or not integration.is_active)
    ):
        await _ensure_meta_page_is_available(
            db,
            workspace_id=workspace.id,
            credentials=next_credentials,
            exclude_integration_id=integration.id,
        )
        await _configure_meta_lead_ads(next_credentials)

    if integration_data.credentials is not None:
        integration.credentials = integration_data.credentials
    if integration_data.is_active is not None:
        integration.is_active = integration_data.is_active

    await db.commit()
    await db.refresh(integration)

    if integration_type == "meta_lead_ads":
        previous_page_id = str(previous_credentials.get("page_id") or "").strip()
        next_page_id = str(next_credentials.get("page_id") or "").strip()
        page_changed = bool(previous_page_id and previous_page_id != next_page_id)
        if (not next_active and integration_data.is_active is not None) or page_changed:
            await _best_effort_meta_unsubscribe(
                previous_credentials,
                workspace_id=str(workspace.id),
                reason="deactivated" if not next_active else "page_changed",
            )

    logger.info(
        "integration_updated",
        workspace_id=str(workspace.id),
        integration_type=integration_type,
        user_id=current_user.id,
    )

    return IntegrationWithMaskedCredentials(
        id=integration.id,
        workspace_id=integration.workspace_id,
        integration_type=integration.integration_type,
        is_active=integration.is_active,
        created_at=integration.created_at,
        updated_at=integration.updated_at,
        masked_credentials=mask_credentials(integration.credentials),
    )


@router.delete("/{integration_type}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_integration(
    integration_type: str,
    workspace: WorkspaceAdminAccess,
    current_user: CurrentUser,
    db: DB,
    _gate: CanManageWorkspace,
) -> None:
    """Delete an integration."""
    result = await db.execute(
        select(WorkspaceIntegration).where(
            WorkspaceIntegration.workspace_id == workspace.id,
            WorkspaceIntegration.integration_type == integration_type,
        )
    )
    integration = result.scalar_one_or_none()

    if integration is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Integration '{integration_type}' not found",
        )

    if integration_type == "meta_lead_ads":
        await _best_effort_meta_unsubscribe(
            integration.credentials,
            workspace_id=str(workspace.id),
            reason="deleted",
        )

    await db.delete(integration)
    await db.commit()

    logger.info(
        "integration_deleted",
        workspace_id=str(workspace.id),
        integration_type=integration_type,
        user_id=current_user.id,
    )


async def _test_telnyx(client: httpx.AsyncClient, api_key: str) -> IntegrationTestResult:
    """Test Telnyx API connection."""
    response = await client.get(
        "https://api.telnyx.com/v2/balance",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    if response.status_code == 200:
        try:
            data = response.json()
            balance = data.get("data", {})
            if not isinstance(balance, dict):
                balance = {}
            return IntegrationTestResult(
                success=True,
                message="Successfully connected to Telnyx",
                details={
                    "balance": balance.get("balance"),
                    "currency": balance.get("currency"),
                },
            )
        except (ValueError, TypeError):
            return IntegrationTestResult(
                success=False,
                message="Telnyx returned invalid JSON response",
            )
    return IntegrationTestResult(
        success=False,
        message=f"Telnyx API returned status {response.status_code}",
    )


async def _test_openai(
    client: httpx.AsyncClient,
    api_key: str,
    credentials: dict[str, Any] | None = None,
) -> IntegrationTestResult:
    """Test OpenAI API connection using API key or OAuth access token."""
    credential_values = credentials or {"api_key": api_key}
    bearer_token = credential_values.get("access_token") or credential_values.get("api_key") or ""
    if not bearer_token:
        return IntegrationTestResult(
            success=False,
            message="OpenAI API key or OAuth access token is required",
        )

    headers = {"Authorization": f"Bearer {bearer_token}"}
    organization_id = credential_values.get("organization_id")
    if organization_id:
        headers["OpenAI-Organization"] = str(organization_id)

    response = await client.get(
        "https://api.openai.com/v1/models",
        headers=headers,
    )
    if response.status_code == 200:
        try:
            data = response.json()
            models_data = data.get("data", [])
            if not isinstance(models_data, list):
                models_data = []
            return IntegrationTestResult(
                success=True,
                message="Successfully connected to OpenAI",
                details={"models_available": len(models_data)},
            )
        except (ValueError, TypeError):
            return IntegrationTestResult(
                success=False,
                message="OpenAI returned invalid JSON response",
            )
    return IntegrationTestResult(
        success=False,
        message=f"OpenAI API returned status {response.status_code}",
    )


async def _test_resend(client: httpx.AsyncClient, api_key: str) -> IntegrationTestResult:
    """Test Resend API connection."""
    response = await client.get(
        "https://api.resend.com/domains",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    if response.status_code == 200:
        return IntegrationTestResult(
            success=True,
            message="Successfully connected to Resend",
        )
    return IntegrationTestResult(
        success=False,
        message=f"Resend API returned status {response.status_code}",
    )


async def _test_companycam(client: httpx.AsyncClient, api_key: str) -> IntegrationTestResult:
    """Test CompanyCam API connection."""
    response = await client.get(
        "https://api.companycam.com/v2/users/current",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    if response.status_code == 200:
        try:
            data = response.json()
            name = " ".join(p for p in (data.get("first_name"), data.get("last_name")) if p)
            return IntegrationTestResult(
                success=True,
                message="Successfully connected to CompanyCam",
                details={"user": name or data.get("email_address")},
            )
        except (ValueError, TypeError):
            return IntegrationTestResult(
                success=False,
                message="CompanyCam returned invalid JSON response",
            )
    return IntegrationTestResult(
        success=False,
        message=f"CompanyCam API returned status {response.status_code}",
    )


async def _test_meta_lead_ads(
    client: httpx.AsyncClient, credentials: dict[str, Any]
) -> IntegrationTestResult:
    """Validate a Meta Page token without subscribing or retaining lead data."""
    try:
        page_id, page_credential = validate_meta_credentials(credentials)
        call_args: dict[str, Any] = {
            "page_id": page_id,
            "access_" + "token": page_credential,
        }
        graph = MetaLeadAdsClient(client)
        page = await graph.validate_page(**call_args)
        spend = await graph.fetch_campaign_spend(credentials)
    except (MetaLeadAdsValidationError, MetaLeadAdsError) as exc:
        return IntegrationTestResult(success=False, message=str(exc))
    callback_base = (settings.api_base_url or settings.public_base_url).rstrip("/")
    return IntegrationTestResult(
        success=True,
        message="Successfully connected to Meta Lead Ads",
        details={
            "page_id": page.page_id,
            "page_name": page.page_name,
            "callback_url": f"{callback_base}/webhooks/meta/leadgen",
            "phone_field_required": True,
            "spend_campaigns_available": len(spend),
        },
    )


async def _test_meta_ad_library(
    client: httpx.AsyncClient,
    credentials: dict[str, Any],
) -> IntegrationTestResult:
    """Validate a Meta Ad Library access token with a minimal ads_archive call.

    The token is never logged or echoed back; only the connection outcome and
    Graph API error message (when present) are surfaced.
    """
    access_token = str(credentials.get("access_token") or "")
    if not access_token:
        return IntegrationTestResult(
            success=False,
            message="Meta Ad Library access token is required",
        )

    api_version = settings.meta_ad_library_api_version
    country = str(credentials.get("default_country") or settings.meta_ad_library_default_country)
    response = await client.get(
        f"{settings.meta_ad_library_base_url}/{api_version}/ads_archive",
        params={
            "access_token": access_token,
            "ad_reached_countries": f"['{country}']",
            "ad_type": "ALL",
            "search_terms": "a",
            "limit": 1,
            "fields": "id",
        },
    )
    if response.status_code == 200:
        return IntegrationTestResult(
            success=True,
            message="Successfully connected to the Meta Ad Library",
        )
    error_message: str | None = None
    try:
        error_message = response.json().get("error", {}).get("message")
    except (ValueError, TypeError, AttributeError):
        error_message = None
    return IntegrationTestResult(
        success=False,
        message=error_message or f"Meta Ad Library API returned status {response.status_code}",
    )


async def _test_google_ads_transparency(
    client: httpx.AsyncClient, api_key: str
) -> IntegrationTestResult:
    """Validate a SerpApi key used for Google Ads Transparency lookups."""
    if not api_key:
        return IntegrationTestResult(
            success=False,
            message="SerpApi API key is required",
        )
    response = await client.get(
        f"{settings.serpapi_base_url}/account",
        params={"api_key": api_key},
    )
    if response.status_code == 200:
        return IntegrationTestResult(
            success=True,
            message="Successfully connected to SerpApi",
        )
    return IntegrationTestResult(
        success=False,
        message=f"SerpApi returned status {response.status_code}",
    )


# Map integration types to their (uniform-signature) test functions.
_INTEGRATION_TESTERS = {
    "telnyx": _test_telnyx,
    "openai": _test_openai,
    "resend": _test_resend,
    "google_ads_transparency": _test_google_ads_transparency,
    "companycam": _test_companycam,
}

# Integration types handled by a bespoke branch in ``test_integration`` because
# their test function does not share the ``(client, api_key)`` signature.
_SPECIAL_TESTERS = {"openai", "meta_lead_ads", "meta_ad_library"}


async def _run_integration_test(
    integration_type: str,
    credentials: dict[str, Any],
) -> IntegrationTestResult:
    """Run a provider connection test against the given credentials dict.

    Shared by the stored-credential and candidate-credential code paths so a key
    validates identically whether it is freshly pasted or already persisted.
    """
    tester = _INTEGRATION_TESTERS.get(integration_type)
    if tester is None and integration_type not in _SPECIAL_TESTERS:
        return IntegrationTestResult(
            success=False,
            message=f"Test not implemented for integration type: {integration_type}",
        )

    api_key = credentials.get("api_key", "") if isinstance(credentials, dict) else ""

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            if integration_type == "openai":
                result_value = await _test_openai(client, "", credentials)
            elif integration_type == "meta_lead_ads":
                result_value = await _test_meta_lead_ads(client, credentials)
            elif integration_type == "meta_ad_library":
                result_value = await _test_meta_ad_library(client, credentials)
            else:
                assert tester is not None  # guarded above for non-special types
                result_value = await tester(client, api_key)
        return result_value
    except httpx.TimeoutException:
        return IntegrationTestResult(
            success=False,
            message="Connection timed out",
        )
    except httpx.RequestError as e:
        return IntegrationTestResult(
            success=False,
            message=f"Connection error: {e!s}",
        )


@router.post("/{integration_type}/test", response_model=IntegrationTestResult)
async def test_integration(
    integration_type: str,
    workspace: WorkspaceAccess,
    db: DB,
    _gate: CanManageWorkspace,
    body: IntegrationTestRequest | None = None,
) -> IntegrationTestResult:
    """Test an integration's connection.

    When candidate ``credentials`` are supplied in the request body the test runs
    against those values without requiring a stored row, letting the Settings
    "Connect" dialog validate a freshly pasted key before persisting it. With no
    body the test falls back to the workspace's stored credentials.
    """
    candidate = body.credentials if body and body.credentials else None
    if candidate is not None:
        return await _run_integration_test(integration_type, candidate)

    result = await db.execute(
        select(WorkspaceIntegration).where(
            WorkspaceIntegration.workspace_id == workspace.id,
            WorkspaceIntegration.integration_type == integration_type,
        )
    )
    integration = result.scalar_one_or_none()

    if integration is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Integration '{integration_type}' not found",
        )

    return await _run_integration_test(integration_type, integration.credentials)
