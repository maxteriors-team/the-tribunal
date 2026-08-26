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
    validated = {"api_key": "quo_secret", "organization_id": "OR_workspace"}
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
                credentials={"api_key": "quo_secret"},
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
        "webhook_id": "11111",
        "webhook_signing_key": "whsec_old",
        "webhook_api_version": "2026-03-30",
    }
    replacement = {
        "api_key": "new_secret",
        "organization_id": "OR_new",
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
