"""Tests for the CRM assistant's quote, invoice, job and review read tools.

Two properties are load-bearing here and are asserted directly rather than
inferred from the happy path:

1. **No token ever reaches model context.** ``QuoteResponse`` carries
   ``public_token``, the unguessable key to the customer proposal page. Tool
   results become model context, and inbound customer SMS reaches that same
   context, so a leaked token is an exfiltration path rather than a cosmetic bug.
2. **The tool boundary equals the HTTP boundary.** Each tool must apply the same
   capability and owner scope its route applies, otherwise the assistant is a
   side door around the router gates.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.roles import WorkspaceRole
from app.schemas.quote import QuoteResponse
from app.services.ai.crm_assistant._quote_tools import _QUOTE_FIELDS
from app.services.ai.crm_assistant._tool_executor import CRMToolExecutor
from app.services.ai.crm_assistant._tools import get_crm_tools, tools_for_role

OWNER = WorkspaceRole.OWNER.value
SALES_REP = WorkspaceRole.SALES_REP.value


@pytest.fixture
def workspace_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def db() -> MagicMock:
    session = MagicMock()
    session.execute = AsyncMock()
    session.scalar = AsyncMock(return_value=None)
    return session


class _Page:
    """Stand-in for a paginated service response."""

    def __init__(self, items: list[Any], total: int | None = None) -> None:
        self.items = items
        self.total = len(items) if total is None else total


def _quote_response(**overrides: Any) -> QuoteResponse:
    defaults: dict[str, Any] = {
        "id": uuid.uuid4(),
        "workspace_id": uuid.uuid4(),
        "contact_id": 101,
        "assigned_user_id": 7,
        "number": "Q-1001",
        "title": "Holiday lighting install",
        "status": "sent",
        "subtotal": 1000.0,
        "tax_amount": 80.0,
        "discount_amount": 0.0,
        "total": 1080.0,
        "currency": "USD",
        "view_count": 3,
        # The whole point of the allowlist: present on the schema, must not escape.
        "public_token": "super-secret-proposal-token",
        "created_at": datetime(2026, 5, 1, tzinfo=UTC),
        "updated_at": datetime(2026, 5, 2, tzinfo=UTC),
    }
    defaults.update(overrides)
    return QuoteResponse.model_validate(defaults)


# ---------------------------------------------------------------------------
# Disclosure
# ---------------------------------------------------------------------------


async def test_list_quotes_never_leaks_the_public_proposal_token(
    db: MagicMock, workspace_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The customer-page token must not enter model context."""
    quote = _quote_response()
    monkeypatch.setattr(
        "app.services.quotes.quote_service.QuoteService.list_quotes",
        AsyncMock(return_value=_Page([quote])),
    )
    executor = CRMToolExecutor(db=db, workspace_id=workspace_id, user_id=7, role=OWNER)

    result = await executor.execute("list_quotes", {"limit": 5})

    assert result["success"] is True
    row = result["data"][0]
    assert "public_token" not in row
    assert "super-secret-proposal-token" not in str(result)
    # The useful fields still survive the projection.
    assert row["number"] == "Q-1001"
    assert row["total"] == 1080.0
    assert row["status"] == "sent"


def test_quote_allowlist_excludes_every_known_secret_field() -> None:
    """A new sensitive field on QuoteResponse stays out unless explicitly added."""
    forbidden = {
        "public_token",
        "deposit_checkout_session_id",
        "deposit_payment_intent_id",
        "proposal_payment_checkout_session_id",
        "proposal_payment_intent_id",
    }
    assert _QUOTE_FIELDS & forbidden == set()
    # And the allowlist may not drift beyond fields the schema actually has.
    assert set(QuoteResponse.model_fields) >= _QUOTE_FIELDS


async def test_get_invoice_does_not_return_payment_references(
    db: MagicMock, workspace_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Manual payment references and per-payment rows stay out of model context."""
    invoice = MagicMock()
    invoice.model_dump.return_value = {
        "id": str(uuid.uuid4()),
        "number": "INV-9",
        "total": 500.0,
        "amount_paid": 500.0,
        "line_items": [
            {"id": 1, "description": "Install", "quantity": 1, "unit_price": 500.0, "total": 500.0}
        ],
        "payments": [{"id": 1, "reference": "cheque 8891 from J. Smith"}],
    }
    monkeypatch.setattr(
        "app.services.invoices.invoice_service.InvoiceService.get_invoice",
        AsyncMock(return_value=invoice),
    )
    executor = CRMToolExecutor(db=db, workspace_id=workspace_id, user_id=7, role=OWNER)

    result = await executor.execute("get_invoice", {"invoice_id": str(uuid.uuid4())})

    assert result["success"] is True
    assert "payments" not in result["data"]
    assert "cheque 8891" not in str(result)
    assert result["data"]["line_items"][0]["description"] == "Install"


# ---------------------------------------------------------------------------
# Authorization: the tool boundary equals the route boundary
# ---------------------------------------------------------------------------


async def test_sales_rep_cannot_read_invoices(db: MagicMock, workspace_id: uuid.UUID) -> None:
    """`billing:read` gates invoices on the route, so it must gate the tool too."""
    executor = CRMToolExecutor(db=db, workspace_id=workspace_id, user_id=7, role=SALES_REP)

    result = await executor.execute("list_invoices", {})

    assert result["success"] is False
    assert result["code"] == "not_permitted"


def test_sales_rep_is_not_offered_invoice_tools() -> None:
    offered = {tool["function"]["name"] for tool in tools_for_role(SALES_REP)}
    assert "list_invoices" not in offered
    assert "get_invoice" not in offered
    # ...but quotes and jobs are theirs to read.
    assert {"list_quotes", "get_quote", "list_jobs"} <= offered


async def test_list_quotes_confines_the_sales_tier_to_its_own_quotes(
    db: MagicMock, workspace_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The sales tier is owner-scoped; an admin tier sees the whole workspace."""
    list_quotes = AsyncMock(return_value=_Page([]))
    monkeypatch.setattr("app.services.quotes.quote_service.QuoteService.list_quotes", list_quotes)

    sales = CRMToolExecutor(db=db, workspace_id=workspace_id, user_id=7, role=SALES_REP)
    await sales.execute("list_quotes", {})
    assert list_quotes.await_args.kwargs["owner_user_id"] == 7

    owner = CRMToolExecutor(db=db, workspace_id=workspace_id, user_id=9, role=OWNER)
    await owner.execute("list_quotes", {})
    assert list_quotes.await_args.kwargs["owner_user_id"] is None


async def test_get_quote_hides_a_quote_outside_the_callers_owner_scope(
    db: MagicMock, workspace_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An out-of-scope id reads as not-found, never as another rep's quote."""
    db.scalar = AsyncMock(return_value=None)  # owner predicate matches nothing
    get_quote = AsyncMock(return_value=_quote_response())
    monkeypatch.setattr("app.services.quotes.quote_service.QuoteService.get_quote", get_quote)
    executor = CRMToolExecutor(db=db, workspace_id=workspace_id, user_id=7, role=SALES_REP)

    result = await executor.execute("get_quote", {"quote_id": str(uuid.uuid4())})

    assert result["success"] is False
    assert result["code"] == "not_found"
    # The record must not be loaded at all once the scope check fails.
    get_quote.assert_not_awaited()


async def test_list_jobs_confines_non_dispatchers_to_their_own_work(
    db: MagicMock, workspace_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Below the dispatch line (`jobs:write`) a caller sees only jobs they are on."""
    job_list = AsyncMock(return_value={"items": [], "total": 0})
    monkeypatch.setattr("app.services.jobs.job_service.JobService.list", job_list)

    sales = CRMToolExecutor(db=db, workspace_id=workspace_id, user_id=7, role=SALES_REP)
    await sales.execute("list_jobs", {})
    assert job_list.await_args.kwargs["visible_to_user_id"] == 7

    owner = CRMToolExecutor(db=db, workspace_id=workspace_id, user_id=9, role=OWNER)
    await owner.execute("list_jobs", {})
    assert job_list.await_args.kwargs["visible_to_user_id"] is None


# ---------------------------------------------------------------------------
# Argument handling
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("tool", "args"),
    [
        ("list_quotes", {"limit": 0}),
        ("list_quotes", {"limit": True}),
        ("list_quotes", {"limit": 999}),
        ("list_invoices", {"contact_id": "not-an-int"}),
        ("list_jobs", {"status": "teleported"}),
        ("list_jobs", {"date_from": "not-a-date"}),
        ("list_reviews", {"is_public": "yes"}),
    ],
)
async def test_bad_arguments_are_rejected_before_any_query(
    db: MagicMock, workspace_id: uuid.UUID, tool: str, args: dict[str, Any]
) -> None:
    executor = CRMToolExecutor(db=db, workspace_id=workspace_id, user_id=7, role=OWNER)

    result = await executor.execute(tool, args)

    assert result["success"] is False
    assert result["code"] == "invalid_argument"


async def test_get_job_rejects_a_malformed_id(db: MagicMock, workspace_id: uuid.UUID) -> None:
    executor = CRMToolExecutor(db=db, workspace_id=workspace_id, user_id=7, role=OWNER)

    result = await executor.execute("get_job", {"job_id": "not-a-uuid"})

    assert result["success"] is False
    assert result["code"] == "invalid_argument"


async def test_list_jobs_reports_the_true_total_when_truncated(
    db: MagicMock, workspace_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`total` describes the world, `returned` describes the page."""
    jobs = [MagicMock(**{"model_dump.return_value": {"id": i}}) for i in range(5)]
    monkeypatch.setattr(
        "app.services.jobs.job_service.JobService.list",
        AsyncMock(return_value={"items": jobs, "total": 5}),
    )
    executor = CRMToolExecutor(db=db, workspace_id=workspace_id, user_id=7, role=OWNER)

    result = await executor.execute("list_jobs", {"limit": 2})

    assert result["returned"] == 2
    assert result["total"] == 5
    assert result["has_more"] is True


# ---------------------------------------------------------------------------
# Catalog wiring
# ---------------------------------------------------------------------------


def test_new_read_tools_are_declared_and_need_no_approval() -> None:
    """These are reads: they must never queue a human approval."""
    from app.services.ai.crm_assistant._tool_metadata import get_tool_policy

    names = {
        "list_quotes",
        "get_quote",
        "list_invoices",
        "get_invoice",
        "list_jobs",
        "get_job",
        "list_reviews",
    }
    declared = {tool["function"]["name"] for tool in get_crm_tools()}
    assert names <= declared
    for name in names:
        assert get_tool_policy(name).requires_approval is False
