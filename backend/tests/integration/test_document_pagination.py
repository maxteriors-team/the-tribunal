"""Document pagination uses a total order, including equal creation timestamps.

Real Postgres, disposable workspaces, rolled back on session exit. No sending or
payment services are invoked. Run with ``pytest -m integration``.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from app.core.encryption import hash_phone
from app.db.session import AsyncSessionLocal, engine
from app.models.contact import Contact
from app.models.invoice import Invoice
from app.models.quote import Quote
from app.models.workspace import Workspace
from app.services.invoices import InvoiceService
from app.services.quotes import QuoteService

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


@pytest.fixture(autouse=True)
async def fresh_pool() -> AsyncIterator[None]:
    await engine.dispose()
    yield
    await engine.dispose()


@pytest.mark.parametrize("model", [Invoice, Quote])
@pytest.mark.parametrize("total", [0, 1, 100, 101, 305])
async def test_document_pages_are_complete_and_stable(
    model: type[Invoice] | type[Quote], total: int
) -> None:
    async with AsyncSessionLocal() as db:
        workspace = Workspace(name="Pagination test", slug=f"pagination-{uuid4().hex}")
        other = Workspace(name="Other workspace", slug=f"pagination-{uuid4().hex}")
        db.add_all([workspace, other])
        await db.flush()
        phone = f"+1555{uuid4().int % 10_000_000:07d}"
        contact = Contact(
            workspace_id=workspace.id,
            first_name="Older",
            phone_number=phone,
            phone_hash=hash_phone(phone),
        )
        db.add(contact)
        await db.flush()
        created_at = datetime(2026, 1, 1, tzinfo=UTC)
        id_base = uuid4().int >> 32 << 32
        rows = [
            model(
                id=UUID(int=id_base + index),
                workspace_id=workspace.id,
                number=f"DOC-{index:06d}",
                status="draft",
                contact_id=contact.id if index == 0 else None,
                created_at=created_at,
                updated_at=created_at,
            )
            for index in range(total)
        ]
        db.add_all(rows)
        db.add(model(workspace_id=other.id, number="OTHER", status="draft"))
        await db.flush()
        list_documents = (
            InvoiceService(db).list_invoices if model is Invoice else QuoteService(db).list_quotes
        )
        expected = [row.id for row in reversed(rows)]
        seen: list[UUID] = []
        # The shared API contract keeps an empty list on page 1 of 1.
        pages = max(1, (total + 99) // 100)
        for page in range(1, pages + 1):
            result = await list_documents(workspace.id, page=page, page_size=100)
            assert result.total == total
            assert result.pages == pages
            assert result.page == page
            assert result.page_size == 100
            assert [item.id for item in result.items] == expected[(page - 1) * 100 : page * 100]
            seen.extend(item.id for item in result.items)
        assert seen == expected
        assert len(set(seen)) == total

        if rows:
            # An edit must not sort by updated_at and move an older document.
            rows[0].notes = "Updated older document"
            rows[0].updated_at = created_at + timedelta(days=1)
            await db.flush()
            last = await list_documents(workspace.id, page=pages, page_size=100)
            assert last.items[-1].id == rows[0].id
            assert last.items[-1].notes == "Updated older document"
            filtered = await list_documents(workspace.id, contact_id=contact.id, status="draft")
            assert filtered.total == 1
            assert [item.id for item in filtered.items] == [rows[0].id]
            empty = await list_documents(workspace.id, contact_id=contact.id, status="sent")
            assert empty.total == 0
            assert empty.items == []

            # A newer timestamp wins even when its UUID sorts below all others.
            newer = model(
                id=UUID(int=id_base - 1),
                workspace_id=workspace.id,
                number="NEWER",
                status="draft",
                created_at=created_at + timedelta(days=2),
            )
            db.add(newer)
            await db.flush()
            first = await list_documents(workspace.id, page=1, page_size=100)
            assert first.items[0].id == newer.id
            assert first.total == total + 1
