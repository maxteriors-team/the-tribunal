"""Regression tests for the encrypted-column contact lookup bugs.

Bug A: ``search_contacts`` advertised phone/email search but ILIKEd the
Fernet-encrypted ``phone_number``/``email`` columns. Fernet is
non-deterministic, so the *pattern* was encrypted before it reached Postgres
and the predicate could never match — a real customer looked like a stranger.

Bug B: ``create_contact``'s duplicate guard compared the same encrypted column
for equality, so it never fired and silently created duplicates.

Both are proven here by compiling the real predicate and running the actual
SQLAlchemy bind processors, the same way the bugs were originally diagnosed.
"""

from __future__ import annotations

import re
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import BinaryExpression, ColumnElement
from sqlalchemy.dialects import postgresql

from app.core.encryption import hash_phone, hash_value
from app.models.contact import Contact
from app.services.ai.crm_assistant._contact_tools import (
    ContactAssistantTools,
    contact_search_predicate,
    email_hash_candidate,
    phone_hash_candidates,
)
from app.services.ai.crm_assistant._tool_context import CRMToolContext

_DIALECT = postgresql.dialect()


def _bound_literals(predicate: ColumnElement[bool]) -> list[Any]:
    """Return the parameter values as Postgres would actually receive them.

    Compiling alone is not enough: ``EncryptedString.process_bind_param`` runs
    at execution time, which is exactly where the encryption happened.
    """
    compiled = predicate.compile(dialect=_DIALECT)
    processors = compiled._bind_processors  # noqa: SLF001 — mirrors SQLAlchemy execution
    values: list[Any] = []
    for key, value in compiled.params.items():
        processor = processors.get(key)
        # IN(...) compiles to a single expanding parameter holding a list.
        items = value if isinstance(value, list) else [value]
        values.extend(processor(item) if processor else item for item in items)
    return values


class TestPhoneHashCandidates:
    def test_e164_query_hashes_to_the_stored_value(self) -> None:
        assert hash_phone("+15554829910") in phone_hash_candidates("+15554829910")

    @pytest.mark.parametrize(
        "typed",
        ["(555) 482-9910", "555-482-9910", "555.482.9910", "5554829910", "+1 555 482 9910"],
    )
    def test_operator_formats_all_reach_the_stored_e164_hash(self, typed: str) -> None:
        """The operator types any format; the row was stored as E.164."""
        assert hash_phone("+15554829910") in phone_hash_candidates(typed)

    def test_short_digit_runs_are_not_treated_as_phone_numbers(self) -> None:
        assert phone_hash_candidates("Suite 400") == []
        assert phone_hash_candidates("bob") == []

    def test_unparseable_long_digit_string_still_yields_a_candidate(self) -> None:
        assert phone_hash_candidates("00000000000") != []


class TestEmailHashCandidate:
    def test_email_query_hashes(self) -> None:
        assert email_hash_candidate("Jenna.Wills@gmail.com") == hash_value("Jenna.Wills@gmail.com")

    def test_hash_is_case_insensitive(self) -> None:
        assert email_hash_candidate("BOB@example.com") == email_hash_candidate("bob@example.com")

    def test_non_email_queries_are_ignored(self) -> None:
        assert email_hash_candidate("bob marchetti") is None
        assert email_hash_candidate("acme corp") is None

    def test_email_with_whitespace_is_not_treated_as_an_address(self) -> None:
        assert email_hash_candidate("bob @ example.com") is None


class TestSearchPredicate:
    def test_empty_query_means_no_filter(self) -> None:
        assert contact_search_predicate("") is None
        assert contact_search_predicate("   ") is None

    def test_name_query_still_uses_plain_ilike(self) -> None:
        predicate = contact_search_predicate("Bob")
        assert predicate is not None
        assert "%Bob%" in _bound_literals(predicate)

    def test_phone_query_never_sends_an_encrypted_pattern(self) -> None:
        """The original bug, asserted directly."""
        predicate = contact_search_predicate("+15554829910")
        assert predicate is not None
        literals = [value for value in _bound_literals(predicate) if isinstance(value, str)]

        assert not any(value.startswith("gAAAAA") for value in literals), (
            "a Fernet ciphertext reached the query — the encrypted column is being matched again"
        )
        assert hash_phone("+15554829910") in literals

    def test_phone_query_targets_the_indexed_hash_column(self) -> None:
        predicate = contact_search_predicate("+15554829910")
        assert predicate is not None
        sql = str(predicate.compile(dialect=_DIALECT))
        assert "contacts.phone_hash" in sql
        assert "contacts.phone_number" not in sql

    def test_email_query_targets_the_indexed_hash_column(self) -> None:
        predicate = contact_search_predicate("jenna.wills@gmail.com")
        assert predicate is not None
        sql = str(predicate.compile(dialect=_DIALECT))
        assert "contacts.email_hash" in sql
        assert re.search(r"contacts\.email\b(?!_hash)", sql) is None
        assert hash_value("jenna.wills@gmail.com") in _bound_literals(predicate)

    def test_name_query_does_not_add_contact_detail_clauses(self) -> None:
        sql = str(contact_search_predicate("Marchetti").compile(dialect=_DIALECT))  # type: ignore[union-attr]
        assert "phone_hash" not in sql
        assert "email_hash" not in sql

    def test_name_company_clauses_are_always_present(self) -> None:
        sql = str(contact_search_predicate("+15554829910").compile(dialect=_DIALECT))  # type: ignore[union-attr]
        assert "first_name" in sql
        assert "last_name" in sql
        assert "company_name" in sql


class TestCreateContactDuplicateGuard:
    """Bug B: the guard compared an encrypted column and never fired."""

    @staticmethod
    def _tools(existing: Contact | None) -> tuple[ContactAssistantTools, MagicMock]:
        db = MagicMock()
        db.add = MagicMock()
        db.flush = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none = MagicMock(return_value=existing)
        db.execute = AsyncMock(return_value=result)
        context = CRMToolContext(db=db, workspace_id=uuid.uuid4(), user_id=1, role="owner")
        return ContactAssistantTools(context), db

    async def test_guard_queries_the_hash_column_not_the_encrypted_one(self) -> None:
        tools, db = self._tools(existing=None)

        await tools.create_contact({"first_name": "Maria", "phone": "+15558675309"})

        where = str(db.execute.await_args.args[0].whereclause.compile(dialect=_DIALECT))
        assert "contacts.phone_hash" in where
        assert "contacts.phone_number" not in where

    async def test_duplicate_is_detected_across_phone_formats(self) -> None:
        stored = MagicMock(spec=Contact)
        stored.id = 4821
        stored.first_name = "Maria"
        stored.last_name = "Delgado"
        stored.phone_number = "+15558675309"
        tools, db = self._tools(existing=stored)

        result = await tools.create_contact({"first_name": "Maria", "phone": "(555) 867-5309"})

        assert result["success"] is False
        db.add.assert_not_called()
        compiled = db.execute.await_args.args[0].compile(dialect=_DIALECT)
        candidates = next(value for value in compiled.params.values() if isinstance(value, list))
        assert hash_phone("+15558675309") in candidates

    async def test_duplicate_returns_the_existing_contact_id(self) -> None:
        stored = MagicMock(spec=Contact)
        stored.id = 4821
        stored.first_name = "Maria"
        stored.last_name = "Delgado"
        stored.phone_number = "+15558675309"
        tools, _ = self._tools(existing=stored)

        result = await tools.create_contact({"first_name": "Maria", "phone": "+15558675309"})

        assert result["success"] is False
        assert result["data"] == {
            "id": 4821,
            "first_name": "Maria",
            "last_name": "Delgado",
            "phone": "+15558675309",
        }
        assert "update_contact" in str(result["hint"])

    async def test_new_phone_still_creates_the_contact(self) -> None:
        tools, db = self._tools(existing=None)

        result = await tools.create_contact(
            {"first_name": "Maria", "phone": "+15558675309", "email": "m@example.com"}
        )

        assert result["success"] is True
        db.add.assert_called_once()
        db.flush.assert_awaited_once()


class TestEncryptedColumnBaseline:
    """Documents *why* the fix is shaped this way."""

    def test_encrypting_the_same_value_twice_differs(self) -> None:
        column_type = Contact.__table__.c.phone_number.type
        processor = column_type.bind_processor(_DIALECT)
        assert processor is not None
        assert processor("+15554829910") != processor("+15554829910")

    def test_ilike_on_the_encrypted_column_destroys_the_pattern(self) -> None:
        predicate: BinaryExpression[bool] = Contact.phone_number.ilike("%5554829910%")
        literals = _bound_literals(predicate)
        assert not any("5554829910" in str(value) for value in literals)

    def test_hash_lookup_is_deterministic(self) -> None:
        assert hash_phone("+15554829910") == hash_phone("+1 (555) 482-9910")
