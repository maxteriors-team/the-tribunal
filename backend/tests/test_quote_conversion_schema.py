"""Validation for the two-phase quote conversion contract."""

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.schemas.quote import QuoteConvertRequest

START = datetime(2026, 11, 15, 14, tzinfo=UTC)
END = START + timedelta(hours=2)
TAKEDOWN_START = datetime(2027, 1, 8, 14, tzinfo=UTC)


def _request(**overrides: object) -> dict[str, object]:
    return {
        "scheduled_start": START,
        "scheduled_end": END,
        "takedown_schedule": {
            "scheduled_start": TAKEDOWN_START,
            "scheduled_end": TAKEDOWN_START + timedelta(hours=2),
        },
        **overrides,
    }


def test_accepts_independent_installation_and_takedown_windows() -> None:
    request = QuoteConvertRequest.model_validate(_request())

    assert request.scheduled_start == START
    assert request.takedown_schedule is not None
    assert request.takedown_schedule.scheduled_start == TAKEDOWN_START


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        (
            {
                "takedown_schedule": {
                    "scheduled_start": END,
                    "scheduled_end": END + timedelta(hours=2),
                }
            },
            "after installation",
        ),
        ({"scheduled_start": None, "scheduled_end": None}, "installation schedule"),
        ({"create_job": False}, "require create_job"),
    ],
)
def test_rejects_ambiguous_or_disabled_takedown_schedule(
    overrides: dict[str, object], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        QuoteConvertRequest.model_validate(_request(**overrides))
