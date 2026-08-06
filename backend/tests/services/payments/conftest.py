"""Shared fixtures for card-on-file tests.

Stripe is never contacted. The module attribute ``stripe_client`` is patched (the
same technique ``tests/services/test_call_payment_service.py`` uses), which also
means any code path that *forgets* to check consent or token validity before
calling Stripe fails loudly here: the fake records every call, so "no Stripe call
was made" is an assertion rather than a hope.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import hash_phone, hash_value
from app.db.session import AsyncSessionLocal, engine
from app.models.contact import Contact
from app.models.workspace import Workspace


class FakeStripeObject(dict[str, Any]):
    """Attribute-and-key accessible stand-in for a Stripe resource."""

    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError as exc:  # pragma: no cover - mirrors Stripe's own error
            raise AttributeError(name) from exc


class FakeResource:
    """One Stripe sub-resource (``customers``, ``setup_intents``, ...)."""

    def __init__(self, recorder: list[tuple[str, Any]], name: str) -> None:
        self._recorder = recorder
        self._name = name
        self.responses: dict[str, Any] = {}

    def _call(self, action: str, *args: Any, **kwargs: Any) -> Any:
        self._recorder.append((f"{self._name}.{action}", {"args": args, "kwargs": kwargs}))
        handler = self.responses.get(action)
        if callable(handler):
            return handler(*args, **kwargs)
        if isinstance(handler, Exception):
            raise handler
        return handler

    def create(self, *args: Any, **kwargs: Any) -> Any:
        return self._call("create", *args, **kwargs)

    def retrieve(self, *args: Any, **kwargs: Any) -> Any:
        return self._call("retrieve", *args, **kwargs)

    def detach(self, *args: Any, **kwargs: Any) -> Any:
        return self._call("detach", *args, **kwargs)


class FakeStripeClient:
    """Records every Stripe call so tests can assert what did (not) happen."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.customers = FakeResource(self.calls, "customers")
        self.setup_intents = FakeResource(self.calls, "setup_intents")
        self.payment_intents = FakeResource(self.calls, "payment_intents")
        self.payment_methods = FakeResource(self.calls, "payment_methods")

    def actions(self) -> list[str]:
        return [name for name, _ in self.calls]


@pytest.fixture
def fake_stripe(monkeypatch: pytest.MonkeyPatch) -> FakeStripeClient:
    """Patch the card-on-file service's Stripe boundary and mark it configured."""
    from app.core.config import settings
    from app.services.payments import card_on_file_service

    client = FakeStripeClient()
    monkeypatch.setattr(card_on_file_service, "stripe_client", lambda: client)
    monkeypatch.setattr(card_on_file_service, "is_payment_configured", lambda: True)
    monkeypatch.setattr(settings, "stripe_publishable_key", "pk_test_fake")
    return client


@pytest_asyncio.fixture(autouse=True)
async def _fresh_engine_pool() -> AsyncIterator[None]:
    """Dispose the shared asyncpg pool around each test.

    pytest-asyncio gives each test a fresh event loop; without disposing, the
    engine's pool can hold connections bound to a closed loop and surface as
    ``Event loop is closed`` when integration tests run back-to-back.
    """
    await engine.dispose()
    yield
    await engine.dispose()


async def make_workspace(db: AsyncSession, name: str = "Cards Co") -> Workspace:
    ws = Workspace(id=uuid.uuid4(), name=name, slug=f"card-{uuid.uuid4().hex[:8]}")
    db.add(ws)
    await db.flush()
    return ws


async def make_contact(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    *,
    first_name: str = "Dana",
    email: str | None = None,
) -> Contact:
    phone = f"+1555{uuid.uuid4().int % 10_000_000:07d}"
    contact = Contact(
        workspace_id=workspace_id,
        first_name=first_name,
        phone_number=phone,
        phone_hash=hash_phone(phone),
        email=email,
        email_hash=hash_value(email) if email else None,
    )
    db.add(contact)
    await db.flush()
    return contact


def session() -> AsyncSession:
    """Open a database session bound to the local Postgres."""
    return AsyncSessionLocal()
