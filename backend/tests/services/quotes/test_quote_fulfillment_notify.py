"""Accepting a quote emails the workspace the distributor parts list.

``proposal_document.fulfillment`` is the aggregated SKU bill-of-materials for
the accepted tier — the sheet someone has to hand the distributor to order the
job. Before this, it was computed, stored, and never read by anything. These
tests pin the hand-off: the notification fires on approval with every SKU and
quantity, stays quiet for quotes that have no parts, and can never take the
approval down with it.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from app.models.quote import Quote
from app.services.notifications import NotificationDispatchResult
from app.services.quotes import QuoteService
from app.services.quotes import quote_service as quote_service_module

pytestmark = pytest.mark.asyncio


def _quote(document: dict[str, Any] | None) -> Quote:
    # Column defaults only apply on flush; this instance never hits the DB, so
    # the numeric/timestamp fields QuoteDetailResponse requires are set here.
    now = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)
    return Quote(
        id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        number="QUO-000042",
        status="approved",
        currency="USD",
        subtotal=5200,
        tax_amount=0,
        discount_amount=0,
        total=5200,
        attach_count=0,
        attach_value=0,
        created_at=now,
        updated_at=now,
        proposal_document=document,
    )


def _capture(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Record notify_workspace_event calls instead of sending anything."""
    calls: list[dict[str, Any]] = []

    async def _fake(db: object, **kwargs: Any) -> NotificationDispatchResult:
        calls.append(kwargs)
        return NotificationDispatchResult(push_sent=True, emails_sent=1)

    monkeypatch.setattr(quote_service_module, "notify_workspace_event", _fake)
    return calls


async def test_approved_quote_emails_every_sku_and_quantity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _capture(monkeypatch)
    quote = _quote(
        {
            "client": {"first_name": "Dana", "last_name": "Homeowner"},
            "fulfillment": [
                {"sku": "59409312", "description": "Luxor 300W Transformer", "qty": 1},
                {"sku": "59308530", "description": "MR16 Lamp", "qty": 12},
                {"sku": "BM-050-C-AB", "description": "Mounting Bracket", "qty": 4},
            ],
        }
    )

    await QuoteService(db=None)._notify_fulfillment_parts(quote)  # type: ignore[arg-type]

    assert len(calls) == 1
    sent = calls[0]
    details = sent["email_details"]
    # Every SKU is an addressable row with its quantity and description.
    assert set(details) == {"59409312", "59308530", "BM-050-C-AB"}
    assert details["59409312"] == "Qty 1 — Luxor 300W Transformer"
    assert details["59308530"] == "Qty 12 — MR16 Lamp"
    assert details["BM-050-C-AB"] == "Qty 4 — Mounting Bracket"
    # The operator can tell which job to order for from the subject line alone.
    assert "QUO-000042" in sent["email_subject"]
    assert "Dana Homeowner" in sent["email_intro"]
    assert "3 SKUs" in sent["email_intro"]
    # Deduped per quote so an approve retry can't double-order.
    assert sent["dedupe_key"] == f"quote_fulfillment:{quote.id}"


async def test_quantities_render_without_trailing_zeros(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Whole counts read as ``2``, not ``2.0``; fractional runs keep precision."""
    calls = _capture(monkeypatch)
    quote = _quote(
        {
            "fulfillment": [
                {"sku": "AAA", "description": "Whole", "qty": 2.0},
                {"sku": "BBB", "description": "Partial", "qty": 1.5},
                {"sku": "CCC", "qty": 3},
            ]
        }
    )

    await QuoteService(db=None)._notify_fulfillment_parts(quote)  # type: ignore[arg-type]

    details = calls[0]["email_details"]
    assert details["AAA"] == "Qty 2 — Whole"
    assert details["BBB"] == "Qty 1.5 — Partial"
    # No description on file — still orderable by SKU and count.
    assert details["CCC"] == "Qty 3"


@pytest.mark.parametrize(
    "document",
    [
        pytest.param(None, id="flat-quote-no-document"),
        pytest.param({}, id="document-without-fulfillment"),
        pytest.param({"fulfillment": []}, id="empty-parts-list"),
        pytest.param({"fulfillment": [{"sku": "  ", "qty": 1}]}, id="blank-sku-only"),
        pytest.param({"fulfillment": ["not-a-dict"]}, id="malformed-entry"),
    ],
)
async def test_no_email_when_there_is_nothing_to_order(
    monkeypatch: pytest.MonkeyPatch, document: dict[str, Any] | None
) -> None:
    calls = _capture(monkeypatch)
    await QuoteService(db=None)._notify_fulfillment_parts(_quote(document))  # type: ignore[arg-type]
    assert calls == []


async def test_mail_failure_never_breaks_the_approval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The quote is already committed as approved — a mail outage must not raise."""

    async def _boom(db: object, **kwargs: Any) -> NotificationDispatchResult:
        raise RuntimeError("resend is down")

    monkeypatch.setattr(quote_service_module, "notify_workspace_event", _boom)
    quote = _quote({"fulfillment": [{"sku": "59409312", "qty": 1}]})

    await QuoteService(db=None)._notify_fulfillment_parts(quote)  # type: ignore[arg-type]


async def test_approve_quote_fires_the_parts_notification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Wiring check: the public/operator approve path reaches the notifier.

    Both client approval (``approve_public``) and operator approval funnel
    through ``approve_quote``, so covering it covers both.
    """
    quote = _quote({"fulfillment": [{"sku": "59409312", "description": "Luxor", "qty": 1}]})
    quote.status = "sent"
    quote.line_items = []
    notified: list[Quote] = []

    async def _no_expire(self: object, workspace_id: uuid.UUID) -> None:
        return None

    async def _get(*args: Any, **kwargs: Any) -> Quote:
        return quote

    async def _no_event(self: object, q: Quote, event_type: str) -> None:
        return None

    async def _track(self: object, q: Quote) -> None:
        notified.append(q)

    class _Db:
        async def commit(self) -> None:
            return None

        async def refresh(self, obj: object, attrs: list[str] | None = None) -> None:
            return None

    monkeypatch.setattr(QuoteService, "_expire_overdue", _no_expire)
    monkeypatch.setattr(QuoteService, "_emit_lifecycle_event", _no_event)
    monkeypatch.setattr(QuoteService, "_notify_fulfillment_parts", _track)
    monkeypatch.setattr(quote_service_module, "get_or_404", _get)

    await QuoteService(db=_Db()).approve_quote(quote.workspace_id, quote.id)  # type: ignore[arg-type]

    assert notified == [quote]
    assert quote.status == "approved"


async def test_already_approved_quote_does_not_reorder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Re-approving is a no-op, so the distributor never gets a second order."""
    quote = _quote({"fulfillment": [{"sku": "59409312", "qty": 1}]})
    quote.status = "approved"
    quote.line_items = []
    notified: list[Quote] = []

    async def _no_expire(self: object, workspace_id: uuid.UUID) -> None:
        return None

    async def _get(*args: Any, **kwargs: Any) -> Quote:
        return quote

    async def _track(self: object, q: Quote) -> None:
        notified.append(q)

    monkeypatch.setattr(QuoteService, "_expire_overdue", _no_expire)
    monkeypatch.setattr(QuoteService, "_notify_fulfillment_parts", _track)
    monkeypatch.setattr(quote_service_module, "get_or_404", _get)

    await QuoteService(db=None).approve_quote(quote.workspace_id, quote.id)  # type: ignore[arg-type]

    assert notified == []
