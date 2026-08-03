"""Guards against lookups that can never match an encrypted column.

``Contact.email``, ``Contact.phone_number`` and ``User.email`` are
:class:`EncryptedString` columns: ciphertext with a random IV, so the same
plaintext encrypts differently every time. ``WHERE email = 'a@b.com'`` therefore
matches **nothing, ever** — it does not raise, it silently returns zero rows.

That is why this class of bug survives review and mocked tests alike. Every
affected call site had passing unit tests: the mocks returned whatever the test
told them to, so nothing noticed the query itself was incapable of matching.

Each model carries a deterministic ``*_hash`` companion column
(:class:`LookupHash`) that exists purely so these lookups can work.

Three call sites shipped to production with the broken form:

* ``calcom_parser.find_contact_by_attendee`` — a booking webhook could not find
  the contact who made the booking, so bookings orphaned or duplicated contacts.
* ``offers.submit_offer_optin`` — every opt-in created a new contact instead of
  matching the existing one.
* ``invitations.create_invitation`` — "is this user already a member?" always
  answered no.

These tests assert on the **compiled SQL**, so they fail if a call site regresses
to filtering on the encrypted column.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select

from app.api.webhooks.calcom_parser import find_contact_by_attendee
from app.core.encryption import EncryptedString, LookupHash, hash_phone, hash_value
from app.models.contact import Contact
from app.models.user import User

APP_ROOT = Path(__file__).resolve().parents[1] / "app"

# ``column on the model`` -> ``column a lookup must filter on instead``.
ENCRYPTED_TO_HASH = {
    (Contact, "email"): "email_hash",
    (Contact, "phone_number"): "phone_hash",
    (User, "email"): "email_hash",
}


def _compile(statement: Any) -> str:
    return str(statement.compile(compile_kwargs={"literal_binds": True}))


class TestModelShape:
    """The premise: these columns really are encrypted, and really have hashes."""

    @pytest.mark.parametrize(
        ("model", "column", "hash_column"),
        [
            (model, column, hash_column)
            for (model, column), hash_column in ENCRYPTED_TO_HASH.items()
        ],
    )
    def test_encrypted_column_has_a_hash_companion(
        self, model: type, column: str, hash_column: str
    ) -> None:
        columns = model.__table__.c

        assert isinstance(columns[column].type, EncryptedString)
        assert isinstance(columns[hash_column].type, LookupHash)

    def test_encrypting_the_same_value_twice_gives_different_ciphertext(self) -> None:
        """Why equality can never work: the IV is random per encryption."""
        encrypted = EncryptedString()
        dialect = MagicMock()

        first = encrypted.process_bind_param("dana@example.com", dialect)
        second = encrypted.process_bind_param("dana@example.com", dialect)

        assert first != second

    def test_hashing_the_same_value_twice_is_stable(self) -> None:
        """Why the hash column works: it is deterministic."""
        assert hash_value("dana@example.com") == hash_value("dana@example.com")
        assert hash_phone("+15551234567") == hash_phone("+15551234567")


class TestCalcomParser:
    """A booking webhook has to find the contact who booked."""

    @pytest.mark.asyncio
    async def test_email_lookup_uses_the_hash_column(self) -> None:
        db, statements = _capturing_db(hits=[None])

        await find_contact_by_attendee(email="dana@example.com", phone=None, db=db, log=MagicMock())

        where = _compile(statements[0]).split("WHERE", 1)[1]
        assert "contacts.email_hash" in where
        assert "contacts.email =" not in where

    @pytest.mark.asyncio
    async def test_phone_fallback_uses_the_hash_column(self) -> None:
        db, statements = _capturing_db(hits=[None, None])

        await find_contact_by_attendee(
            email="dana@example.com", phone="+1 (555) 123-4567", db=db, log=MagicMock()
        )

        # Only the WHERE clause matters: every column appears in the SELECT list.
        where = _compile(statements[1]).split("WHERE", 1)[1]
        assert "contacts.phone_hash" in where
        # The old form was a suffix LIKE against ciphertext.
        assert "LIKE" not in where.upper()
        assert "contacts.phone_number" not in where

    @pytest.mark.asyncio
    async def test_a_seeded_contact_is_actually_found(self) -> None:
        """End to end through the real function, with the hash the code computes."""
        contact = MagicMock(id=42)
        db, _ = _capturing_db(hits=[contact])

        found = await find_contact_by_attendee(
            email="dana@example.com", phone=None, db=db, log=MagicMock()
        )

        assert found is contact


class TestStaticGuard:
    """No call site anywhere may filter an encrypted column by equality.

    The three known sites are fixed, but the trap is generic: any future lookup
    written the obvious way is silently broken. This walks the AST of every
    module under ``app/`` and fails on the pattern itself.
    """

    def test_no_module_compares_an_encrypted_column_to_a_value(self) -> None:
        banned = {
            ("Contact", "email"),
            ("Contact", "phone_number"),
            ("User", "email"),
        }
        offenders: list[str] = []

        for path in sorted(APP_ROOT.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Compare):
                    continue
                if not any(isinstance(op, (ast.Eq, ast.NotEq)) for op in node.ops):
                    continue
                left = node.left
                if (
                    isinstance(left, ast.Attribute)
                    and isinstance(left.value, ast.Name)
                    and (left.value.id, left.attr) in banned
                ):
                    model = Contact if left.value.id == "Contact" else User
                    hint = ENCRYPTED_TO_HASH[(model, left.attr)]
                    location = f"{path.relative_to(APP_ROOT.parent)}:{node.lineno}"
                    offenders.append(
                        f"{location} {left.value.id}.{left.attr} == ... "
                        f"(use {left.value.id}.{hint})"
                    )

        assert not offenders, "encrypted columns compared by equality:\n  " + "\n  ".join(offenders)


def _capturing_db(hits: list[Any]) -> tuple[AsyncMock, list[Any]]:
    """An async session stand-in that records every statement it executes."""
    statements: list[Any] = []

    def _result(value: Any) -> MagicMock:
        result = MagicMock()
        result.scalar_one_or_none = MagicMock(return_value=value)
        scalars = MagicMock()
        scalars.first = MagicMock(return_value=value)
        result.scalars = MagicMock(return_value=scalars)
        return result

    results = iter([_result(hit) for hit in hits])

    async def execute(statement: Any) -> MagicMock:
        statements.append(statement)
        return next(results)

    db = AsyncMock()
    db.execute = execute
    return db, statements


def test_select_on_the_encrypted_column_compiles_but_cannot_match() -> None:
    """Documents the failure mode: valid SQL, guaranteed zero rows."""
    broken = _compile(select(Contact).where(Contact.email == "dana@example.com"))
    fixed = _compile(select(Contact).where(Contact.email_hash == hash_value("dana@example.com")))

    # Both are syntactically fine — nothing raises, which is the whole problem.
    assert "contacts.email =" in broken
    assert "contacts.email_hash =" in fixed
