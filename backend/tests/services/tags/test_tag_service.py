"""Tests for normalized tag service helpers used by lifecycle automation."""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from app.models.tag import Tag
from app.services.tags import TagService


def _result(value: object) -> MagicMock:
    result = MagicMock()
    result.scalar_one.return_value = value
    return result


async def test_get_or_create_tag_upserts_then_fetches_workspace_tag() -> None:
    """Named tag creation is idempotent and resolves the ORM row after upsert."""
    tag = Tag(id=uuid.uuid4(), workspace_id=uuid.uuid4(), name="no-show", color="#6366f1")
    db = MagicMock()
    db.execute = AsyncMock(side_effect=[MagicMock(), _result(tag)])

    service = TagService(db)
    result = await service.get_or_create_tag(tag.workspace_id, " no-show ")

    assert result is tag
    assert db.execute.await_count == 2
    insert_stmt = db.execute.await_args_list[0].args[0]
    assert "ON CONFLICT ON CONSTRAINT uq_tags_workspace_name DO NOTHING" in str(insert_stmt)


async def test_add_tag_to_contact_uses_contact_tag_unique_constraint() -> None:
    """Applying a lifecycle tag creates the join row idempotently."""
    tag = Tag(id=uuid.uuid4(), workspace_id=uuid.uuid4(), name="no-show", color="#6366f1")
    db = MagicMock()
    db.execute = AsyncMock(side_effect=[MagicMock(), _result(tag), MagicMock()])

    await TagService(db).add_tag_to_contact(
        workspace_id=tag.workspace_id,
        contact_id=123,
        name="no-show",
    )

    insert_stmt = db.execute.await_args_list[-1].args[0]
    assert "ON CONFLICT ON CONSTRAINT uq_contact_tags_contact_tag DO NOTHING" in str(insert_stmt)


async def test_add_tags_to_contact_trims_blanks_and_deduplicates() -> None:
    """Bulk string helpers do not create empty or duplicate tag requests."""
    db = MagicMock()
    service = TagService(db)
    service.add_tag_to_contact = AsyncMock(return_value=MagicMock())  # type: ignore[method-assign]
    workspace_id = uuid.uuid4()

    await service.add_tags_to_contact(
        workspace_id=workspace_id,
        contact_id=42,
        names=[" vip ", "", "vip", "warm"],
    )

    assert service.add_tag_to_contact.await_count == 2
    assert [call.kwargs["name"] for call in service.add_tag_to_contact.await_args_list] == [
        "vip",
        "warm",
    ]


async def test_replace_contact_tags_deletes_missing_and_upserts_requested_tags() -> None:
    """Legacy string tag updates replace the normalized contact tag set."""
    workspace_id = uuid.uuid4()
    tags = [
        Tag(id=uuid.uuid4(), workspace_id=workspace_id, name="vip", color="#6366f1"),
        Tag(id=uuid.uuid4(), workspace_id=workspace_id, name="warm", color="#6366f1"),
    ]
    db = MagicMock()
    db.execute = AsyncMock()
    service = TagService(db)

    async def fake_get_or_create_tag(**kwargs: Any) -> Tag:
        return next(tag for tag in tags if tag.name == kwargs["name"])

    service.get_or_create_tag = AsyncMock(side_effect=fake_get_or_create_tag)  # type: ignore[method-assign]

    result = await service.replace_contact_tags_by_name(
        workspace_id=workspace_id,
        contact_id=42,
        names=[" vip ", "warm", "vip"],
    )

    assert result == tags
    assert service.get_or_create_tag.await_count == 2
    executed_sql = [str(call.args[0]) for call in db.execute.await_args_list]
    contact_tag_upsert = "ON CONFLICT ON CONSTRAINT uq_contact_tags_contact_tag DO NOTHING"
    assert any("DELETE FROM contact_tags" in sql for sql in executed_sql)
    assert sum(contact_tag_upsert in sql for sql in executed_sql) == 2
