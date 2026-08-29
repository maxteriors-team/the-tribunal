"""Shared row-level ownership predicate for sales-scoped quotes."""

from sqlalchemy import true
from sqlalchemy.sql.elements import ColumnElement

from app.models.quote import Quote


def quote_owner_predicate(owner_user_id: int | None) -> ColumnElement[bool]:
    """Match one sales owner's quotes, or all quotes when ownership is unrestricted."""
    if owner_user_id is None:
        return true()
    return (Quote.assigned_user_id == owner_user_id) | (
        Quote.assigned_user_id.is_(None) & (Quote.created_by_id == owner_user_id)
    )
