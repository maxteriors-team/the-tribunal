"""Tests for the truthful list-tool result envelope.

The old shape reported ``count: len(page)`` after capping at ``limit``, so
"how many Smiths do I have?" against 300 matches answered "10" with total
confidence. ``total`` now comes from a real COUNT(*) and ``has_more`` says the
answer is truncated.
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy.dialects import postgresql

from app.models.contact import Contact
from app.services.ai.crm_assistant._contact_tools import ContactAssistantTools
from app.services.ai.crm_assistant._pagination import count_matching, listing, local_listing
from app.services.ai.crm_assistant._tool_context import CRMToolContext

_DIALECT = postgresql.dialect()


class TestListingEnvelope:
    def test_reports_page_size_and_true_total_separately(self) -> None:
        payload = listing([{"id": 1}, {"id": 2}], total=300)

        assert payload["returned"] == 2
        assert payload["total"] == 300
        assert payload["has_more"] is True

    def test_complete_result_is_not_flagged_as_truncated(self) -> None:
        payload = listing([{"id": 1}], total=1)

        assert payload["has_more"] is False

    def test_empty_result_is_coherent(self) -> None:
        payload = listing([], total=0)

        assert payload == {
            "success": True,
            "data": [],
            "returned": 0,
            "total": 0,
            "has_more": False,
        }

    def test_extra_keys_are_merged(self) -> None:
        payload = listing([], total=0, extra={"conversation": {"id": "abc"}})

        assert payload["conversation"] == {"id": "abc"}

    def test_local_listing_needs_no_count_query(self) -> None:
        payload = local_listing([{"a": 1}, {"a": 2}])

        assert payload["total"] == 2
        assert payload["has_more"] is False


class TestCountMatching:
    @staticmethod
    def _db(total: Any) -> MagicMock:
        db = MagicMock()
        db.scalar = AsyncMock(return_value=total)
        return db

    async def test_strips_order_and_limit_from_the_count_query(self) -> None:
        db = self._db(42)
        stmt = Contact.__table__.select().order_by(Contact.created_at.desc()).limit(10).offset(5)

        total = await count_matching(db, Contact, stmt)

        assert total == 42
        sql = str(db.scalar.await_args.args[0].compile(dialect=_DIALECT))
        assert "count(*)" in sql.lower()
        assert "ORDER BY" not in sql
        assert "LIMIT" not in sql
        assert "OFFSET" not in sql

    async def test_keeps_the_filter_so_count_matches_the_page(self) -> None:
        db = self._db(3)
        stmt = Contact.__table__.select().where(Contact.status == "qualified")

        await count_matching(db, Contact, stmt)

        sql = str(db.scalar.await_args.args[0].compile(dialect=_DIALECT))
        assert "contacts.status" in sql

    async def test_null_count_becomes_zero(self) -> None:
        assert await count_matching(self._db(None), Contact, Contact.__table__.select()) == 0


class TestSearchContactsReportsTruth:
    async def test_capped_page_still_reports_the_real_total(self) -> None:
        """The exact failure mode: 300 matches, 10 returned, don't answer '10'."""
        contacts = []
        for index in range(10):
            contact = MagicMock(spec=Contact)
            for attribute in (
                "first_name",
                "last_name",
                "phone_number",
                "email",
                "status",
                "company_name",
                "lead_score",
                "engagement_score",
                "is_qualified",
                "qualification_signals",
                "source",
                "last_appointment_status",
            ):
                setattr(contact, attribute, None)
            contact.id = index
            contact.last_engaged_at = None
            contact.created_at = None
            contact.updated_at = None
            contacts.append(contact)

        db = MagicMock()
        execute_result = MagicMock()
        execute_result.scalars.return_value.all.return_value = contacts
        db.execute = AsyncMock(return_value=execute_result)
        db.scalar = AsyncMock(return_value=300)

        tools = ContactAssistantTools(CRMToolContext(db=db, workspace_id=uuid.uuid4(), user_id=1))
        result = await tools.search_contacts({"query": "Smith", "limit": 10})

        assert result["returned"] == 10
        assert result["total"] == 300
        assert result["has_more"] is True
        assert "count" not in result


class TestModelTiers:
    """The tool loop must not run on the cheapest tier.

    A 30-tool agent loop that chains actions is not a "lightweight task"; the
    repo convention reserves the cheapest tier for those. Summarisation is one
    mechanical rewrite with no tools, so it legitimately stays cheap.
    """

    def test_tool_loop_and_summarizer_use_different_tiers(self) -> None:
        from app.services.ai.crm_assistant import _processor, _summarizer

        assert _processor.MODEL != _summarizer.SUMMARY_MODEL

    def test_models_come_from_settings_not_hardcoded(self) -> None:
        from app.core.config import settings
        from app.services.ai.crm_assistant import _processor, _summarizer

        assert settings.openai_assistant_model == _processor.MODEL
        assert settings.openai_assistant_summary_model == _processor.ENHANCE_MODEL
        assert settings.openai_assistant_summary_model == _summarizer.SUMMARY_MODEL

    def test_completion_budget_fits_a_multi_record_answer(self) -> None:
        """800 tokens truncated list answers mid-table."""
        from app.services.ai.crm_assistant import _processor

        assert _processor.MAX_COMPLETION_TOKENS >= 2000
