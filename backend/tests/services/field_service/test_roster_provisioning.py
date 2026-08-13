"""Unit tests for membership-driven dispatch-roster provisioning.

Offline: the session is faked so these assert the branching in
``app.services.field_service.roster`` (which role provisions, what the roster
row is named, when an existing row is reused instead of duplicated) without a
database. The end-to-end wiring through ``bulk_create_members`` and the real
uniqueness invariant are covered by ``tests/services/field_service/test_roster``
(integration).
"""

from __future__ import annotations

import uuid
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.field_service import Technician
from app.models.user import User
from app.services.field_service.roster import (
    ensure_member_on_roster,
    is_field_role,
    retire_member_from_roster,
)

pytestmark = pytest.mark.asyncio

WS_ID = uuid.uuid4()


class _FakeResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalar_one_or_none(self) -> Any:
        return self._rows[0] if self._rows else None

    def scalars(self) -> _FakeResult:
        return self

    def first(self) -> Any:
        return self._rows[0] if self._rows else None

    def all(self) -> list[Any]:
        return list(self._rows)


class _FakeSession:
    """Returns queued query results in order; records adds and flushes."""

    def __init__(self, *results: list[Any]) -> None:
        self._results = [_FakeResult(rows) for rows in results]
        self.added: list[Any] = []
        self.flushes = 0

    async def execute(self, _query: Any) -> _FakeResult:
        return self._results.pop(0) if self._results else _FakeResult([])

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        self.flushes += 1


def _session(*results: list[Any]) -> Any:
    return _FakeSession(*results)


def _user(**kwargs: Any) -> User:
    defaults: dict[str, Any] = {
        "id": 7,
        "email": "sam.rivera@example.com",
        "full_name": "Sam Rivera",
        "phone_number": "+15125550123",
    }
    return User(**{**defaults, **kwargs})


def _technician(**kwargs: Any) -> Technician:
    defaults: dict[str, Any] = {
        "id": uuid.uuid4(),
        "workspace_id": WS_ID,
        "user_id": None,
        "name": "Sam Rivera",
        "email": "sam.rivera@example.com",
        "is_active": True,
    }
    return Technician(**{**defaults, **kwargs})


async def test_field_roles_are_the_two_on_site_roles() -> None:
    assert is_field_role("technician")
    assert is_field_role("lead_technician")
    # Dispatchers run the board; they are not automatically on it.
    assert not is_field_role("dispatcher")
    assert not is_field_role("manager")
    assert not is_field_role("owner")
    assert not is_field_role(None)


async def test_field_role_member_gets_a_roster_row() -> None:
    db = _session([], [])

    entry = await ensure_member_on_roster(
        cast(AsyncSession, db), workspace_id=WS_ID, user=_user(), role="technician"
    )

    assert entry is not None
    assert db.added == [entry]
    assert entry.workspace_id == WS_ID
    assert entry.user_id == 7
    assert entry.name == "Sam Rivera"
    assert entry.email == "sam.rivera@example.com"
    assert entry.phone == "+15125550123"
    assert entry.is_active is True


async def test_non_field_role_is_never_put_on_the_board() -> None:
    db = _session()

    entry = await ensure_member_on_roster(
        cast(AsyncSession, db), workspace_id=WS_ID, user=_user(), role="dispatcher"
    )

    assert entry is None
    assert db.added == []


async def test_unnamed_account_falls_back_to_the_email_local_part() -> None:
    # ``full_name`` is optional on an invited account, but the dispatch list has
    # nothing else to show, so an empty name must never reach the board.
    db = _session([], [])

    entry = await ensure_member_on_roster(
        cast(AsyncSession, db),
        workspace_id=WS_ID,
        user=_user(full_name="   "),
        role="lead_technician",
    )

    assert entry is not None
    assert entry.name == "sam.rivera"


async def test_existing_link_is_reused_and_reactivated() -> None:
    retired = _technician(user_id=7, is_active=False)
    db = _session([retired])

    entry = await ensure_member_on_roster(
        cast(AsyncSession, db), workspace_id=WS_ID, user=_user(), role="technician"
    )

    assert entry is retired
    assert entry.is_active is True
    assert db.added == []


async def test_rehired_member_does_not_get_a_second_row() -> None:
    active = _technician(user_id=7)
    db = _session([active])

    entry = await ensure_member_on_roster(
        cast(AsyncSession, db), workspace_id=WS_ID, user=_user(), role="technician"
    )

    assert entry is active
    assert db.added == []
    assert db.flushes == 0


async def test_loginless_row_with_the_same_email_is_claimed() -> None:
    # A crew imported from Jobber (or typed in by a dispatcher) already lists
    # this person; linking beats listing them on the board twice.
    imported = _technician(email="Sam.Rivera@Example.com")
    db = _session([], [imported])

    entry = await ensure_member_on_roster(
        cast(AsyncSession, db), workspace_id=WS_ID, user=_user(), role="technician"
    )

    assert entry is imported
    assert entry.user_id == 7
    assert db.added == []


async def test_removed_member_is_retired_but_history_survives() -> None:
    linked = _technician(user_id=7)
    db = _session([linked])

    retired = await retire_member_from_roster(cast(AsyncSession, db), workspace_id=WS_ID, user_id=7)

    assert retired == 1
    # Unlinked + deactivated, never deleted: the jobs they worked keep their
    # assignment rows, and the roster row stays editable.
    assert linked.user_id is None
    assert linked.is_active is False
    assert db.added == []


async def test_retiring_a_member_who_never_worked_jobs_is_a_no_op() -> None:
    db = _session([])

    assert (
        await retire_member_from_roster(cast(AsyncSession, db), workspace_id=WS_ID, user_id=7) == 0
    )
    assert db.flushes == 0
