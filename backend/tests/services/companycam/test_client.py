"""Tests for CompanyCam project↔contact matching."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.services.companycam.client import (
    CompanyCamClient,
    _digits,
    _project_matches_contact,
    find_projects_for_contact,
)


def _project(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "65082566",
        "name": "Megan Zawaidah",
        "created_at": 1717509327,
        "photo_count": 18,
        "project_url": "https://app.companycam.com/projects/65082566",
        "primary_contact": {
            "name": "Megan Zawaidah",
            "phone_number": "+12485088343",
            "email": "drmzawaideh@gmail.com",
        },
    }
    base.update(overrides)
    return base


class TestDigits:
    def test_strips_us_country_code(self) -> None:
        assert _digits("+12485088343") == "2485088343"

    def test_plain_ten_digit(self) -> None:
        assert _digits("(248) 508-8343") == "2485088343"

    def test_none(self) -> None:
        assert _digits(None) == ""


class TestProjectMatchesContact:
    def test_phone_match_wins(self) -> None:
        assert _project_matches_contact(
            _project(name="Something Else"),
            full_name="megan zawaidah",
            phone_digits="2485088343",
            email="",
        )

    def test_email_match(self) -> None:
        assert _project_matches_contact(
            _project(primary_contact={"email": "DRMZawaideh@gmail.com "}),
            full_name="",
            phone_digits="",
            email="drmzawaideh@gmail.com",
        )

    def test_phone_mismatch_blocks_name_fallback(self) -> None:
        # Project has contact info that contradicts — name alone is not enough.
        assert not _project_matches_contact(
            _project(),
            full_name="megan zawaidah",
            phone_digits="9998887777",
            email="other@example.com",
        )

    def test_name_fallback_when_no_contact_info(self) -> None:
        assert _project_matches_contact(
            _project(primary_contact={}),
            full_name="megan zawaidah",
            phone_digits="9998887777",
            email="",
        )

    def test_no_match(self) -> None:
        assert not _project_matches_contact(
            _project(),
            full_name="someone else",
            phone_digits="",
            email="",
        )


async def test_find_projects_dedupes_and_sorts_newest_first() -> None:
    older = _project(id="1", created_at=100)
    newer = _project(id="2", created_at=200)
    client = CompanyCamClient("token")
    # Name search and address search overlap on project 1.
    client.search_projects = AsyncMock(side_effect=[[older, newer], [older]])  # type: ignore[method-assign]

    result = await find_projects_for_contact(
        client,
        first_name="Megan",
        last_name="Zawaidah",
        phone_number="+12485088343",
        email=None,
        address_line1="1334 Pilgrim Ave",
    )

    assert [p["id"] for p in result] == ["2", "1"]
    assert client.search_projects.await_count == 2


async def test_find_projects_skips_blank_queries() -> None:
    client = CompanyCamClient("token")
    client.search_projects = AsyncMock(return_value=[])  # type: ignore[method-assign]

    result = await find_projects_for_contact(
        client,
        first_name="Megan",
        last_name=None,
        phone_number=None,
        email=None,
        address_line1=None,
    )

    assert result == []
    client.search_projects.assert_awaited_once_with("Megan")


async def test_find_projects_caps_results() -> None:
    projects = [
        _project(id=str(i), created_at=i, primary_contact={"phone_number": "+12485088343"})
        for i in range(10)
    ]
    client = CompanyCamClient("token")
    client.search_projects = AsyncMock(side_effect=[projects, []])  # type: ignore[method-assign]

    result = await find_projects_for_contact(
        client,
        first_name="Megan",
        last_name="Zawaidah",
        phone_number="2485088343",
        email=None,
        address_line1="1334 Pilgrim Ave",
    )

    assert len(result) == 5
    assert result[0]["id"] == "9"


@pytest.mark.parametrize(
    ("uris", "expected_thumb"),
    [
        (
            [
                {"type": "thumbnail", "url": "https://t"},
                {"type": "web", "url": "https://w"},
            ],
            "https://t",
        ),
        ([{"type": "web", "url": "https://w"}], "https://w"),
        ([], ""),
    ],
)
def test_photo_urls_picks_best_available(uris: list[dict], expected_thumb: str) -> None:
    from app.api.v1.integrations.companycam import _photo_urls

    thumbnail, _web = _photo_urls({"uris": uris})
    assert thumbnail == expected_thumb
