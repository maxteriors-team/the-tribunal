"""Owner-scoped quote access and dedicated quote capability tests."""

from __future__ import annotations

import inspect
import types
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy.dialects import postgresql

from app.api.v1 import quotes
from app.core.permissions import Capability, quote_owner_scope, role_can
from app.models.quote import Quote
from app.schemas.quote import QuoteApproveRequest
from app.services.quotes.proposal_pricing import BistroPricingConfigurationError

WORKSPACE_ID = uuid.uuid4()
QUOTE_ID = uuid.uuid4()


def _actor(user_id: int = 11) -> types.SimpleNamespace:
    return types.SimpleNamespace(id=user_id, is_active=True)


def _membership(role: str) -> types.SimpleNamespace:
    return types.SimpleNamespace(role=role, workspace_id=WORKSPACE_ID)


def _result(value: Quote | None) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _executed_sql(db: AsyncMock) -> str:
    statement = db.execute.await_args.args[0]
    return str(
        statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )


async def test_sales_quote_lookup_is_workspace_and_owner_scoped() -> None:
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_result(None))

    with pytest.raises(HTTPException) as exc_info:
        await quotes._scoped_quote(
            WORKSPACE_ID,
            QUOTE_ID,
            _actor(11),
            _membership("sales_rep"),
            db,
        )

    assert exc_info.value.status_code == 404
    sql = _executed_sql(db)
    assert "quotes.workspace_id" in sql
    assert "quotes.assigned_user_id = 11" in sql
    assert "quotes.assigned_user_id IS NULL" in sql
    assert "quotes.created_by_id = 11" in sql


async def test_manager_quote_lookup_remains_workspace_wide() -> None:
    quote = Quote(id=QUOTE_ID, workspace_id=WORKSPACE_ID, number="Q-1")
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_result(quote))

    assert (
        await quotes._scoped_quote(
            WORKSPACE_ID,
            QUOTE_ID,
            _actor(20),
            _membership("manager"),
            db,
        )
        is quote
    )
    sql = _executed_sql(db)
    where_clause = sql.split("WHERE", 1)[1]
    assert "quotes.workspace_id" in where_clause
    assert "quotes.assigned_user_id" not in where_clause
    assert quote_owner_scope("manager", 20) is None


async def test_sales_list_forces_owner_scope() -> None:
    service = MagicMock()
    service.list_quotes = AsyncMock(return_value=MagicMock())

    with patch.object(quotes, "QuoteService", return_value=service):
        await quotes.list_quotes(
            WORKSPACE_ID,
            _actor(11),
            AsyncMock(),
            _membership("sales_rep"),
        )

    assert service.list_quotes.await_args.kwargs["owner_user_id"] == 11


async def test_sales_created_quotes_are_forced_to_the_caller() -> None:
    service = MagicMock()
    service.create_quote = AsyncMock(return_value=MagicMock())
    payload = MagicMock()

    with patch.object(quotes, "QuoteService", return_value=service):
        await quotes.create_quote(
            WORKSPACE_ID,
            payload,
            _actor(11),
            AsyncMock(),
            _membership("sales_rep"),
        )

    service.create_quote.assert_awaited_once_with(
        WORKSPACE_ID,
        payload,
        created_by_id=11,
        assigned_user_id=11,
    )


async def test_sales_wizard_and_estimate_quotes_are_forced_to_the_caller() -> None:
    service = MagicMock()
    service.save_from_wizard = AsyncMock(return_value=MagicMock())
    service.create_quote_from_estimate = AsyncMock(return_value=MagicMock())
    payload = MagicMock()
    actor = _actor(11)
    membership = _membership("sales_rep")

    with patch.object(quotes, "QuoteService", return_value=service):
        await quotes.save_wizard_proposal(WORKSPACE_ID, payload, actor, AsyncMock(), membership)
        await quotes.convert_estimate_to_quote(
            WORKSPACE_ID, payload, actor, AsyncMock(), membership
        )

    service.save_from_wizard.assert_awaited_once_with(
        WORKSPACE_ID,
        payload,
        created_by_id=11,
        assigned_user_id=11,
    )
    service.create_quote_from_estimate.assert_awaited_once_with(
        WORKSPACE_ID,
        payload,
        created_by_id=11,
        assigned_user_id=11,
    )


async def test_bistro_configuration_errors_map_to_conflict_for_every_wizard_route() -> None:
    error = BistroPricingConfigurationError("Configure Bistro Pricing before creating this quote.")
    service = MagicMock()
    service.preview_from_wizard = AsyncMock(side_effect=error)
    service.save_from_wizard = AsyncMock(side_effect=error)
    service.update_from_wizard = AsyncMock(side_effect=error)
    service.revise_from_wizard = AsyncMock(side_effect=error)
    payload = MagicMock()
    actor = _actor(11)
    membership = _membership("sales_rep")
    db = AsyncMock()
    quote = MagicMock()

    calls = (
        lambda: quotes.preview_wizard_proposal(WORKSPACE_ID, payload, actor, db, membership),
        lambda: quotes.save_wizard_proposal(WORKSPACE_ID, payload, actor, db, membership),
        lambda: quotes.update_wizard_proposal(
            WORKSPACE_ID, QUOTE_ID, payload, quote, actor, db, membership
        ),
        lambda: quotes.revise_wizard_proposal(
            WORKSPACE_ID, QUOTE_ID, payload, quote, actor, db, membership
        ),
    )

    with patch.object(quotes, "QuoteService", return_value=service):
        for call in calls:
            with pytest.raises(HTTPException) as exc_info:
                await call()
            assert exc_info.value.status_code == 409
            assert exc_info.value.detail == str(error)


async def test_sales_can_send_a_quote_after_owner_scope_resolves() -> None:
    service = MagicMock()
    service.mark_sent = AsyncMock(return_value=MagicMock())

    with patch.object(quotes, "QuoteService", return_value=service):
        await quotes.send_quote(
            WORKSPACE_ID,
            QUOTE_ID,
            MagicMock(),
            _actor(11),
            AsyncMock(),
            _membership("sales_rep"),
        )

    service.mark_sent.assert_awaited_once_with(WORKSPACE_ID, QUOTE_ID)


async def test_operator_approval_forwards_only_the_payment_enum() -> None:
    service = MagicMock()
    service.approve_quote = AsyncMock(return_value=MagicMock())

    with patch.object(quotes, "QuoteService", return_value=service):
        await quotes.approve_quote(
            WORKSPACE_ID,
            QUOTE_ID,
            MagicMock(),
            _actor(11),
            AsyncMock(),
            _membership("manager"),
            QuoteApproveRequest(payment_option="cash_check"),
        )

    service.approve_quote.assert_awaited_once_with(
        WORKSPACE_ID, QUOTE_ID, payment_option="cash_check"
    )


def test_salespeople_cannot_read_private_profitability() -> None:
    assert role_can("sales_rep", Capability.BILLING_READ) is False
    assert role_can("owner", Capability.BILLING_READ) is True


def test_every_authenticated_quote_id_route_uses_scoped_dependency() -> None:
    for route in quotes.router.routes:
        endpoint = getattr(route, "endpoint", None)
        if endpoint is None or "quote_id" not in inspect.signature(endpoint).parameters:
            continue
        assert "_quote" in inspect.signature(endpoint).parameters, endpoint.__name__
