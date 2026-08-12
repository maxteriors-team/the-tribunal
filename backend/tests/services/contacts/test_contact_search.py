"""Contact search has to find people by the name that is printed on the card.

The reported bug: typing "Lisa Shelton" into the command palette returned "No
results found" while both "Lisa" and "Shelton" worked. The search ILIKE'd the
raw query against each column independently, and a full name is a substring of
neither ``first_name`` nor ``last_name``.

Run against real Postgres (``-m integration``) rather than by asserting on
generated SQL: the bug is about which *rows* come back, and a string-compare on
a WHERE clause would have passed just as happily before the fix.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.core.encryption import hash_phone
from app.db.session import AsyncSessionLocal, engine
from app.models.contact import Contact
from app.models.workspace import Workspace
from app.services.contacts.contact_filters import apply_contact_list_filters

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture(autouse=True)
async def _fresh_engine_pool():
    await engine.dispose()
    yield
    await engine.dispose()


async def _workspace(db) -> Workspace:
    ws = Workspace(id=uuid.uuid4(), name="Search", slug=f"se-{uuid.uuid4().hex[:8]}")
    db.add(ws)
    await db.flush()
    return ws


async def _contact(db, workspace_id: uuid.UUID, first: str, last: str, **extra) -> Contact:
    phone = f"+1555{uuid.uuid4().int % 10_000_000:07d}"
    contact = Contact(
        workspace_id=workspace_id,
        first_name=first,
        last_name=last,
        phone_number=phone,
        phone_hash=hash_phone(phone),
        **extra,
    )
    db.add(contact)
    await db.flush()
    return contact


async def _search(db, workspace_id: uuid.UUID, term: str) -> list[str]:
    """Return matching contacts' full names via the real list-filter path."""
    query = apply_contact_list_filters(
        select(Contact).where(Contact.workspace_id == workspace_id),
        search=term,
    )
    rows = (await db.execute(query)).scalars().all()
    return sorted(f"{c.first_name} {c.last_name}" for c in rows)


class TestFullNameSearch:
    async def test_full_name_finds_the_contact(self) -> None:
        """The exact reported failure: first + last together returned nothing."""
        async with AsyncSessionLocal() as db:
            ws = await _workspace(db)
            await _contact(db, ws.id, "Lisa", "Shelton")
            await _contact(db, ws.id, "Michael", "Mardeusz")

            assert await _search(db, ws.id, "Lisa Shelton") == ["Lisa Shelton"]
            await db.rollback()

    async def test_single_names_still_work(self) -> None:
        async with AsyncSessionLocal() as db:
            ws = await _workspace(db)
            await _contact(db, ws.id, "Lisa", "Shelton")

            assert await _search(db, ws.id, "Lisa") == ["Lisa Shelton"]
            assert await _search(db, ws.id, "Shelton") == ["Lisa Shelton"]
            await db.rollback()

    async def test_word_order_does_not_matter(self) -> None:
        """Tokens are ANDed across columns, so "last first" matches too."""
        async with AsyncSessionLocal() as db:
            ws = await _workspace(db)
            await _contact(db, ws.id, "Lisa", "Shelton")

            assert await _search(db, ws.id, "Shelton Lisa") == ["Lisa Shelton"]
            await db.rollback()

    async def test_case_and_extra_whitespace_are_ignored(self) -> None:
        async with AsyncSessionLocal() as db:
            ws = await _workspace(db)
            await _contact(db, ws.id, "Lisa", "Shelton")

            assert await _search(db, ws.id, "  lisa   SHELTON ") == ["Lisa Shelton"]
            await db.rollback()

    async def test_partial_words_match(self) -> None:
        """Typing ahead ("Li Shel") should still narrow to the right person."""
        async with AsyncSessionLocal() as db:
            ws = await _workspace(db)
            await _contact(db, ws.id, "Lisa", "Shelton")

            assert await _search(db, ws.id, "Li Shel") == ["Lisa Shelton"]
            await db.rollback()

    async def test_every_token_must_match(self) -> None:
        """A wrong surname must not match on the first name alone."""
        async with AsyncSessionLocal() as db:
            ws = await _workspace(db)
            await _contact(db, ws.id, "Lisa", "Shelton")
            await _contact(db, ws.id, "Lisa", "Nguyen")

            assert await _search(db, ws.id, "Lisa Shelton") == ["Lisa Shelton"]
            assert await _search(db, ws.id, "Lisa Bogus") == []
            await db.rollback()

    async def test_namesakes_both_return(self) -> None:
        async with AsyncSessionLocal() as db:
            ws = await _workspace(db)
            await _contact(db, ws.id, "Lisa", "Shelton")
            await _contact(db, ws.id, "Lisa", "Shelton")

            assert await _search(db, ws.id, "Lisa Shelton") == ["Lisa Shelton", "Lisa Shelton"]
            await db.rollback()

    async def test_search_stays_inside_the_workspace(self) -> None:
        """Multi-tenant safety: a matching name in another workspace is invisible."""
        async with AsyncSessionLocal() as db:
            mine = await _workspace(db)
            theirs = await _workspace(db)
            await _contact(db, theirs.id, "Lisa", "Shelton")

            assert await _search(db, mine.id, "Lisa Shelton") == []
            await db.rollback()


class TestMultiWordValuesStillMatch:
    async def test_company_name_containing_spaces(self) -> None:
        """The whole-string match is kept, so multi-word column values survive."""
        async with AsyncSessionLocal() as db:
            ws = await _workspace(db)
            await _contact(db, ws.id, "Dana", "Reyes", company_name="Acme Roofing Co")

            assert await _search(db, ws.id, "Acme Roofing") == ["Dana Reyes"]
            await db.rollback()

    async def test_name_spanning_first_and_company(self) -> None:
        """Tokens may be satisfied by different columns."""
        async with AsyncSessionLocal() as db:
            ws = await _workspace(db)
            await _contact(db, ws.id, "Dana", "Reyes", company_name="Acme Roofing Co")

            assert await _search(db, ws.id, "Dana Acme") == ["Dana Reyes"]
            await db.rollback()
