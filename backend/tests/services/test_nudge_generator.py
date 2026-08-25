"""Tests for the NudgeGeneratorService.

Unit tests with mocked AsyncSession — no real DB required.

Proof-of-concept for the factory_boy fixtures defined in
``tests/factories.py`` + ``tests/conftest.py``. Previously this file used
hand-rolled ``_make_workspace`` / ``_make_contact`` ``MagicMock`` helpers.
Those are now real ``Workspace`` / ``Contact`` instances produced by
``workspace_factory`` / ``contact_factory``, which means:

- Tests fail loudly if the model schema drifts (missing columns / wrong types)
  instead of silently passing on a misshapen mock.
- The setup reads as "build this entity with these overrides" rather than
  ad-hoc attribute assignment.

See ``CONTRIBUTING.md`` for the broader factory pattern.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.contact import Contact
from app.models.workspace import Workspace
from app.services.nudges.nudge_generator import NudgeGeneratorService
from tests.factories import ContactFactory, WorkspaceFactory


@pytest.fixture
def generator() -> NudgeGeneratorService:
    return NudgeGeneratorService()


@pytest.fixture
def mock_db() -> AsyncMock:
    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    return db


def _workspace_with_nudge_settings(
    workspace_factory: type[WorkspaceFactory],
    nudge_settings: dict[str, Any] | None = None,
) -> Workspace:
    """Build a Workspace with ``settings.nudge_settings`` pre-populated."""
    return workspace_factory.build(
        settings={"nudge_settings": nudge_settings or {"enabled": True, "lead_days": 3}},
    )


def _contact_named_alice(
    contact_factory: type[ContactFactory],
    important_dates: dict[str, Any] | None = None,
    contact_id: int = 1,
) -> Contact:
    """Build a Contact named 'Alice Smith' for stable assertion strings."""
    return contact_factory.build(
        id=contact_id,
        first_name="Alice",
        last_name="Smith",
        important_dates=important_dates,
    )


def _scalar_result(value: Any) -> MagicMock:
    """Create a mock execute result whose .scalars().all() returns a list."""
    result = MagicMock()
    result.scalars.return_value.all.return_value = value
    return result


def _scalar_one_result(value: Any) -> MagicMock:
    """Create a mock execute result whose .scalar_one_or_none() returns value."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _rows_result(value: Any) -> MagicMock:
    """Create a mock execute result whose .all() returns rows."""
    result = MagicMock()
    result.all.return_value = value
    return result


class TestGenerateBirthdayNudge:
    async def test_generate_birthday_nudge(
        self,
        generator: NudgeGeneratorService,
        mock_db: AsyncMock,
        contact_factory: type[ContactFactory],
        workspace_factory: type[WorkspaceFactory],
    ) -> None:
        """Contact with birthday in 2 days → creates a birthday nudge."""
        today = datetime.now(UTC).date()
        bday = today + timedelta(days=2)
        bday_str = bday.strftime("%Y-%m-%d")

        contact = _contact_named_alice(contact_factory, {"birthday": bday_str})
        workspace = _workspace_with_nudge_settings(
            workspace_factory,
            {"enabled": True, "lead_days": 3, "nudge_types": ["birthday"]},
        )

        # 1st execute: fetch contacts with important_dates
        # 2nd execute: dedup check → no existing nudge
        mock_db.execute = AsyncMock(
            side_effect=[
                _scalar_result([contact]),  # contacts query
                _scalar_one_result(99),  # workspace owner
                _rows_result([]),  # open opportunity owners
                _scalar_one_result(None),  # dedup check → not found
            ]
        )

        count = await generator.generate_for_workspace(mock_db, workspace)

        assert count == 1
        mock_db.add.assert_called_once()
        nudge_arg = mock_db.add.call_args[0][0]
        assert nudge_arg.nudge_type == "birthday"
        assert nudge_arg.contact_id == contact.id
        assert nudge_arg.assigned_to_user_id == 99
        mock_db.commit.assert_awaited_once()


class TestGenerateAnniversaryNudge:
    async def test_generate_anniversary_nudge(
        self,
        generator: NudgeGeneratorService,
        mock_db: AsyncMock,
        contact_factory: type[ContactFactory],
        workspace_factory: type[WorkspaceFactory],
    ) -> None:
        """Contact with anniversary in 1 day → creates an anniversary nudge."""
        today = datetime.now(UTC).date()
        ann = today + timedelta(days=1)
        ann_str = ann.strftime("%Y-%m-%d")

        contact = _contact_named_alice(contact_factory, {"anniversary": ann_str})
        workspace = _workspace_with_nudge_settings(
            workspace_factory,
            {"enabled": True, "lead_days": 3, "nudge_types": ["anniversary"]},
        )

        mock_db.execute = AsyncMock(
            side_effect=[
                _scalar_result([contact]),
                _scalar_one_result(99),
                _rows_result([]),
                _scalar_one_result(None),
            ]
        )

        count = await generator.generate_for_workspace(mock_db, workspace)

        assert count == 1
        nudge_arg = mock_db.add.call_args[0][0]
        assert nudge_arg.nudge_type == "anniversary"


class TestGenerateCustomDateNudge:
    async def test_generate_custom_date_nudge(
        self,
        generator: NudgeGeneratorService,
        mock_db: AsyncMock,
        contact_factory: type[ContactFactory],
        workspace_factory: type[WorkspaceFactory],
    ) -> None:
        """Contact with custom date in window → creates a custom nudge."""
        today = datetime.now(UTC).date()
        custom_date = today + timedelta(days=2)

        contact = _contact_named_alice(
            contact_factory,
            {"custom": [{"label": "Policy Renewal", "date": custom_date.strftime("%Y-%m-%d")}]},
        )
        workspace = _workspace_with_nudge_settings(
            workspace_factory,
            {"enabled": True, "lead_days": 3, "nudge_types": ["custom"]},
        )

        mock_db.execute = AsyncMock(
            side_effect=[
                _scalar_result([contact]),
                _scalar_one_result(99),
                _rows_result([]),
                _scalar_one_result(None),
            ]
        )

        count = await generator.generate_for_workspace(mock_db, workspace)

        assert count == 1
        nudge_arg = mock_db.add.call_args[0][0]
        assert nudge_arg.nudge_type == "custom"
        assert "Policy Renewal" in nudge_arg.title


class TestNoNudgeOutsideWindow:
    async def test_no_nudge_outside_window(
        self,
        generator: NudgeGeneratorService,
        mock_db: AsyncMock,
        contact_factory: type[ContactFactory],
        workspace_factory: type[WorkspaceFactory],
    ) -> None:
        """Birthday in 10 days with lead_days=3 → no nudge created."""
        today = datetime.now(UTC).date()
        bday = today + timedelta(days=10)

        contact = _contact_named_alice(
            contact_factory,
            {"birthday": bday.strftime("%Y-%m-%d")},
        )
        workspace = _workspace_with_nudge_settings(
            workspace_factory,
            {"enabled": True, "lead_days": 3, "nudge_types": ["birthday"]},
        )

        mock_db.execute = AsyncMock(
            side_effect=[
                _scalar_result([contact]),
                _scalar_one_result(99),
                _rows_result([]),
            ]
        )

        count = await generator.generate_for_workspace(mock_db, workspace)

        assert count == 0
        mock_db.add.assert_not_called()


class TestDedupPreventsDuplicate:
    async def test_dedup_prevents_duplicate(
        self,
        generator: NudgeGeneratorService,
        mock_db: AsyncMock,
        contact_factory: type[ContactFactory],
        workspace_factory: type[WorkspaceFactory],
    ) -> None:
        """Existing dedup key → no new nudge created."""
        today = datetime.now(UTC).date()
        bday = today + timedelta(days=2)

        contact = _contact_named_alice(
            contact_factory,
            {"birthday": bday.strftime("%Y-%m-%d")},
        )
        workspace = _workspace_with_nudge_settings(
            workspace_factory,
            {"enabled": True, "lead_days": 3, "nudge_types": ["birthday"]},
        )

        mock_db.execute = AsyncMock(
            side_effect=[
                _scalar_result([contact]),
                _scalar_one_result(99),
                _rows_result([]),
                _scalar_one_result(uuid.uuid4()),  # dedup check → exists
            ]
        )

        count = await generator.generate_for_workspace(mock_db, workspace)

        assert count == 0
        mock_db.add.assert_not_called()


class TestCoolingNudge:
    async def test_cooling_nudge(
        self,
        generator: NudgeGeneratorService,
        mock_db: AsyncMock,
        contact_factory: type[ContactFactory],
        workspace_factory: type[WorkspaceFactory],
    ) -> None:
        """Old conversation → generates a cooling nudge."""
        now = datetime.now(UTC)
        old_msg_time = now - timedelta(days=45)

        conv = MagicMock()
        conv.contact_id = 42
        conv.last_message_at = old_msg_time

        contact = _contact_named_alice(contact_factory, contact_id=42)

        workspace = _workspace_with_nudge_settings(
            workspace_factory,
            {"enabled": True, "lead_days": 3, "cooling_days": 30},
        )

        # The orchestrator runs ALL enabled strategies in registry order.
        # Date strategies skip because date_contacts=[].
        # Cooling strategy gets specific results; all subsequent strategies
        # receive empty results via the generator fallback.
        empty = _scalar_result([])
        specific_results = [
            _scalar_result([]),  # 1. contacts (no important_dates)
            _scalar_one_result(99),  # 2. workspace owner
            _rows_result([(42, 77)]),  # 3. latest open opportunity owner
            _scalar_result([conv]),  # 4. cooling: cold conversations
            _scalar_one_result(None),  # 5. cooling: dedup → not found
            _scalar_one_result(contact),  # 6. cooling: load contact
        ]
        call_count = 0

        async def _execute_side_effect(*args: Any, **kwargs: Any) -> MagicMock:
            nonlocal call_count
            idx = call_count
            call_count += 1
            return specific_results[idx] if idx < len(specific_results) else empty

        mock_db.execute = AsyncMock(side_effect=_execute_side_effect)

        count = await generator.generate_for_workspace(mock_db, workspace)

        assert count == 1
        nudge_arg = mock_db.add.call_args[0][0]
        assert nudge_arg.nudge_type == "cooling"
        assert nudge_arg.contact_id == 42
        assert nudge_arg.assigned_to_user_id == 77


class TestNudgeMessageContent:
    def test_birthday_message_content(
        self,
        generator: NudgeGeneratorService,
        contact_factory: type[ContactFactory],
    ) -> None:
        """_build_nudge_message returns title/message with contact name for birthday."""
        contact = _contact_named_alice(contact_factory)
        title, message, action = generator._build_nudge_message(
            contact, "birthday", date_str="April 15", days_until=3
        )

        assert "Alice Smith" in title
        assert "birthday" in title.lower() or "🎂" in title
        assert "Alice Smith" in message
        assert "3 days" in message
        assert action == "send_card"

    def test_cooling_message_content(
        self,
        generator: NudgeGeneratorService,
        contact_factory: type[ContactFactory],
    ) -> None:
        """_build_nudge_message returns re-engage title for cooling."""
        contact = _contact_named_alice(contact_factory)
        title, message, action = generator._build_nudge_message(contact, "cooling", days_until=35)

        assert "Alice Smith" in title
        assert "35 days" in message
        assert action == "call"

    def test_custom_date_message_content(
        self,
        generator: NudgeGeneratorService,
        contact_factory: type[ContactFactory],
    ) -> None:
        """_build_nudge_message uses custom label."""
        contact = _contact_named_alice(contact_factory)
        title, message, action = generator._build_nudge_message(
            contact, "custom", date_str="May 01", days_until=5, label="Lease Renewal"
        )

        assert "Lease Renewal" in title
        assert "Alice Smith" in message


class TestRespectsNudgeTypesSetting:
    async def test_only_cooling_enabled_skips_date_nudges(
        self,
        generator: NudgeGeneratorService,
        mock_db: AsyncMock,
        contact_factory: type[ContactFactory],
        workspace_factory: type[WorkspaceFactory],
    ) -> None:
        """Only cooling in nudge_types → date nudges skipped entirely."""
        today = datetime.now(UTC).date()
        bday = today + timedelta(days=1)
        contact = _contact_named_alice(
            contact_factory,
            {"birthday": bday.strftime("%Y-%m-%d")},
        )

        workspace = _workspace_with_nudge_settings(
            workspace_factory,
            {
                "enabled": True,
                "lead_days": 3,
                "nudge_types": ["cooling"],
                "cooling_days": 30,
            },
        )

        # 1st: contacts query (still runs), 2nd: cold conversations (none)
        mock_db.execute = AsyncMock(
            side_effect=[
                _scalar_result([contact]),  # contacts query
                _scalar_one_result(99),  # workspace owner
                _rows_result([]),  # open opportunity owners
                _scalar_result([]),  # cold conversations → none
            ]
        )

        count = await generator.generate_for_workspace(mock_db, workspace)

        assert count == 0
        mock_db.add.assert_not_called()


class TestNoNudgesWhenDisabled:
    async def test_no_nudges_when_disabled(
        self,
        generator: NudgeGeneratorService,
        mock_db: AsyncMock,
        workspace_factory: type[WorkspaceFactory],
    ) -> None:
        """Nudge settings disabled → returns 0 immediately."""
        workspace = _workspace_with_nudge_settings(workspace_factory, {"enabled": False})

        count = await generator.generate_for_workspace(mock_db, workspace)

        assert count == 0
        mock_db.execute.assert_not_called()
        mock_db.add.assert_not_called()
