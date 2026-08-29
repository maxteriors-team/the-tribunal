"""Cross-**workspace** isolation: can tenant A reach tenant B's rows?

Every prior RBAC pass varied the caller's *role* inside one workspace
(``tests/api/test_technician_surface_probe.py``). This file varies the
*tenant*: the caller is a full member of workspace A, in good standing, and
asks for a row that belongs to workspace B.

The rule the codebase already states, in ``app/db/scope.py``:

    Cross-workspace rows intentionally look identical to missing rows at API
    boundaries to avoid leaking object existence across tenants.

So the assertion is not merely "denied" but **404, indistinguishable from a row
that never existed**. A 403 is a weaker answer that still leaks: it confirms the
id is real somewhere, which turns a guessable id space into an enumeration
oracle over another tenant's data.

Audited 2026-08-28; findings recorded in ``docs/technician-role-audit.md``.
"""

from __future__ import annotations

import types
import uuid
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import (
    get_active_workspace_membership,
    get_current_user,
    get_db,
    get_membership,
    get_workspace,
)
from app.main import app

# The caller's own workspace.
OURS = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
# Somebody else's. Every id below is owned by this one.
THEIRS = uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")

CALL_ID = uuid.UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")


def _client(db: Any) -> AsyncClient:
    """A client authenticated as an **owner** of :data:`OURS`.

    Deliberately the highest role: this file is about the tenant boundary, not
    the capability matrix. If an owner cannot cross it, no lesser role can, and
    a failure here can never be mistaken for a missing capability gate.
    """

    async def _user() -> types.SimpleNamespace:
        return types.SimpleNamespace(id=1, is_active=True, email="owner@ours.test")

    async def _membership() -> types.SimpleNamespace:
        return types.SimpleNamespace(role="owner", workspace_id=OURS, user_id=1)

    async def _workspace() -> types.SimpleNamespace:
        return types.SimpleNamespace(id=OURS, is_active=True, settings={}, name="Ours")

    async def _db() -> AsyncIterator[Any]:
        yield db

    app.dependency_overrides[get_current_user] = _user
    app.dependency_overrides[get_membership] = _membership
    app.dependency_overrides[get_active_workspace_membership] = _membership
    app.dependency_overrides[get_workspace] = _workspace
    app.dependency_overrides[get_db] = _db
    return AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
    )


def _foreign_call() -> MagicMock:
    """A voice message whose conversation belongs to :data:`THEIRS`."""
    conversation = MagicMock()
    conversation.workspace_id = THEIRS
    conversation.contact = None
    message = MagicMock()
    message.id = CALL_ID
    message.channel = "voice"
    message.conversation = conversation
    message.conversation_id = uuid.uuid4()
    message.provider_message_id = "call_control_id"
    return message


def _db_returning(*rows: Any) -> AsyncMock:
    """A db whose successive ``execute`` calls return ``rows``, then ``None``."""
    results = []
    for row in rows:
        result = MagicMock()
        result.scalar_one_or_none.return_value = row
        result.unique.return_value.scalar_one_or_none.return_value = row
        result.scalars.return_value.all.return_value = []
        results.append(result)
    db = AsyncMock()
    db.execute.side_effect = [*results, *([results[-1]] * 20)] if results else None
    return db


async def test_reading_another_tenants_call_is_not_found_not_forbidden() -> None:
    """``GET /calls/{id}`` returned 403 for a foreign call until 2026-08-28.

    The row was never disclosed, so nothing leaked *from* it \u2014 but the status
    code itself confirmed the id was real in another workspace, which is enough
    to enumerate. It now answers exactly as it does for an id that does not
    exist anywhere.
    """
    # First execute: the message lookup, which finds a call owned by THEIRS.
    db = _db_returning(_foreign_call())

    try:
        async with _client(db) as client:
            response = await client.get(f"/api/v1/workspaces/{OURS}/calls/{CALL_ID}")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404
    # And the body must not distinguish it from a genuinely missing call. The app
    # wraps errors in a {code, message, request_id} envelope, so assert on that
    # rather than FastAPI's raw "detail".
    body = response.json()
    assert body["code"] == "not_found"
    assert body["message"] == "Call not found"


async def test_hanging_up_another_tenants_call_is_not_found_not_forbidden(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The same oracle on a write path.

    The conversation lookup here *is* workspace-scoped, so a foreign call was
    never actually hung up — but answering 403 still confirmed the id was real.

    ``telnyx_api_key`` is stubbed because the route checks it *before* the
    ownership check: without this the request 503s early and the test would pass
    while proving nothing.
    """
    from app.api.v1 import calls as calls_module

    monkeypatch.setattr(calls_module.settings, "telnyx_api_key", "test-key")

    # execute #1 finds the message; #2 is the workspace-scoped conversation
    # lookup, which correctly finds nothing because the row belongs to THEIRS.
    db = _db_returning(_foreign_call(), None)

    try:
        async with _client(db) as client:
            response = await client.post(f"/api/v1/workspaces/{OURS}/calls/{CALL_ID}/hangup")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404, response.text
    assert response.json()["message"] == "Call not found"


@pytest.mark.parametrize(
    "detail_source",
    [
        "app/db/scope.py::assert_workspace_owned",
    ],
)
def test_the_shared_helper_answers_404_for_a_foreign_row(detail_source: str) -> None:
    """Pin the rule itself, not just the two routes that broke it.

    ``assert_workspace_owned`` is the chokepoint most routes use. If someone
    'helpfully' switches it to 403 to make debugging easier, every route that
    relies on it starts leaking existence at once — so the status is worth an
    assertion of its own.
    """
    import inspect

    from app.db import scope

    source = inspect.getsource(scope.assert_workspace_owned)
    assert "HTTP_404_NOT_FOUND" in source, detail_source
    assert "HTTP_403_FORBIDDEN" not in source, detail_source
