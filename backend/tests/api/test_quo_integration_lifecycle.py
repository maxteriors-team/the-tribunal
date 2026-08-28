"""Quo webhook provisioning and cleanup lifecycle tests."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.v1.integrations import credentials as credentials_api
from app.models import workspace as workspace_models
from app.models.workspace import WorkspaceIntegration
from app.schemas.integration import IntegrationCreate, IntegrationUpdate
from app.services.quo import QuoApiError, QuoPhoneNumber

pytestmark = pytest.mark.asyncio


async def test_create_active_quo_integration_provisions_before_encrypted_save() -> None:
    workspace_id = uuid.uuid4()
    workspace = MagicMock(id=workspace_id)
    current_user = MagicMock(id=7)
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    db = MagicMock()
    db.execute = AsyncMock(return_value=result)
    db.commit = AsyncMock()

    async def refresh(integration: WorkspaceIntegration) -> None:
        now = datetime.now(UTC)
        integration.created_at = now
        integration.updated_at = now

    db.refresh = AsyncMock(side_effect=refresh)
    validated = {
        "api_key": "quo_secret",
        "organization_id": "OR_workspace",
        "phone_number_id": "PN_main",
        "phone_number": "+14155552671",
    }
    provisioned = {
        **validated,
        "webhook_id": "12345",
        "webhook_signing_key": "whsec_signing_key",
        "webhook_api_version": "2026-03-30",
    }

    with (
        patch.object(
            credentials_api,
            "_validate_quo_credentials",
            new=AsyncMock(return_value=validated),
        ),
        patch.object(
            credentials_api,
            "_provision_quo_webhook",
            new=AsyncMock(return_value=provisioned),
        ) as provision_mock,
        patch.object(credentials_api, "encrypt_json", return_value="ciphertext") as encrypt_mock,
        patch.object(workspace_models, "decrypt_json", return_value=provisioned),
    ):
        await credentials_api.create_integration(
            IntegrationCreate(
                integration_type="quo",
                credentials={"api_key": "quo_secret", "phone_number_id": "PN_main"},
                is_active=True,
            ),
            workspace,
            current_user,
            db,
            MagicMock(),
        )

    integration = db.add.call_args.args[0]
    provision_mock.assert_awaited_once_with(
        validated,
        integration_id=integration.id,
        expected_organization_id="OR_workspace",
    )
    encrypt_mock.assert_called_once_with(provisioned)
    assert integration.encrypted_credentials == "ciphertext"


async def test_deactivation_strips_secrets_then_cleans_remote_webhook() -> None:
    workspace_id = uuid.uuid4()
    previous = {
        "api_key": "quo_secret",
        "organization_id": "OR_workspace",
        "phone_number_id": "PN_main",
        "phone_number": "+14155552671",
        "webhook_id": "12345",
        "webhook_signing_key": "whsec_signing_key",
        "webhook_api_version": "2026-03-30",
    }
    stored_after_update: dict[str, Any] = {}

    def decrypt_json(value: str) -> dict[str, Any]:
        return previous if value == "old_ciphertext" else stored_after_update

    def encrypt_json(value: dict[str, Any]) -> str:
        stored_after_update.update(value)
        return "new_ciphertext"

    integration = WorkspaceIntegration(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        integration_type="quo",
        encrypted_credentials="old_ciphertext",
        is_active=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    result = MagicMock()
    result.scalar_one_or_none.return_value = integration
    db = MagicMock()
    db.execute = AsyncMock(return_value=result)
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    with (
        patch.object(workspace_models, "decrypt_json", side_effect=decrypt_json),
        patch.object(workspace_models, "encrypt_json", side_effect=encrypt_json),
        patch.object(
            credentials_api,
            "_best_effort_quo_webhook_cleanup",
            new=AsyncMock(),
        ) as cleanup_mock,
    ):
        await credentials_api.update_integration(
            "quo",
            IntegrationUpdate(credentials=None, is_active=False),
            MagicMock(id=workspace_id),
            MagicMock(id=7),
            db,
            MagicMock(),
        )

    assert stored_after_update == {
        "api_key": "quo_secret",
        "organization_id": "OR_workspace",
        "phone_number_id": "PN_main",
        "phone_number": "+14155552671",
    }
    cleanup_mock.assert_awaited_once_with(
        previous,
        workspace_id=str(workspace_id),
        reason="deactivated",
    )


async def test_replacing_credentials_cleans_previous_remote_webhook() -> None:
    workspace_id = uuid.uuid4()
    previous = {
        "api_key": "old_secret",
        "organization_id": "OR_old",
        "phone_number_id": "PN_old",
        "phone_number": "+14155550111",
        "webhook_id": "11111",
        "webhook_signing_key": "whsec_old",
        "webhook_api_version": "2026-03-30",
    }
    replacement = {
        "api_key": "new_secret",
        "organization_id": "OR_new",
        "phone_number_id": "PN_new",
        "phone_number": "+14155550222",
        "webhook_id": "22222",
        "webhook_signing_key": "whsec_new",
        "webhook_api_version": "2026-03-30",
    }
    integration = WorkspaceIntegration(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        integration_type="quo",
        encrypted_credentials="old_ciphertext",
        is_active=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    result = MagicMock()
    result.scalar_one_or_none.return_value = integration
    db = MagicMock()
    db.execute = AsyncMock(return_value=result)
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    def decrypt_json(value: str) -> dict[str, Any]:
        return previous if value == "old_ciphertext" else replacement

    with (
        patch.object(workspace_models, "decrypt_json", side_effect=decrypt_json),
        patch.object(workspace_models, "encrypt_json", return_value="new_ciphertext"),
        patch.object(
            credentials_api,
            "_prepare_quo_update",
            new=AsyncMock(return_value=(replacement, replacement)),
        ),
        patch.object(
            credentials_api,
            "_best_effort_quo_webhook_cleanup",
            new=AsyncMock(),
        ) as cleanup_mock,
    ):
        await credentials_api.update_integration(
            "quo",
            IntegrationUpdate(credentials={"api_key": "new_secret"}, is_active=True),
            MagicMock(id=workspace_id),
            MagicMock(id=7),
            db,
            MagicMock(),
        )

    assert integration.encrypted_credentials == "new_ciphertext"
    cleanup_mock.assert_awaited_once_with(
        previous,
        workspace_id=str(workspace_id),
        reason="replaced",
    )


async def test_active_line_reports_contact_quo_history_when_selected_line_has_no_thread() -> None:
    workspace_id = uuid.uuid4()
    db = MagicMock()
    db.scalar = AsyncMock(return_value=uuid.uuid4())
    active_line = MagicMock(
        phone_number_id="PN_selected",
        phone_number="+14155552671",
    )

    with patch.object(
        credentials_api,
        "resolve_active_quo_line",
        new=AsyncMock(return_value=active_line),
    ):
        result = await credentials_api.get_active_quo_line(
            MagicMock(id=workspace_id),
            # The route now requires ``crm:read``: passing ``contact_id`` reveals
            # whether that contact has Quo conversation history. Called directly
            # here, so the membership is a stub — the gate itself is covered by
            # tests/api/test_technician_surface_probe.py.
            MagicMock(role="owner"),
            db,
            contact_id=42,
        )

    assert result.active is True
    assert result.phone_number_id == "PN_selected"
    assert result.has_contact_history is True
    db.scalar.assert_awaited_once()


async def test_validation_requires_one_of_three_provider_owned_phone_numbers() -> None:
    choices = [
        QuoPhoneNumber(id="PN_one", phone_number="+14155550101"),
        QuoPhoneNumber(id="PN_two", phone_number="+14155550102", provider_label="Sales"),
        QuoPhoneNumber(id="PN_three", phone_number="+14155550103"),
    ]
    with patch.object(
        credentials_api,
        "_inspect_quo_credentials",
        new=AsyncMock(return_value=("quo_secret", "OR_workspace", choices)),
    ):
        with pytest.raises(QuoApiError, match="Select one"):
            await credentials_api._validate_quo_credentials({"api_key": "quo_secret"})
        with pytest.raises(QuoApiError, match="unavailable"):
            await credentials_api._validate_quo_credentials(
                {"api_key": "quo_secret", "phone_number_id": "PN_other"}
            )
        validated = await credentials_api._validate_quo_credentials(
            {
                "api_key": "quo_secret",
                "phone_number_id": "PN_two",
                "phone_number": "+19999999999",
            }
        )

    assert validated == {
        "api_key": "quo_secret",
        "organization_id": "OR_workspace",
        "phone_number_id": "PN_two",
        "phone_number": "+14155550102",
    }


async def test_candidate_key_test_returns_three_safe_sender_choices() -> None:
    choices = [
        QuoPhoneNumber(id="PN_one", phone_number="+14155550101"),
        QuoPhoneNumber(id="PN_two", phone_number="+14155550102", provider_label="Sales"),
        QuoPhoneNumber(id="PN_three", phone_number="+14155550103"),
    ]
    with patch.object(
        credentials_api,
        "_inspect_quo_credentials",
        new=AsyncMock(return_value=("quo_secret", "OR_workspace", choices)),
    ):
        result = await credentials_api._test_quo({"api_key": "quo_secret"})

    assert result.success is True
    assert result.phone_numbers is not None
    assert [choice.id for choice in result.phone_numbers] == ["PN_one", "PN_two", "PN_three"]
    assert result.phone_numbers[1].provider_label == "Sales"


async def test_selection_only_update_preserves_encrypted_key_and_webhook() -> None:
    workspace_id = uuid.uuid4()
    previous = {
        "api_key": "quo_secret",
        "organization_id": "OR_workspace",
        "phone_number_id": "PN_old",
        "phone_number": "+14155550101",
        "webhook_id": "12345",
        "webhook_signing_key": "whsec_signing_key",
        "webhook_api_version": "2026-03-30",
    }
    validated = {
        "api_key": "quo_secret",
        "organization_id": "OR_workspace",
        "phone_number_id": "PN_new",
        "phone_number": "+14155550102",
    }
    stored: dict[str, Any] = {}
    integration = WorkspaceIntegration(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        integration_type="quo",
        encrypted_credentials="old_ciphertext",
        is_active=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    result = MagicMock()
    result.scalar_one_or_none.return_value = integration
    db = MagicMock()
    db.execute = AsyncMock(return_value=result)
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    def decrypt_json(value: str) -> dict[str, Any]:
        return previous if value == "old_ciphertext" else stored

    def encrypt_json(value: dict[str, Any]) -> str:
        stored.update(value)
        return "new_ciphertext"

    with (
        patch.object(workspace_models, "decrypt_json", side_effect=decrypt_json),
        patch.object(workspace_models, "encrypt_json", side_effect=encrypt_json),
        patch.object(
            credentials_api,
            "_validate_quo_credentials",
            new=AsyncMock(return_value=validated),
        ) as validate_mock,
        patch.object(
            credentials_api,
            "_provision_quo_webhook",
            new=AsyncMock(),
        ) as provision_mock,
    ):
        await credentials_api.update_integration(
            "quo",
            IntegrationUpdate(credentials={"phone_number_id": "PN_new"}, is_active=True),
            MagicMock(id=workspace_id),
            MagicMock(id=7),
            db,
            MagicMock(),
        )

    validate_mock.assert_awaited_once()
    provision_mock.assert_not_awaited()
    assert stored == {
        **validated,
        **{key: previous[key] for key in credentials_api._QUO_WEBHOOK_CREDENTIAL_KEYS},
    }
