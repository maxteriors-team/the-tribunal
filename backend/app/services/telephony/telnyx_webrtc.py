"""Short-lived Telnyx WebRTC credentials for authenticated CRM operators."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User

logger = structlog.get_logger()

_TELNYX_API_URL = "https://api.telnyx.com/v2"
_SIP_USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_MAX_TOKEN_LENGTH = 16_384


class TelnyxWebRTCError(RuntimeError):
    """Safe provider failure that may be returned to an authenticated operator."""


class _CredentialNotFoundError(TelnyxWebRTCError):
    """Stored provider credential was removed and must be recreated."""


@dataclass(frozen=True, slots=True)
class BrowserCredential:
    """Non-secret provider identity for one Tribunal user."""

    credential_id: str
    sip_username: str


class TelnyxWebRTCService:
    """Provision per-user SIP identities without exposing long-lived passwords.

    The browser receives only Telnyx's 24-hour JWT. The credential connection
    must use internal-only SIP URI calling and have no PSTN outbound profile, so
    a copied browser token cannot dial arbitrary paid destinations.
    """

    def __init__(
        self,
        api_key: str,
        connection_id: str,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._connection_id = self._validate_connection_id(connection_id)
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=_TELNYX_API_URL,
            headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
            timeout=httpx.Timeout(15.0),
        )

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def issue_user_token(self, db: AsyncSession, user: User) -> str:
        """Return a fresh JWT, recreating a provider-deleted credential once."""
        credential = await self.ensure_user_credential(db, user)
        try:
            return await self._create_token(credential.credential_id)
        except _CredentialNotFoundError:
            locked_user = await self._lock_user(db, user.id)
            locked_user.telnyx_telephony_credential_id = None
            locked_user.telnyx_sip_username = None
            await db.commit()
            credential = await self.ensure_user_credential(db, locked_user)
            return await self._create_token(credential.credential_id)

    async def ensure_user_credential(self, db: AsyncSession, user: User) -> BrowserCredential:
        """Get or provision one internal-only SIP identity for a user."""
        if user.telnyx_telephony_credential_id and user.telnyx_sip_username:
            return BrowserCredential(
                credential_id=user.telnyx_telephony_credential_id,
                sip_username=self._validate_sip_username(user.telnyx_sip_username),
            )

        locked_user = await self._lock_user(db, user.id)
        if locked_user.telnyx_telephony_credential_id and locked_user.telnyx_sip_username:
            return BrowserCredential(
                credential_id=locked_user.telnyx_telephony_credential_id,
                sip_username=self._validate_sip_username(locked_user.telnyx_sip_username),
            )

        credential = await self._create_credential(locked_user.id)
        locked_user.telnyx_telephony_credential_id = credential.credential_id
        locked_user.telnyx_sip_username = credential.sip_username
        # The provider resource already exists. Commit its non-secret identifiers
        # now so a later call failure cannot orphan the credential on rollback.
        await db.commit()
        return credential

    async def _lock_user(self, db: AsyncSession, user_id: int) -> User:
        result = await db.execute(select(User).where(User.id == user_id).with_for_update())
        locked_user = result.scalar_one_or_none()
        if locked_user is None:
            raise TelnyxWebRTCError("Browser calling user no longer exists")
        return locked_user

    async def _create_credential(self, user_id: int) -> BrowserCredential:
        payload = {
            "connection_id": self._connection_id,
            "name": f"tribunal-user-{user_id}",
            "tag": "tribunal-browser",
        }
        data = await self._post_json("/telephony_credentials", payload)
        resource = data.get("data")
        if not isinstance(resource, dict):
            raise TelnyxWebRTCError("Browser calling provider returned an invalid credential")

        credential_id = self._validate_uuid(str(resource.get("id") or ""), "credential ID")
        sip_username = self._validate_sip_username(str(resource.get("sip_username") or ""))
        logger.info("telnyx_browser_credential_created", user_id=user_id)
        return BrowserCredential(credential_id=credential_id, sip_username=sip_username)

    async def _create_token(self, credential_id: str) -> str:
        try:
            response = await self._client.post(f"/telephony_credentials/{credential_id}/token")
        except httpx.HTTPError as exc:
            raise TelnyxWebRTCError("Browser calling service is temporarily unavailable") from exc

        if response.status_code == 404:
            raise _CredentialNotFoundError("Browser calling credential was not found")
        if response.status_code >= 400:
            logger.warning(
                "telnyx_browser_token_failed",
                status_code=response.status_code,
                request_id=response.headers.get("x-request-id"),
            )
            raise TelnyxWebRTCError("Browser calling service is temporarily unavailable")

        token = response.text.strip()
        if len(token) > _MAX_TOKEN_LENGTH or token.count(".") != 2:
            raise TelnyxWebRTCError("Browser calling provider returned an invalid token")
        return token

    async def _post_json(self, path: str, payload: dict[str, str]) -> dict[str, object]:
        try:
            response = await self._client.post(path, json=payload)
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            status_code = getattr(getattr(exc, "response", None), "status_code", None)
            logger.warning("telnyx_browser_request_failed", status_code=status_code)
            raise TelnyxWebRTCError("Browser calling service is temporarily unavailable") from exc
        if not isinstance(data, dict):
            raise TelnyxWebRTCError("Browser calling provider returned an invalid response")
        return data

    @staticmethod
    def _validate_connection_id(value: str) -> str:
        if value.isdigit() and 1 <= len(value) <= 20:
            return value
        return TelnyxWebRTCService._validate_uuid(value, "connection ID")

    @staticmethod
    def _validate_uuid(value: str, label: str) -> str:
        try:
            return str(uuid.UUID(value))
        except ValueError as exc:
            raise TelnyxWebRTCError(f"Browser calling {label} is invalid") from exc

    @staticmethod
    def _validate_sip_username(value: str) -> str:
        if not _SIP_USERNAME_PATTERN.fullmatch(value):
            raise TelnyxWebRTCError("Browser calling SIP identity is invalid")
        return value
