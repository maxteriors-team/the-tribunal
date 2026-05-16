"""End-to-end-ish tests for ``Retry-After`` on DB-backed 429 responses.

These exercise the per-endpoint rate-limit checks in ``demo.py``, ``embed.py``,
``lead_form.py``, and ``auth.py`` by stubbing ``db.execute`` to simulate an
over-the-cap row count. The point isn't to re-test SQLAlchemy — it's to pin
the contract that every 429 from these helpers carries a ``Retry-After``
header derived from the rolling-window state.
"""

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.api.v1 import auth as auth_api
from app.api.v1 import demo as demo_api
from app.api.v1 import embed as embed_api
from app.api.v1 import lead_form as lead_form_api
from app.core.config import settings


def _exec_result(count: int, oldest: datetime | None) -> MagicMock:
    """Build a ``db.execute()`` return value that mimics a one-row result."""
    result = MagicMock()
    result.one.return_value = (count, oldest)
    # Some legacy call sites in the file still use ``.scalar()``; keep both
    # branches alive so a fixture works for both shapes.
    result.scalar.return_value = count
    return result


def _make_db(*results: MagicMock) -> AsyncMock:
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=list(results))
    return db


class TestDemoCheckRateLimits:
    async def test_ip_429_carries_retry_after_from_oldest_record(self) -> None:
        """Hour window, oldest record 10 minutes old → retry in 50 minutes."""
        now = datetime.now(UTC)
        oldest = now - timedelta(minutes=10)
        db = _make_db(_exec_result(settings.demo_ip_rate_limit, oldest))

        with pytest.raises(HTTPException) as exc_info:
            await demo_api.check_rate_limits(db, "1.2.3.4", "+15558675309", "call")

        assert exc_info.value.status_code == 429
        assert exc_info.value.headers is not None
        retry_after = int(exc_info.value.headers["Retry-After"])
        # Hour window (3600s) minus ~600s elapsed = ~3000s, ±a few seconds.
        assert 2990 <= retry_after <= 3010

    async def test_phone_429_carries_retry_after_from_day_window(self) -> None:
        """IP check passes; phone check trips on the daily cap."""
        now = datetime.now(UTC)
        oldest = now - timedelta(hours=6)
        db = _make_db(
            _exec_result(0, None),  # IP under cap
            _exec_result(settings.demo_phone_rate_limit, oldest),  # phone over
        )

        with pytest.raises(HTTPException) as exc_info:
            await demo_api.check_rate_limits(db, "1.2.3.4", "+15558675309", "call")

        assert exc_info.value.status_code == 429
        assert exc_info.value.headers is not None
        retry_after = int(exc_info.value.headers["Retry-After"])
        # Day window (86400s) minus ~6h elapsed = ~64800s, ±a few seconds.
        assert 64790 <= retry_after <= 64810
        assert "phone" in exc_info.value.detail.lower()

    async def test_retry_after_falls_back_when_oldest_is_missing(self) -> None:
        """Defensive path: no oldest record → fall back to full window."""
        db = _make_db(_exec_result(settings.demo_ip_rate_limit, None))

        with pytest.raises(HTTPException) as exc_info:
            await demo_api.check_rate_limits(db, "1.2.3.4", "+15558675309", "call")

        assert exc_info.value.headers is not None
        assert exc_info.value.headers["Retry-After"] == "3600"

    async def test_under_limit_does_not_raise(self) -> None:
        db = _make_db(
            _exec_result(0, None),
            _exec_result(0, None),
        )
        # Must not raise.
        await demo_api.check_rate_limits(db, "1.2.3.4", "+15558675309", "call")

    async def test_bypass_phone_skips_all_checks(self) -> None:
        """Bypass list short-circuits before any DB call — no header to check,
        but we assert the function returns cleanly with an empty mock DB."""
        bypass = next(iter(settings.demo_rate_limit_bypass_phones), None)
        if not bypass:
            pytest.skip("no bypass phones configured for this env")
        db = AsyncMock()
        await demo_api.check_rate_limits(db, "1.2.3.4", bypass, "call")
        db.execute.assert_not_called()


class TestEmbedCheckRateLimits:
    async def test_ip_429_carries_retry_after(self) -> None:
        now = datetime.now(UTC)
        oldest = now - timedelta(minutes=5)
        db = _make_db(_exec_result(settings.demo_ip_rate_limit, oldest))

        with pytest.raises(HTTPException) as exc_info:
            await embed_api._check_embed_rate_limits(db, "9.9.9.9", "+15551112222")

        assert exc_info.value.status_code == 429
        assert exc_info.value.headers is not None
        retry_after = int(exc_info.value.headers["Retry-After"])
        # ~3300s remaining of a 3600s window.
        assert 3290 <= retry_after <= 3310

    async def test_phone_429_carries_retry_after(self) -> None:
        now = datetime.now(UTC)
        oldest = now - timedelta(hours=1)
        db = _make_db(
            _exec_result(0, None),
            _exec_result(settings.demo_phone_rate_limit, oldest),
        )

        with pytest.raises(HTTPException) as exc_info:
            await embed_api._check_embed_rate_limits(db, "9.9.9.9", "+15551112222")

        assert exc_info.value.status_code == 429
        assert exc_info.value.headers is not None
        retry_after = int(exc_info.value.headers["Retry-After"])
        # 24h - 1h = ~82800s.
        assert 82790 <= retry_after <= 82810


class TestLeadFormCheckRateLimit:
    async def test_429_carries_retry_after(self) -> None:
        now = datetime.now(UTC)
        oldest = now - timedelta(minutes=15)
        db = _make_db(_exec_result(settings.lead_form_ip_rate_limit, oldest))

        with pytest.raises(HTTPException) as exc_info:
            await lead_form_api._check_lead_form_rate_limit(db, "5.5.5.5")

        assert exc_info.value.status_code == 429
        assert exc_info.value.headers is not None
        retry_after = int(exc_info.value.headers["Retry-After"])
        # ~2700s remaining of a 3600s window.
        assert 2690 <= retry_after <= 2710

    async def test_429_falls_back_to_full_window_without_oldest(self) -> None:
        db = _make_db(_exec_result(settings.lead_form_ip_rate_limit, None))

        with pytest.raises(HTTPException) as exc_info:
            await lead_form_api._check_lead_form_rate_limit(db, "5.5.5.5")

        assert exc_info.value.headers is not None
        assert exc_info.value.headers["Retry-After"] == "3600"

    async def test_under_limit_does_not_raise(self) -> None:
        db = _make_db(_exec_result(0, None))
        await lead_form_api._check_lead_form_rate_limit(db, "5.5.5.5")


class TestAuthCheckRateLimit:
    async def test_429_carries_retry_after(self) -> None:
        now = datetime.now(UTC)
        # 15-minute window per auth.py; oldest 2 min ago → ~780s remaining.
        oldest = now - timedelta(minutes=2)
        # First call is the count+oldest read; the success path also writes a
        # new record, but since we raise before the insert that call never
        # happens — one ``execute`` is enough.
        db = _make_db(_exec_result(auth_api._AUTH_RATE_LIMIT, oldest))
        # The success path calls db.flush() which we leave as a default
        # AsyncMock — never reached when over the cap.

        with pytest.raises(HTTPException) as exc_info:
            await auth_api._check_auth_rate_limit(db, "8.8.8.8", "login")

        assert exc_info.value.status_code == 429
        assert exc_info.value.headers is not None
        retry_after = int(exc_info.value.headers["Retry-After"])
        # 900s window - 120s elapsed = ~780s, ± slack.
        assert 770 <= retry_after <= 790

    async def test_429_falls_back_when_oldest_missing(self) -> None:
        db = _make_db(_exec_result(auth_api._AUTH_RATE_LIMIT, None))

        with pytest.raises(HTTPException) as exc_info:
            await auth_api._check_auth_rate_limit(db, "8.8.8.8", "login")

        assert exc_info.value.headers is not None
        # Full 15-minute window = 900s.
        assert exc_info.value.headers["Retry-After"] == "900"

    async def test_under_limit_records_attempt_and_does_not_raise(self) -> None:
        db = _make_db(_exec_result(0, None))
        db.add = MagicMock()
        db.flush = AsyncMock()

        await auth_api._check_auth_rate_limit(db, "8.8.8.8", "login")

        db.add.assert_called_once()
        db.flush.assert_awaited_once()


# Suppress an unused-import warning if a future refactor drops one of the
# modules above; importing through ``__all__`` would obscure the test target.
_KEEP_REFS: tuple[Any, ...] = (demo_api, embed_api, lead_form_api, auth_api)
