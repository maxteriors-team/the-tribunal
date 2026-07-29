"""Per-workspace authentication for the self-hosted Mac relay webhook.

Closes audit finding H-4 (``docs/security-audit-2026-07-27.md``).

The relay webhook used to accept one *global* bearer token and then take the
tenant from the request body (``to``/``recipient``). That token is deployed to
every customer-operated Mac, so a single compromised relay host could write
messages into any workspace on the platform — and, because ``from`` was equally
attacker-chosen, do it *as* another tenant's operator.

Here the token **is** the tenancy decision. Each relay host presents a token
minted for one :class:`~app.models.phone_number.PhoneNumber` row; resolving it
yields that row's ``workspace_id``, and every downstream lookup is scoped to it.

Only the SHA-256 hex digest is persisted (``phone_numbers.mac_relay_token_hash``),
mirroring ``app/api/v1/api_keys.py`` / ``app/api/deps._user_from_api_key``:
plaintext exists exactly once, at issue time, so a database read primitive
yields no usable credential. Lookup is an equality match on the digest rather
than a ``compare_digest`` scan — the same reason the API-key path does it, and
the reason the digest column is uniquely indexed.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.phone_number import PhoneNumber

#: Human-recognisable prefix so a leaked token is identifiable in a log or a
#: secret scanner (``api_keys`` uses ``trib_`` for the same reason).
TOKEN_PREFIX = "macrelay_"


def generate_mac_relay_token() -> str:
    """Mint a relay token. The caller must show this plaintext exactly once."""
    return f"{TOKEN_PREFIX}{secrets.token_urlsafe(32)}"


def hash_mac_relay_token(token: str) -> str:
    """Return the SHA-256 hex digest of ``token`` — the only form we store."""
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class MacRelayCredential:
    """The tenant a relay request authenticated as.

    ``workspace_id is None`` marks the legacy, **un-scoped** global token, which
    is only reachable when ``settings.mac_relay_allow_legacy_global_token`` is
    explicitly turned on. Consumers must read that as "this request carries no
    tenant binding" and fall back to the pre-H-4 body-derived behaviour; it is
    never a licence to skip a workspace filter on a token that *does* bind.
    """

    workspace_id: uuid.UUID | None
    phone_number_id: uuid.UUID | None = None

    @property
    def is_legacy_global(self) -> bool:
        """Whether this request authenticated with the un-scoped global token."""
        return self.workspace_id is None

    @property
    def log_context(self) -> dict[str, str]:
        """Structlog-bindable identity of the authenticated relay."""
        if self.workspace_id is None:
            return {"relay_auth": "legacy_global_token"}
        return {
            "relay_auth": "workspace_token",
            "workspace_id": str(self.workspace_id),
        }


async def resolve_mac_relay_credential(db: AsyncSession, token: str) -> MacRelayCredential | None:
    """Resolve a presented relay token to its workspace, or ``None``.

    Deactivating a number (``is_active = false``) revokes its relay credential,
    matching how ``APIKey.is_active`` gates API keys.
    """
    if not token:
        return None

    result = await db.execute(
        select(PhoneNumber).where(
            PhoneNumber.mac_relay_token_hash == hash_mac_relay_token(token),
            PhoneNumber.is_active.is_(True),
        )
    )
    phone_record = result.scalar_one_or_none()
    if phone_record is None:
        return None

    return MacRelayCredential(
        workspace_id=phone_record.workspace_id,
        phone_number_id=phone_record.id,
    )


async def mac_relay_credentials_configured(db: AsyncSession) -> bool:
    """Whether any active number carries a relay token.

    Lets the webhook keep its fail-closed 503 for "this endpoint was never
    provisioned" while answering 401 for "provisioned, but that token is wrong".
    """
    result = await db.execute(
        select(PhoneNumber.id)
        .where(
            PhoneNumber.mac_relay_token_hash.is_not(None),
            PhoneNumber.is_active.is_(True),
        )
        .limit(1)
    )
    return result.first() is not None
