"""Session-scoped tenancy: every ORM read is filtered to one workspace.

Every access control this codebase has lives in a FastAPI dependency
(``docs/technician-role-audit.md``, findings 1-10). A service, worker, or
WebSocket handler that queries ``Contact`` directly is protected by none of them.
:func:`app.db.scope.assert_workspace_owned` exists for that, but it is opt-in,
and finding 7 found 50 routes that skipped the equivalent opt-in check. Anything
optional is eventually forgotten.

This module makes the filter automatic. A session is labelled with the workspace
it is allowed to see, and a ``do_orm_execute`` listener appends
``workspace_id = :id`` to every ORM SELECT touching a :class:`WorkspaceScoped`
entity.

**What this is not.** It is a correctness control with a security benefit, not a
boundary. It rewrites ORM statements, so raw ``text()`` SQL and SQL injection
both walk straight past it. Only Postgres row-level security stops those, and
:doc:`the plan <../../../.ezcoder/plans/data-layer-tenancy.md>` records why RLS
is not viable here yet: Alembic connects as the table *owner*, and owners bypass
RLS unless every table is switched to ``FORCE ROW LEVEL SECURITY`` — so a policy
added today would be silently inert. The realistic threat this *does* close is a
developer writing ``select(Contact).where(Contact.id == x)`` and forgetting the
tenant.

Usage::

    # A request, scoped to the workspace the caller is a member of.
    scope_session_to_workspace(session, workspace_id)

    # A worker that legitimately sweeps every workspace.
    mark_session_as_system(session, reason="reminder_worker sweeps all workspaces")

Sessions are labelled rather than a ``ContextVar`` being read: a context variable
survives across ``await`` boundaries into background tasks, so one missed reset
leaks a tenant id into unrelated work. ``session.info`` lives exactly as long as
the session it describes.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any, Final

import structlog
from sqlalchemy import event
from sqlalchemy.orm import DeclarativeBase, ORMExecuteState, Session, with_loader_criteria

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger(__name__)

#: ``session.info`` keys. Namespaced so they cannot collide with application use.
WORKSPACE_KEY: Final = "app.tenancy.workspace_id"
SYSTEM_KEY: Final = "app.tenancy.system"

#: Phase 1 (observe). An unlabelled session logs and is *not* filtered, so the
#: warning stream can be driven to zero in production before anything breaks.
#: Phase 2 flips this to raise. See the plan's rollout section: turning it on
#: before the count is zero takes out every unlabelled call site at once.
ENFORCE_LABELLING: Final = False


class WorkspaceScoped:
    """Marks a model whose rows belong to exactly one workspace.

    Declares nothing. The model already has its own ``workspace_id`` column, with
    its own foreign key, index, and nullability — restating that here would mean
    two sources of truth and an Alembic diff. This is purely the marker the
    listener matches on, so tenancy is visible in the model definition rather
    than hidden in a list somewhere else.

    ``tests/db/test_tenancy_filter.py`` asserts that every model carrying a
    ``workspace_id`` column also carries this mixin, so a new tenant-owned model
    cannot silently opt out.
    """


def scope_session_to_workspace(session: AsyncSession | Session, workspace_id: uuid.UUID) -> None:
    """Restrict every subsequent ORM read on ``session`` to ``workspace_id``.

    Raises:
        ValueError: if the session was already marked as a system session.
            Silently downgrading a system session to a scoped one (or the
            reverse) would make the effective scope depend on call order, which
            is exactly the class of bug this module exists to remove.
    """
    if session_system_reason(session) is not None:
        raise ValueError(
            "This session is already marked as a system (cross-workspace) session; "
            "refusing to also scope it to a single workspace. Use a new session."
        )
    existing = session.info.get(WORKSPACE_KEY)
    if existing is not None and existing != workspace_id:
        raise ValueError(
            f"Session is already scoped to workspace {existing}; refusing to "
            f"re-scope it to {workspace_id}. Use a new session."
        )
    session.info[WORKSPACE_KEY] = workspace_id


def mark_session_as_system(session: AsyncSession | Session, *, reason: str) -> None:
    """Exempt ``session`` from tenant filtering, for genuinely cross-workspace work.

    The escape hatch. Roughly 40 worker call sites legitimately sweep every
    workspace, and the membership lookup that *decides* a caller's workspace
    cannot itself be workspace-scoped without a chicken-and-egg deadlock.

    ``reason`` is required and unused at runtime. It exists so each exemption
    states its justification at the call site, and so
    ``grep -rn mark_session_as_system`` is a complete audit of everything that
    can read across tenants.
    """
    if session.info.get(WORKSPACE_KEY) is not None:
        raise ValueError(
            "This session is already scoped to a workspace; refusing to widen it "
            "to a system session. Use a new session."
        )
    if not reason.strip():
        raise ValueError("mark_session_as_system requires a non-empty reason")
    session.info[SYSTEM_KEY] = reason


def session_workspace_id(session: AsyncSession | Session) -> uuid.UUID | None:
    """The workspace this session is scoped to, or ``None`` if unscoped."""
    value = session.info.get(WORKSPACE_KEY)
    return value if isinstance(value, uuid.UUID) else None


def session_system_reason(session: AsyncSession | Session) -> str | None:
    """Why this session may read across workspaces, or ``None`` if it may not.

    Type-checked rather than merely truthy, mirroring
    :func:`session_workspace_id`. Both labels are read on every query, and the
    exemption is the one that turns filtering *off* — so it only counts when the
    value is what :func:`mark_session_as_system` actually writes. A stray or
    stand-in object in ``info`` reads as "not exempt", which fails toward
    filtering rather than away from it.
    """
    value = session.info.get(SYSTEM_KEY)
    return value if isinstance(value, str) and value else None


def _scoped_entities(state: ORMExecuteState) -> list[type[Any]]:
    """Workspace-scoped entities named by this statement's top-level FROM.

    ``column_descriptions`` is only present on ORM-enabled statements. The
    listener already filtered to ``is_select``, but a Core ``select()`` executed
    through the session still lands here — those have no ORM entities to scope,
    and are skipped rather than crashed on.
    """
    descriptions = getattr(state.statement, "column_descriptions", None)
    if not descriptions:
        return []
    return [
        entity
        for description in descriptions
        if isinstance(entity := description.get("entity"), type)
        and issubclass(entity, WorkspaceScoped)
        and issubclass(entity, DeclarativeBase)
    ]


@event.listens_for(Session, "do_orm_execute")
def _apply_workspace_filter(state: ORMExecuteState) -> None:
    """Append the tenant predicate to every ORM SELECT on a scoped session.

    Relationship and column loads are skipped deliberately:
    ``with_loader_criteria`` already propagates from the originating statement to
    lazy loads and ``selectinload``\\ s, so re-applying here would double the
    predicate and, on a refresh, filter an object the session already holds.
    """
    if not state.is_select or state.is_column_load or state.is_relationship_load:
        return

    if session_system_reason(state.session) is not None:
        return

    workspace_id = session_workspace_id(state.session)
    if workspace_id is None:
        _report_unlabelled(state)
        return

    for entity in _scoped_entities(state):
        # The non-lambda form, deliberately.
        #
        # ``with_loader_criteria`` also takes a lambda, which is compiled once
        # per class. A lambda that closes *directly* over ``workspace_id`` is
        # fine — ``track_closure_variables`` defaults on and re-reads it, and I
        # verified that by regressing this line to that form and watching the
        # tests still pass. The form that breaks is a lambda that *calls*
        # something to get the id (``lambda cls: cls.workspace_id ==
        # get_current()``), per sqlalchemy#5760: the call is evaluated once and
        # cached, so every later request reuses the first tenant's value.
        # Regressing to that form fails three tests in
        # ``tests/db/test_tenancy_filter.py``.
        #
        # This form sidesteps the question entirely: no lambda, no compilation
        # cache, nothing to reason about. Given the failure mode is "serve one
        # customer another customer's rows", the boring construct wins.
        state.statement = state.statement.options(
            with_loader_criteria(
                entity,
                entity.workspace_id == workspace_id,
                include_aliases=True,
            )
        )


def _report_unlabelled(state: ORMExecuteState) -> None:
    """Handle a query on a session with no tenancy label.

    Phase 1 logs; phase 2 raises. Logging first is what makes the rollout safe:
    the warning stream enumerates every call site still to label, in production,
    without breaking any of them.
    """
    entities = [entity.__name__ for entity in _scoped_entities(state)]
    if not entities:
        return

    if ENFORCE_LABELLING:
        raise UnlabelledTenancyError(entities)

    # The event name is the first positional argument — structlog binds that to
    # ``event`` itself, so passing ``event=`` as a keyword raises TypeError.
    # Follows the ``security_event=True`` convention used in app/api/webhooks/.
    log.warning(
        "unlabelled_tenancy_query",
        security_event=True,
        entities=entities,
        detail=(
            "ORM query on workspace-scoped entities from a session with no "
            "tenancy label; returning unfiltered rows. Call "
            "scope_session_to_workspace() or mark_session_as_system()."
        ),
    )


class UnlabelledTenancyError(RuntimeError):
    """Raised in phase 2 when a query runs on a session with no tenancy label."""

    def __init__(self, entities: list[str]) -> None:
        super().__init__(
            f"Query on workspace-scoped entities {sorted(entities)} from a session "
            "with no tenancy label. Call scope_session_to_workspace(session, ws_id) "
            "for request-scoped work, or mark_session_as_system(session, reason=...) "
            "for genuinely cross-workspace work."
        )
        self.entities = entities


def workspace_scoped_models() -> list[type[Any]]:
    """Every mapped model carrying the :class:`WorkspaceScoped` marker."""
    from app.db.base import Base

    return [
        mapper.class_
        for mapper in Base.registry.mappers
        if issubclass(mapper.class_, WorkspaceScoped)
    ]
