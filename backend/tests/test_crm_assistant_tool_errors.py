"""Tool failures must be distinguishable, actionable, and leak-free.

Before this, a malformed argument, a database outage and a genuine bug all
returned the identical string ``"Failed to execute <tool>"``. The model could
not tell "fix your arguments and retry" from "stop and tell the operator", so
it either retried blindly or gave up on recoverable mistakes.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.exc import OperationalError

from app.services.ai.crm_assistant._tool_errors import (
    ToolErrorCode,
    conflict,
    internal_error,
    invalid_argument,
    invalid_id,
    missing_argument,
    not_found,
    not_permitted,
    unavailable,
    unknown_tool,
    validation_failed,
)
from app.services.ai.crm_assistant._tool_executor import CRMToolExecutor


class TestErrorShape:
    def test_every_helper_produces_the_same_contract(self) -> None:
        results = [
            invalid_argument("bad"),
            invalid_id("campaign_id", "list first"),
            missing_argument("contact_id"),
            not_found("Campaign"),
            conflict("already running"),
            not_permitted("blocked"),
            unavailable("db down"),
            internal_error("some_tool"),
            unknown_tool("made_up_tool"),
            validation_failed("Offer", "discount_value must be > 0"),
        ]
        for result in results:
            assert result["success"] is False
            assert isinstance(result["code"], str)
            assert isinstance(result["message"], str)
            assert result["message"].endswith(".") or result["message"]
            assert isinstance(result["retryable"], bool)

    def test_codes_are_distinct_per_failure_class(self) -> None:
        assert invalid_argument("x")["code"] == ToolErrorCode.INVALID_ARGUMENT
        assert not_found("Campaign")["code"] == ToolErrorCode.NOT_FOUND
        assert conflict("x")["code"] == ToolErrorCode.CONFLICT
        assert not_permitted("x")["code"] == ToolErrorCode.NOT_PERMITTED
        assert unavailable("x")["code"] == ToolErrorCode.UNAVAILABLE
        assert internal_error("t")["code"] == ToolErrorCode.INTERNAL
        assert unknown_tool("t")["code"] == ToolErrorCode.UNKNOWN_TOOL

    @pytest.mark.parametrize(
        ("result", "expected"),
        [
            (invalid_argument("x"), True),
            (not_found("Campaign"), True),
            (conflict("x"), False),
            (unavailable("x"), False),
            (internal_error("t"), False),
            (not_permitted("x"), False),
        ],
    )
    def test_only_self_correctable_failures_are_retryable(
        self, result: dict[str, object], expected: bool
    ) -> None:
        assert result["retryable"] is expected

    def test_hints_point_at_a_concrete_next_move(self) -> None:
        assert "list_campaigns" in str(not_found("Campaign", "Call list_campaigns.")["hint"])
        assert "search" in str(not_found("Contact")["hint"]).lower()

    def test_validation_detail_is_bounded(self) -> None:
        result = validation_failed("Offer", "x" * 5000)
        assert len(str(result["detail"])) <= 600

    def test_extra_payload_is_preserved(self) -> None:
        result = conflict("dupe", "use update", data={"id": 7})
        assert result["data"] == {"id": 7}


class TestExecutorErrorClassification:
    @staticmethod
    def _executor(db: AsyncMock) -> CRMToolExecutor:
        return CRMToolExecutor(db=db, workspace_id=uuid.uuid4(), user_id=1, role="owner")

    async def test_unknown_tool_is_named_and_not_retryable(self) -> None:
        result = await self._executor(AsyncMock()).execute("teleport_contact", {})

        assert result["code"] == ToolErrorCode.UNKNOWN_TOOL
        assert "teleport_contact" in result["message"]
        assert result["retryable"] is False

    async def test_missing_required_argument_is_marked_retryable(self) -> None:
        db = AsyncMock()
        db.execute.side_effect = KeyError("phone")

        result = await self._executor(db).execute("create_contact", {"first_name": "Bo"})

        assert result["code"] == ToolErrorCode.INVALID_ARGUMENT
        assert result["retryable"] is True
        assert "schema" in str(result["hint"])

    async def test_database_outage_is_distinct_and_not_retryable(self) -> None:
        db = AsyncMock()
        db.scalar.side_effect = OperationalError("SELECT 1", {}, Exception("no route to host"))

        result = await self._executor(db).execute("search_contacts", {"query": "bob"})

        assert result["code"] == ToolErrorCode.UNAVAILABLE
        assert result["retryable"] is False

    async def test_unexpected_bug_is_internal(self) -> None:
        db = AsyncMock()
        db.scalar.side_effect = RuntimeError("boom")

        result = await self._executor(db).execute("search_contacts", {"query": "bob"})

        assert result["code"] == ToolErrorCode.INTERNAL
        assert result["retryable"] is False

    async def test_the_three_failure_classes_are_not_interchangeable(self) -> None:
        """The whole point: these used to be one indistinguishable string."""
        bad_args = AsyncMock()
        bad_args.execute.side_effect = TypeError("nope")
        outage = AsyncMock()
        outage.scalar.side_effect = OperationalError("SELECT 1", {}, Exception("down"))
        bug = AsyncMock()
        bug.scalar.side_effect = RuntimeError("boom")

        codes = {
            (await self._executor(bad_args).execute("create_contact", {}))["code"],
            (await self._executor(outage).execute("search_contacts", {"query": "a"}))["code"],
            (await self._executor(bug).execute("search_contacts", {"query": "a"}))["code"],
        }

        assert len(codes) == 3


class TestNoLeakage:
    async def test_exception_text_never_reaches_the_model(self) -> None:
        secret = "postgres://user:hunter2@10.0.0.5:5432/aicrm"
        db = AsyncMock()
        db.scalar.side_effect = RuntimeError(secret)

        result = await CRMToolExecutor(
            db=db, workspace_id=uuid.uuid4(), user_id=1, role="owner"
        ).execute("search_contacts", {"query": "bob"})

        assert secret not in str(result)
        assert "hunter2" not in str(result)

    async def test_database_error_text_never_reaches_the_model(self) -> None:
        db = AsyncMock()
        db.scalar.side_effect = OperationalError(
            "SELECT * FROM contacts WHERE phone_hash = 'abc'", {}, Exception("fatal")
        )

        result = await CRMToolExecutor(
            db=db, workspace_id=uuid.uuid4(), user_id=1, role="owner"
        ).execute("search_contacts", {"query": "bob"})

        assert "phone_hash" not in str(result)
        assert "SELECT" not in str(result)
