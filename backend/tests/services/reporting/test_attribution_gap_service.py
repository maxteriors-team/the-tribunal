"""Fast unit coverage for structured lead-source attribution gaps."""

import uuid
from datetime import date
from unittest.mock import AsyncMock, MagicMock

from app.services.reporting import ReportingService


async def test_attribution_gap_counts_and_rate() -> None:
    db = AsyncMock()
    result = MagicMock()
    result.one.return_value = (5, 2)
    db.execute.return_value = result

    report = await ReportingService(db).attribution_gap(
        uuid.uuid4(),
        date_from=date(2026, 7, 1),
        date_to=date(2026, 7, 31),
    )

    assert report.total_contacts == 5
    assert report.unattributed_contacts == 2
    assert report.attributed_contacts == 3
    assert report.gap_rate == 0.4


async def test_attribution_gap_uses_null_rate_for_empty_range() -> None:
    db = AsyncMock()
    result = MagicMock()
    result.one.return_value = (0, 0)
    db.execute.return_value = result

    report = await ReportingService(db).attribution_gap(
        uuid.uuid4(),
        date_from=date(2026, 7, 1),
        date_to=date(2026, 7, 31),
    )

    assert report.total_contacts == 0
    assert report.unattributed_contacts == 0
    assert report.gap_rate is None
