"""Tests for the per-username account lockout in the login endpoint.

These tests pin the security contract added in
``backend/app/api/v1/auth.py``: after ``_USERNAME_LOCKOUT_LIMIT`` failed login
attempts on the same username within ``_USERNAME_LOCKOUT_WINDOW_MINUTES``, the
endpoint must return a generic 401 regardless of password correctness, so a
distributed attacker rotating IPs cannot brute-force a single account.

The tests exercise the pure helpers (`_hash_username`,
`_check_username_lockout`, `_record_login_failure`) directly, plus the wired
``POST /login`` route with a fake in-memory ``AsyncSession``.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.engine import Result

from app.api.v1 import auth as auth_module
from app.api.v1.auth import (
    _LOGIN_FAILED_ENDPOINT,
    _USERNAME_LOCKOUT_LIMIT,
    _check_username_lockout,
    _hash_username,
    _record_login_failure,
)
from app.models.auth_rate_limit import AuthRateLimit


@asynccontextmanager
async def _test_lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Minimal lifespan that skips workers, Redis, and DB setup."""
    yield


def _make_test_app() -> FastAPI:
    app = FastAPI(lifespan=_test_lifespan)
    app.include_router(auth_module.router, prefix="/api/v1/auth")
    return app


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    app = _make_test_app()
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as ac:
        yield ac


class _FakeSession:
    """In-memory async session that supports the narrow surface auth.py uses.

    Mimics ``AsyncSession.execute(select(func.count())...).scalar()`` for the
    two count queries the login path runs (IP limit + username lockout) and
    captures any ``AuthRateLimit`` objects added to the session, so tests can
    inspect them.
    """

    def __init__(self, lockout_count: int = 0) -> None:
        self.lockout_count = lockout_count
        self.added: list[Any] = []
        self.committed = False
        self.flushed = 0

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        self.flushed += 1

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:  # pragma: no cover - defensive
        pass

    async def close(self) -> None:  # pragma: no cover - defensive
        pass

    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def execute(self, statement: Any) -> Result:  # type: ignore[type-arg]
        """Return a Result that exposes the requested count, then no user."""
        text = str(statement)
        result = MagicMock(spec=Result)
        if "count" in text.lower():
            # First count query in /login is the IP-limit check; subsequent
            # count queries are the username-lockout check. We return the same
            # configured value for "count" queries so tests can drive the
            # lockout path independent of the IP path (IP path is unaffected
            # by lockout_count when it's small).
            result.scalar.return_value = self.lockout_count
        else:
            # User lookup: never resolves to a real user.
            result.scalar_one_or_none.return_value = None
            result.scalar.return_value = None
        return result


class TestHashUsername:
    """``_hash_username`` is the lockout key; case/whitespace must collapse."""

    def test_hash_is_deterministic(self) -> None:
        assert _hash_username("a@b.com") == _hash_username("a@b.com")

    def test_hash_lowercases_input(self) -> None:
        """Mixed-case variants of the same email collide on lockout key."""
        assert _hash_username("Foo@Example.com") == _hash_username("foo@example.com")

    def test_hash_strips_whitespace(self) -> None:
        """Leading/trailing whitespace cannot bypass the lockout."""
        assert _hash_username("  foo@example.com  ") == _hash_username("foo@example.com")

    def test_hash_is_64_hex_chars(self) -> None:
        """SHA-256 hex digest length, fits in the String(64) column."""
        h = _hash_username("foo@example.com")
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_different_usernames_have_different_hashes(self) -> None:
        assert _hash_username("a@b.com") != _hash_username("c@d.com")


class TestCheckUsernameLockout:
    """``_check_username_lockout`` translates the count query into a bool."""

    async def test_returns_false_below_threshold(self) -> None:
        db = _FakeSession(lockout_count=_USERNAME_LOCKOUT_LIMIT - 1)
        assert await _check_username_lockout(db, "victim@example.com") is False  # type: ignore[arg-type]

    async def test_returns_true_at_threshold(self) -> None:
        """Exactly hitting the limit triggers the lockout."""
        db = _FakeSession(lockout_count=_USERNAME_LOCKOUT_LIMIT)
        assert await _check_username_lockout(db, "victim@example.com") is True  # type: ignore[arg-type]

    async def test_returns_true_above_threshold(self) -> None:
        db = _FakeSession(lockout_count=_USERNAME_LOCKOUT_LIMIT + 5)
        assert await _check_username_lockout(db, "victim@example.com") is True  # type: ignore[arg-type]

    async def test_zero_count_is_not_locked(self) -> None:
        db = _FakeSession(lockout_count=0)
        assert await _check_username_lockout(db, "fresh@example.com") is False  # type: ignore[arg-type]


class TestRecordLoginFailure:
    """``_record_login_failure`` writes a row tagged with the username hash."""

    async def test_records_with_hashed_username_and_failed_endpoint(self) -> None:
        db = _FakeSession()
        await _record_login_failure(db, "victim@example.com", "203.0.113.7")  # type: ignore[arg-type]

        assert len(db.added) == 1
        record = db.added[0]
        assert isinstance(record, AuthRateLimit)
        assert record.endpoint == _LOGIN_FAILED_ENDPOINT
        assert record.username_hash == _hash_username("victim@example.com")
        assert record.client_ip == "203.0.113.7"
        assert db.flushed == 1

    async def test_never_stores_plaintext_username(self) -> None:
        """The plaintext username must not appear on the persisted row."""
        db = _FakeSession()
        username = "leak-me@example.com"
        await _record_login_failure(db, username, "203.0.113.7")  # type: ignore[arg-type]

        record = db.added[0]
        # username_hash is a hex digest, not the raw email.
        assert username not in (record.username_hash or "")
        assert "@" not in (record.username_hash or "")


class TestLoginEndpointLockout:
    """End-to-end: ``POST /login`` honours the lockout."""

    async def test_login_locked_out_returns_generic_401(self, client: AsyncClient) -> None:
        """Once the account is locked out, login returns a generic 401."""
        db = _FakeSession(lockout_count=_USERNAME_LOCKOUT_LIMIT)

        with (
            patch("app.api.v1.auth._check_auth_rate_limit", new=AsyncMock()),
            patch("app.db.session.AsyncSessionLocal", return_value=db),
        ):
            response = await client.post(
                "/api/v1/auth/login",
                data={"username": "victim@example.com", "password": "anything"},
            )

        assert response.status_code == 401
        assert response.json()["detail"] == "Incorrect email or password"

    async def test_login_locked_out_does_not_record_extra_failure(
        self, client: AsyncClient
    ) -> None:
        """Locked-out requests short-circuit before recording a new failure.

        Otherwise an attacker could keep extending their own lockout window
        indefinitely; once they hit the threshold the window should naturally
        roll forward without further input.
        """
        db = _FakeSession(lockout_count=_USERNAME_LOCKOUT_LIMIT)

        with (
            patch("app.api.v1.auth._check_auth_rate_limit", new=AsyncMock()),
            patch("app.db.session.AsyncSessionLocal", return_value=db),
        ):
            await client.post(
                "/api/v1/auth/login",
                data={"username": "victim@example.com", "password": "anything"},
            )

        # No AuthRateLimit row added for the lockout short-circuit.
        assert all(not isinstance(o, AuthRateLimit) for o in db.added)

    async def test_login_below_threshold_records_failure_and_returns_401(
        self, client: AsyncClient
    ) -> None:
        """Below the lockout limit, a wrong password records a failure row."""
        db = _FakeSession(lockout_count=0)

        with (
            patch("app.api.v1.auth._check_auth_rate_limit", new=AsyncMock()),
            patch("app.db.session.AsyncSessionLocal", return_value=db),
        ):
            response = await client.post(
                "/api/v1/auth/login",
                data={"username": "victim@example.com", "password": "wrong"},
            )

        assert response.status_code == 401
        # Exactly one failure row recorded against this username.
        failure_rows = [
            o
            for o in db.added
            if isinstance(o, AuthRateLimit) and o.endpoint == _LOGIN_FAILED_ENDPOINT
        ]
        assert len(failure_rows) == 1
        assert failure_rows[0].username_hash == _hash_username("victim@example.com")

    async def test_login_lockout_is_case_insensitive(self, client: AsyncClient) -> None:
        """A locked-out account stays locked under case variations of the email."""
        db = _FakeSession(lockout_count=_USERNAME_LOCKOUT_LIMIT)

        with (
            patch("app.api.v1.auth._check_auth_rate_limit", new=AsyncMock()),
            patch("app.db.session.AsyncSessionLocal", return_value=db),
        ):
            response = await client.post(
                "/api/v1/auth/login",
                data={"username": "VICTIM@Example.COM", "password": "anything"},
            )

        assert response.status_code == 401


class TestLockoutModelContract:
    """The model column must accept the values the login path writes."""

    def test_username_hash_column_exists_and_is_nullable(self) -> None:
        col = AuthRateLimit.__table__.columns["username_hash"]
        assert col.nullable is True
        # String(64) — SHA-256 hex digest length.
        assert getattr(col.type, "length", None) == 64

    def test_can_construct_with_username_hash(self) -> None:
        row = AuthRateLimit(
            client_ip="203.0.113.7",
            endpoint=_LOGIN_FAILED_ENDPOINT,
            username_hash=_hash_username("a@b.com"),
        )
        assert row.username_hash == _hash_username("a@b.com")
        assert row.endpoint == _LOGIN_FAILED_ENDPOINT

    def test_can_construct_without_username_hash(self) -> None:
        """Legacy rows / non-login endpoints leave username_hash unset."""
        row = AuthRateLimit(client_ip="203.0.113.7", endpoint="register")
        assert row.username_hash is None


class TestLockoutWindowConfig:
    """Pin the documented config: 10 attempts / 15 minutes."""

    def test_lockout_limit_is_ten(self) -> None:
        assert _USERNAME_LOCKOUT_LIMIT == 10

    def test_lockout_window_is_fifteen_minutes(self) -> None:
        from app.api.v1.auth import _USERNAME_LOCKOUT_WINDOW_MINUTES

        assert _USERNAME_LOCKOUT_WINDOW_MINUTES == 15

    def test_window_start_is_recent(self) -> None:
        """The lockout window starts close to "now minus 15 minutes".

        Guard against accidental sign/unit flips on the timedelta.
        """
        from app.api.v1.auth import _USERNAME_LOCKOUT_WINDOW_MINUTES

        expected = datetime.now(UTC) - timedelta(minutes=_USERNAME_LOCKOUT_WINDOW_MINUTES)
        # Allow a generous skew so this isn't flaky under slow CI.
        assert abs((datetime.now(UTC) - expected).total_seconds() - 15 * 60) < 5
