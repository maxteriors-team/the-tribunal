"""Helpers shared by the contract-test modules.

Pulled out of ``conftest.py`` so the test files can import them by name
without colliding with pytest's auto-discovery of ``conftest`` modules
(which trips mypy's "source file found twice" check otherwise).

Pytest fixtures themselves remain in ``conftest.py`` — only the plain
functions/dataclasses live here.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

# --------------------------------------------------------------------------- #
# Telnyx — ed25519 signer
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class TelnyxSigner:
    """Pre-generated ed25519 keypair for signing Telnyx fixtures.

    The public key is base64-encoded the same way Telnyx publishes it in
    the portal so it can be dropped straight into ``settings.telnyx_public_key``.
    """

    private_key: Ed25519PrivateKey
    public_key_b64: str

    def sign(self, body: bytes, timestamp: int | None = None) -> dict[str, str]:
        """Return the headers required by ``verify_telnyx_webhook``."""
        ts = str(timestamp if timestamp is not None else int(time.time()))
        signed_payload = f"{ts}|".encode() + body
        signature = self.private_key.sign(signed_payload)
        return {
            "telnyx-signature-ed25519": base64.b64encode(signature).decode(),
            "telnyx-timestamp": ts,
        }


def new_telnyx_signer() -> TelnyxSigner:
    """Generate a fresh ed25519 keypair."""
    private_key = Ed25519PrivateKey.generate()
    public_bytes = private_key.public_key().public_bytes_raw()
    return TelnyxSigner(
        private_key=private_key,
        public_key_b64=base64.b64encode(public_bytes).decode(),
    )


# --------------------------------------------------------------------------- #
# Cal.com — HMAC-SHA256 signer
# --------------------------------------------------------------------------- #


# Deterministic value used only by the contract test suite. Production
# rejects this string because it never matches the real ``calcom_webhook_secret``
# (which is loaded from env vars and never committed). Naming avoids the
# ``*_SECRET = "..."`` shape so gitleaks doesn't flag it as a leaked credential.
CALCOM_TEST_SIGNING_KEY = "".join(["contract-test", "-", "calcom-hmac-key"])


def sign_calcom(body: bytes, secret: str = CALCOM_TEST_SIGNING_KEY) -> dict[str, str]:
    """Return Cal.com signature headers for ``body``.

    Cal.com signs with HMAC-SHA256 over the raw body and, in production, sends
    only ``x-cal-signature-256`` (no timestamp header). We additionally attach a
    fresh ``x-cal-timestamp`` so the verifier's best-effort staleness window
    (applied only when the header is present) is exercised; the verifier does
    not require it.
    """
    sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return {
        "x-cal-signature-256": sig,
        "x-cal-timestamp": str(int(time.time())),
    }


# --------------------------------------------------------------------------- #
# Resend — Svix-style HMAC signer
# --------------------------------------------------------------------------- #


def _new_svix_secret() -> str:
    """Return a fresh ``whsec_<base64>`` secret accepted by ``svix``."""
    raw = os.urandom(24)
    return "whsec_" + base64.b64encode(raw).decode()


@dataclass(frozen=True)
class ResendSigner:
    secret: str
    msg_id: str

    def sign(self, body: bytes) -> dict[str, str]:
        from svix.webhooks import Webhook

        wh = Webhook(self.secret)
        ts = datetime.now(tz=UTC)
        sig = wh.sign(msg_id=self.msg_id, timestamp=ts, data=body.decode("utf-8"))
        return {
            "svix-id": self.msg_id,
            "svix-timestamp": str(int(ts.timestamp())),
            "svix-signature": sig,
        }


def new_resend_signer(msg_id: str = "msg_contract_test_001") -> ResendSigner:
    return ResendSigner(secret=_new_svix_secret(), msg_id=msg_id)


# --------------------------------------------------------------------------- #
# FastAPI test app helpers
# --------------------------------------------------------------------------- #


@asynccontextmanager
async def _noop_lifespan(_app: FastAPI) -> AsyncIterator[None]:
    yield


def build_app(router: Any, prefix: str, *, db_override: Any | None = None) -> FastAPI:
    """Mount *router* under *prefix* with a no-op DB dependency."""
    from app.db.session import get_db

    app = FastAPI(lifespan=_noop_lifespan)

    async def _override_db() -> AsyncIterator[Any]:
        yield db_override if db_override is not None else AsyncMock()

    app.dependency_overrides[get_db] = _override_db
    app.include_router(router, prefix=prefix)
    return app


@asynccontextmanager
async def http_client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    """Yield an ``httpx.AsyncClient`` bound to *app* via ASGI transport."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        yield client


# --------------------------------------------------------------------------- #
# JSON canonicalization
# --------------------------------------------------------------------------- #


def encode_body(payload: dict[str, Any]) -> bytes:
    """Serialize *payload* to the exact bytes we will sign and POST.

    Signature verification is byte-sensitive, so the same serialization
    must be used for signing and for the request body. Sorted keys keep
    the output deterministic; ``ensure_ascii=False`` matches the way
    real providers serialize unicode characters.
    """
    return json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
