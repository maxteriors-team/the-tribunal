"""Tests for ``app.db.scope.apply_workspace_scope``.

The helper centralizes the ``Model.workspace_id == workspace_id`` predicate
that ~50 routers previously hand-rolled. Two behaviours we lock down:

* Applying the scope on a tenant model appends a single ``WHERE`` predicate
  binding the supplied workspace UUID.
* Calling the helper on a model that lacks ``workspace_id`` raises
  ``TypeError`` — the whole point of centralizing this is to make accidental
  use on a non-tenant model fail loudly.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import UUID, Column, String, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.db.scope import apply_workspace_scope, select_workspace_owned


class _ScopeTestBase(DeclarativeBase):
    """Isolated declarative base — we don't want these test tables registered
    on the production ``app.db.base.Base`` metadata."""


class _TenantModel(_ScopeTestBase):
    __tablename__ = "scope_test_tenant"

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)


class _GlobalModel(_ScopeTestBase):
    """Model with no ``workspace_id`` column — must be rejected."""

    __tablename__ = "scope_test_global"

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)


class _NotAModel:
    """A plain class, not a mapped model — also must be rejected."""

    workspace_id = Column(UUID)  # decoy attribute, but no __table__


class TestApplyWorkspaceScope:
    def test_appends_workspace_predicate(self) -> None:
        workspace_id = uuid.uuid4()
        query = select(_TenantModel)

        scoped = apply_workspace_scope(query, _TenantModel, workspace_id)

        compiled = scoped.compile(compile_kwargs={"literal_binds": True})
        sql = str(compiled).lower()
        assert "where" in sql
        assert "workspace_id" in sql
        assert workspace_id.hex in str(compiled)

    def test_preserves_existing_where_clauses(self) -> None:
        workspace_id = uuid.uuid4()
        query = select(_TenantModel).where(_TenantModel.name == "alpha")

        scoped = apply_workspace_scope(query, _TenantModel, workspace_id)

        # Both predicates must be present — the helper appends, not replaces.
        compiled = str(scoped.compile(compile_kwargs={"literal_binds": True})).lower()
        assert "name" in compiled
        assert "workspace_id" in compiled

    def test_returns_new_select_without_mutating_input(self) -> None:
        workspace_id = uuid.uuid4()
        query = select(_TenantModel)
        original_sql = str(query)

        apply_workspace_scope(query, _TenantModel, workspace_id)

        # SQLAlchemy Select is immutable; the input must be untouched.
        assert str(query) == original_sql

    def test_raises_when_model_lacks_workspace_id_column(self) -> None:
        with pytest.raises(TypeError, match="workspace_id"):
            apply_workspace_scope(select(_GlobalModel), _GlobalModel, uuid.uuid4())

    def test_raises_when_target_is_not_a_mapped_model(self) -> None:
        with pytest.raises(TypeError, match="workspace_id"):
            apply_workspace_scope(
                select(_TenantModel),
                _NotAModel,  # type: ignore[arg-type]
                uuid.uuid4(),
            )

    def test_rejects_non_sequence_loader_options(self) -> None:
        with pytest.raises(TypeError, match="options must be a sequence"):
            select_workspace_owned(
                _TenantModel,
                uuid.uuid4(),
                options=True,  # type: ignore[arg-type]
            )
