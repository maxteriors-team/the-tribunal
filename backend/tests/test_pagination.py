"""Tests for shared pagination response builders."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.db.pagination import PaginationResult, list_response


class _Item(BaseModel):
    """Tiny response model for pagination tests."""

    model_config = ConfigDict(from_attributes=True)

    value: int


class _OrmItem:
    def __init__(self, value: int) -> None:
        self.value = value


class _Page(BaseModel):
    """Tiny paginated response model for builder tests."""

    items: list[_Item]
    total: int
    page: int
    page_size: int
    pages: int


def test_to_dict_materializes_shared_metadata_shape() -> None:
    result = PaginationResult(items=[1, 2], total=5, page=2, page_size=2, pages=3)

    assert result.to_dict() == {
        "items": [1, 2],
        "total": 5,
        "page": 2,
        "page_size": 2,
        "pages": 3,
    }


def test_build_response_validates_items_and_constructs_page_model() -> None:
    result = PaginationResult(items=[_OrmItem(7)], total=1, page=1, page_size=50, pages=1)

    response = result.build_response(item_model=_Item, response_builder=_Page)

    assert isinstance(response, _Page)
    assert response.items == [_Item(value=7)]
    assert response.total == 1


def test_build_response_accepts_item_mapper_for_joined_rows() -> None:
    result = PaginationResult(items=[("a", 2)], total=1, page=1, page_size=10, pages=1)

    payload = result.build_response(item_mapper=lambda row: {"name": row[0], "count": row[1]})

    assert payload["items"] == [{"name": "a", "count": 2}]
    assert payload["pages"] == 1


def test_list_response_returns_non_paginated_shape() -> None:
    assert list_response(["a", "b"]) == {"items": ["a", "b"], "total": 2}
    assert list_response(["a"], total=10) == {"items": ["a"], "total": 10}
