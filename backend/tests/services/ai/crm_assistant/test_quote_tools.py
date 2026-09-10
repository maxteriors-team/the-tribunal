"""The assistant may draft a quote — on a tight leash.

``_quote_tools`` is otherwise read-only on purpose: quotes carry money and a
customer-facing token. ``create_quote`` is the single write, and it is only
acceptable while two properties hold. These tests pin both, because losing
either turns "draft a quote" into "the AI made up a price and someone sent it".

1. **The model cannot name a price.** There is no price field in the schema, and
   every figure is read from the workspace price book.
2. **A human approves before the row exists.**

The third property is scoping: an item from another workspace must not price a
line here.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.permissions import Capability
from app.services.ai.crm_assistant._quote_tools import QuoteAssistantTools
from app.services.ai.crm_assistant._tool_context import CRMToolContext
from app.services.ai.crm_assistant._tool_executor import CRMToolExecutor
from app.services.ai.crm_assistant._tool_metadata import ToolRiskLevel
from app.services.ai.crm_assistant._tools import get_crm_tools

WORKSPACE = uuid.uuid4()
ITEM_ID = uuid.uuid4()
CATALOG_PRICE = 1620.0


def _spec() -> dict:
    return next(t["function"] for t in get_crm_tools() if t["function"]["name"] == "create_quote")


# --------------------------------------------------------------------------- #
# 1. The model cannot name a price
# --------------------------------------------------------------------------- #
def test_the_schema_offers_the_model_no_way_to_state_a_price() -> None:
    """The strongest guarantee available: the field does not exist.

    A hallucinated "roofline is $800" is unrepresentable rather than merely
    rejected, so there is no validation path to get wrong.
    """
    line_props = _spec()["parameters"]["properties"]["line_items"]["items"]["properties"]

    assert set(line_props) == {"catalog_item_id", "quantity"}

    # Every accepted parameter name, at any depth. Checked against the schema
    # rather than the whole spec, since the *description* says "price" on purpose
    # (it tells the model prices come from the price book).
    def property_names(node: object) -> set[str]:
        if not isinstance(node, dict):
            return set()
        found = set(node.get("properties", {}))
        for key in ("properties", "items"):
            child = node.get(key)
            if isinstance(child, dict):
                found |= property_names(child)
                for value in child.values():
                    found |= property_names(value)
        return found

    accepted = property_names(_spec()["parameters"])
    for banned in ("unit_price", "price", "amount", "total", "discount", "subtotal"):
        assert banned not in accepted, f"create_quote accepts {banned!r} from the model"


@pytest.mark.asyncio
async def test_line_prices_come_from_the_price_book() -> None:
    tools = _tools_with_catalog([_catalog_item(ITEM_ID, "C9 Roofline", CATALOG_PRICE)])

    await tools.create_quote(
        {"contact_id": 7, "line_items": [{"catalog_item_id": str(ITEM_ID), "quantity": 2}]}
    )

    quote_in = tools.service.create_quote.await_args.args[1]
    assert [li.unit_price for li in quote_in.line_items] == [CATALOG_PRICE]
    assert [li.quantity for li in quote_in.line_items] == [2.0]
    # The name is the catalog's, not anything the model supplied.
    assert [li.name for li in quote_in.line_items] == ["C9 Roofline"]


@pytest.mark.asyncio
async def test_a_price_smuggled_into_the_arguments_is_ignored() -> None:
    """Even if the model invents the field, the price book still wins."""
    tools = _tools_with_catalog([_catalog_item(ITEM_ID, "C9 Roofline", CATALOG_PRICE)])

    await tools.create_quote(
        {
            "contact_id": 7,
            "line_items": [
                {
                    "catalog_item_id": str(ITEM_ID),
                    "quantity": 1,
                    "unit_price": 25.0,
                    "total": 25.0,
                    "name": "Free roofline",
                }
            ],
        }
    )

    quote_in = tools.service.create_quote.await_args.args[1]
    assert [li.unit_price for li in quote_in.line_items] == [CATALOG_PRICE]
    assert [li.name for li in quote_in.line_items] == ["C9 Roofline"]


# --------------------------------------------------------------------------- #
# 2. A human approves first
# --------------------------------------------------------------------------- #
def test_creating_a_quote_waits_for_human_approval() -> None:
    executor = CRMToolExecutor(db=MagicMock(), workspace_id=WORKSPACE, user_id=1, role="owner")

    metadata = executor.tool_metadata["create_quote"]

    assert metadata.requires_approval is True
    assert metadata.requires_confirmation is True
    assert metadata.risk_level is ToolRiskLevel.HIGH
    assert metadata.required_capability is Capability.QUOTES_WRITE


def test_reading_quotes_still_needs_no_approval() -> None:
    """The gate is on the write only; asking about quotes stays instant."""
    executor = CRMToolExecutor(db=MagicMock(), workspace_id=WORKSPACE, user_id=1, role="owner")

    for name in ("list_quotes", "get_quote"):
        assert executor.tool_metadata[name].requires_approval is False


def test_the_assistant_still_cannot_send_or_approve_a_quote() -> None:
    """Drafting is the *only* write. Anything customer-facing stays off-limits."""
    names = {t["function"]["name"] for t in get_crm_tools()}

    for forbidden in ("send_quote", "approve_quote", "convert_quote", "delete_quote"):
        assert forbidden not in names


# --------------------------------------------------------------------------- #
# 3. Scoping and rejections
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_an_item_from_another_workspace_cannot_price_a_line() -> None:
    # The catalog lookup is workspace-scoped, so a foreign id resolves to
    # nothing and the draft is refused rather than priced at someone else's rate.
    tools = _tools_with_catalog([])

    result = await tools.create_quote(
        {"contact_id": 7, "line_items": [{"catalog_item_id": str(uuid.uuid4()), "quantity": 1}]}
    )

    assert result["success"] is False
    tools.service.create_quote.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "line_items",
    [
        pytest.param([], id="no lines"),
        pytest.param("roofline", id="not a list"),
        pytest.param([{"catalog_item_id": "not-a-uuid", "quantity": 1}], id="bad id"),
        pytest.param([{"catalog_item_id": str(ITEM_ID), "quantity": 0}], id="zero quantity"),
        pytest.param([{"catalog_item_id": str(ITEM_ID), "quantity": -3}], id="negative quantity"),
        pytest.param([{"catalog_item_id": str(ITEM_ID), "quantity": "lots"}], id="text quantity"),
        pytest.param(["roofline"], id="line is not an object"),
    ],
)
async def test_a_malformed_request_drafts_nothing(line_items: object) -> None:
    tools = _tools_with_catalog([_catalog_item(ITEM_ID, "C9 Roofline", CATALOG_PRICE)])

    result = await tools.create_quote({"contact_id": 7, "line_items": line_items})

    assert result["success"] is False
    tools.service.create_quote.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_wall_of_lines_is_refused_so_the_approval_card_stays_readable() -> None:
    tools = _tools_with_catalog([_catalog_item(ITEM_ID, "C9 Roofline", CATALOG_PRICE)])

    result = await tools.create_quote(
        {
            "contact_id": 7,
            "line_items": [{"catalog_item_id": str(ITEM_ID), "quantity": 1}] * 21,
        }
    )

    assert result["success"] is False
    tools.service.create_quote.assert_not_awaited()


@pytest.mark.asyncio
async def test_the_reply_says_the_customer_has_not_seen_it() -> None:
    """Otherwise the operator assumes it went out and never sends it."""
    tools = _tools_with_catalog([_catalog_item(ITEM_ID, "C9 Roofline", CATALOG_PRICE)])

    result = await tools.create_quote(
        {"contact_id": 7, "line_items": [{"catalog_item_id": str(ITEM_ID), "quantity": 1}]}
    )

    assert result["success"] is True
    assert "not been sent" in str(result["message"])


@pytest.mark.asyncio
async def test_the_draft_never_leaks_the_customer_facing_token() -> None:
    """Everything returned becomes model context, which can be echoed outward."""
    tools = _tools_with_catalog([_catalog_item(ITEM_ID, "C9 Roofline", CATALOG_PRICE)])

    result = await tools.create_quote(
        {"contact_id": 7, "line_items": [{"catalog_item_id": str(ITEM_ID), "quantity": 1}]}
    )

    assert "public_token" not in result["data"]
    assert "secret-token" not in str(result)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _catalog_item(item_id: uuid.UUID, name: str, unit_price: float) -> SimpleNamespace:
    return SimpleNamespace(id=item_id, name=name, unit_price=unit_price)


def _tools_with_catalog(items: list[SimpleNamespace]) -> QuoteAssistantTools:
    """A QuoteAssistantTools whose price-book lookup returns ``items``."""
    db = AsyncMock()
    db.execute.return_value = MagicMock(scalars=MagicMock(return_value=items))

    # The real context object, not a stand-in: it is a plain dataclass, so there
    # is nothing to fake and no reason to silence the type checker.
    context = CRMToolContext(db=db, workspace_id=WORKSPACE, user_id=1, role="owner")
    tools = QuoteAssistantTools(context)

    created = MagicMock()
    created.model_dump.return_value = {
        "id": str(uuid.uuid4()),
        "number": "QUO-000123",
        "status": "draft",
        "total": CATALOG_PRICE,
        "public_token": "secret-token",
    }
    tools.service = MagicMock()
    tools.service.create_quote = AsyncMock(return_value=created)
    return tools
