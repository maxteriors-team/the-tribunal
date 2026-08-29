"""The session-scoped tenant filter actually reaches the emitted SQL.

Asserted by compiling statements and reading the WHERE clause, with **no
database**. That is deliberate rather than a shortcut: the backend CI job has no
Postgres service and runs with ``-m 'not integration'``, so a test that needed a
live database would not run in the required check. A control nobody's CI
executes is a claim, not a control.

Covers the four things that can go wrong, in descending order of how badly:

1. the tenant id is **cached** across requests, so tenant B is served tenant A's
   rows (sqlalchemy#5760 — the reason the non-lambda form is used);
2. the filter is not applied at all;
3. the filter is applied to a system session, silently starving the workers;
4. a new tenant-owned model forgets the marker and is never filtered.
"""

from __future__ import annotations

import contextlib
import uuid

import pytest
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.tenancy import (
    SYSTEM_KEY,
    WORKSPACE_KEY,
    UnlabelledTenancyError,
    WorkspaceScoped,
    mark_session_as_system,
    scope_session_to_workspace,
    session_system_reason,
    session_workspace_id,
    workspace_scoped_models,
)
from app.models.contact import Contact
from app.models.user import User

WS_A = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
WS_B = uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")


def _binds(workspace_id: uuid.UUID) -> tuple[str, str]:
    """Both spellings a UUID can take in compiled SQL.

    ``literal_binds`` renders the ``UUID(as_uuid=True)`` type without dashes, so
    asserting on ``str(uuid)`` alone silently never matches — a test that passes
    for the wrong reason. Checked both ways so neither rendering can hide a
    missing predicate.
    """
    return str(workspace_id), workspace_id.hex


def _mentions(sql: str, workspace_id: uuid.UUID) -> bool:
    return any(form in sql for form in _binds(workspace_id))


def _compile(session: Session, stmt: object) -> str:
    """Render the SQL the ORM would send, without sending it.

    Goes through ``session.execute`` far enough to fire ``do_orm_execute`` — the
    listener rewrites the statement in that event, so compiling the statement
    directly would test nothing.
    """
    captured: list[str] = []

    def _capture(state: object) -> None:
        stmt_after = state.statement  # type: ignore[attr-defined]
        captured.append(str(stmt_after.compile(compile_kwargs={"literal_binds": True})))

    event.listen(session, "do_orm_execute", _capture)
    try:
        # The listener under test rewrites the statement and our capture records
        # it; execution then dies reaching for a connection there isn't one of.
        # That failure is the point at which we already have what we need.
        with contextlib.suppress(Exception):
            session.execute(stmt)  # type: ignore[arg-type]
    finally:
        event.remove(session, "do_orm_execute", _capture)

    return captured[0] if captured else ""


@pytest.fixture
def session() -> Session:
    """A real Session, never connected. Enough to fire ORM execution events."""
    return Session()


# ── 1. The caching trap (blocking) ────────────────────────────────────────


def test_two_tenants_in_a_row_each_get_their_own_id() -> None:
    """The bug that would turn this control into a breach.

    ``with_loader_criteria`` also accepts a lambda, compiled once per class. A
    lambda that *calls* something to fetch the tenant id has that call evaluated
    once and cached (sqlalchemy#5760), so every later request would be served the
    first tenant's rows. Verified: regressing the listener to that form fails
    this test and two others.

    A lambda closing directly over the id is, by contrast, fine — also verified,
    by regressing to it and watching these pass. The implementation avoids
    lambdas altogether so neither case has to be reasoned about again.
    """
    first = Session()
    scope_session_to_workspace(first, WS_A)
    sql_a = _compile(first, select(Contact))

    second = Session()
    scope_session_to_workspace(second, WS_B)
    sql_b = _compile(second, select(Contact))

    assert _mentions(sql_a, WS_A)
    assert not _mentions(sql_a, WS_B)
    assert _mentions(sql_b, WS_B), "second tenant was served the first tenant's id"
    assert not _mentions(sql_b, WS_A), "first tenant's id leaked into the second query"


# ── 2. The filter is applied ──────────────────────────────────────────────


def test_scoped_session_filters_by_workspace(session: Session) -> None:
    scope_session_to_workspace(session, WS_A)
    sql = _compile(session, select(Contact))

    assert "workspace_id" in sql
    assert _mentions(sql, WS_A)


def test_scoping_survives_a_query_that_already_has_a_where(session: Session) -> None:
    """A caller's own filter must not displace the tenant predicate."""
    scope_session_to_workspace(session, WS_A)
    sql = _compile(session, select(Contact).where(Contact.email == "x@example.test"))

    assert _mentions(sql, WS_A)
    assert "contacts.email" in sql


# ── 3. The escape hatch ───────────────────────────────────────────────────


def test_system_session_is_not_filtered(session: Session) -> None:
    """Workers sweep every workspace; filtering them silently returns nothing."""
    mark_session_as_system(session, reason="test: worker sweeps all workspaces")
    sql = _compile(session, select(Contact))

    assert not _mentions(sql, WS_A)
    assert "WHERE" not in sql, f"a system session was filtered: {sql}"


def test_a_session_cannot_be_both_scoped_and_system(session: Session) -> None:
    """Order-dependent scope is the bug class this module removes."""
    scope_session_to_workspace(session, WS_A)
    with pytest.raises(ValueError, match="already scoped"):
        mark_session_as_system(session, reason="test")

    other = Session()
    mark_session_as_system(other, reason="test")
    with pytest.raises(ValueError, match="already marked as a system"):
        scope_session_to_workspace(other, WS_A)


def test_rescoping_to_a_different_workspace_is_refused(session: Session) -> None:
    scope_session_to_workspace(session, WS_A)
    scope_session_to_workspace(session, WS_A)  # idempotent
    with pytest.raises(ValueError, match="already scoped"):
        scope_session_to_workspace(session, WS_B)


def test_system_sessions_must_state_a_reason(session: Session) -> None:
    """The reason is the audit trail; an empty one defeats the grep."""
    with pytest.raises(ValueError, match="non-empty reason"):
        mark_session_as_system(session, reason="   ")


# ── 4. Coverage: no tenant-owned model escapes the marker ─────────────────


def test_every_model_with_a_workspace_id_carries_the_marker() -> None:
    """A new tenant-owned model cannot silently opt out of filtering.

    Equality, not a subset, so it fails in both directions: a model that gains a
    ``workspace_id`` without the marker fails, and a marked model that has no
    such column fails too (the listener would raise on it at runtime).
    """
    with_column: set[str] = set()
    with_marker: set[str] = set()

    for mapper in Base.registry.mappers:
        model = mapper.class_
        table = getattr(model, "__table__", None)
        if table is not None and "workspace_id" in table.columns:
            with_column.add(model.__name__)
        if issubclass(model, WorkspaceScoped):
            with_marker.add(model.__name__)

    missing = sorted(with_column - with_marker)
    spurious = sorted(with_marker - with_column)

    assert not missing, (
        "These models own workspace data but are not filtered, so a query that "
        "forgets its tenant predicate returns every workspace's rows:\n  "
        + "\n  ".join(missing)
        + "\n\nAdd the WorkspaceScoped marker to each."
    )
    assert not spurious, (
        "These models carry the WorkspaceScoped marker but have no workspace_id "
        "column, so the filter would fail at runtime:\n  " + "\n  ".join(spurious)
    )


def test_the_marker_is_actually_applied_to_something() -> None:
    """Guards the coverage test above from passing vacuously."""
    models = workspace_scoped_models()
    assert len(models) > 50, f"only {len(models)} scoped models; expected ~90"


def test_unscoped_models_are_untouched(session: Session) -> None:
    """``users`` is global by design; filtering it would break login."""
    scope_session_to_workspace(session, WS_A)
    sql = _compile(session, select(User))

    assert not _mentions(sql, WS_A)
    assert "WHERE" not in sql, f"a global model was filtered: {sql}"


# ── Session labelling helpers ─────────────────────────────────────────────


def test_a_stray_value_in_the_system_key_does_not_disable_filtering() -> None:
    """The exemption must only count when it is what the helper actually wrote.

    Found by a real failure: a bare ``MagicMock`` stand-in session returns a
    truthy mock for ``info.get(...)``, which read as "exempt" and silently turned
    filtering off. Production sessions are real, so this was test-only — but the
    label that disables the filter should be type-checked, not merely truthy, so
    an unexpected value fails *toward* filtering.
    """
    session = Session()
    session.info[SYSTEM_KEY] = object()  # not the string the helper writes
    assert session_system_reason(session) is None

    scope_session_to_workspace(session, WS_A)  # not blocked by the stray value
    assert _mentions(_compile(session, select(Contact)), WS_A)


def test_system_reason_round_trips(session: Session) -> None:
    assert session_system_reason(session) is None
    mark_session_as_system(session, reason="nightly sweep")
    assert session_system_reason(session) == "nightly sweep"


# ── The two call sites that label sessions in production ────────────────


async def test_system_session_helper_labels_and_closes() -> None:
    """``system_session`` is the only sanctioned way to read across tenants."""
    from app.db.session import system_session

    async with system_session("test: sweeps every workspace") as db:
        assert session_system_reason(db) == "test: sweeps every workspace"
        assert session_workspace_id(db) is None


def test_every_worker_uses_the_system_session_helper() -> None:
    """Workers must go through the audited hatch, not the raw sessionmaker.

    ``AsyncSessionLocal`` produces an *unlabelled* session, which phase 2 will
    reject outright. Asserting on the source keeps ``grep -rn system_session`` an
    honest inventory of what can read across tenants.
    """
    import pathlib

    offenders = []
    for path in sorted(pathlib.Path("app/workers").glob("*.py")):
        source = path.read_text()
        if "AsyncSessionLocal() as" in source:
            offenders.append(path.name)

    assert not offenders, (
        "These workers open an unlabelled session instead of system_session():\n  "
        + "\n  ".join(offenders)
    )


async def test_request_dependencies_scope_the_session_to_the_caller() -> None:
    """``get_workspace`` labels the request session once membership is verified.

    The other half of the design: requests are scoped, workers are exempt, and
    nothing else should be either. Without this the whole mechanism is inert on
    the request path, which is where the customer data is.
    """
    from unittest.mock import AsyncMock, MagicMock

    from app.api.deps import get_workspace

    membership = MagicMock()
    workspace = MagicMock()
    workspace.id = WS_A
    workspace.is_active = True

    def _result(value: object) -> MagicMock:
        result = MagicMock()
        result.scalar_one_or_none.return_value = value
        return result

    db = MagicMock()
    db.info = {}
    db.execute = AsyncMock(side_effect=[_result(membership), _result(workspace)])

    request = MagicMock()
    request.state = MagicMock(spec=[])  # no api_key_workspace_id bound

    await get_workspace(
        request=request,
        workspace_id=WS_A,
        current_user=MagicMock(id=1),
        db=db,
    )

    assert db.info[WORKSPACE_KEY] == WS_A


def test_an_unlabelled_session_warns_and_still_returns_rows(session: Session) -> None:
    """Observe mode: log the call site, do not break it.

    This path had no test in the first draft and shipped broken — the warning
    passed ``event=`` to structlog, which already binds the first positional
    argument to ``event``, so every unlabelled query raised ``TypeError``
    instead of logging. It was caught by integration tests that only run in the
    migrations workflow, because the required backend job has no Postgres.

    Phase 1's entire purpose is to observe without breaking anything, so the
    observing itself has to work.
    """
    from structlog.testing import capture_logs

    assert session_workspace_id(session) is None
    assert session_system_reason(session) is None

    # Not via ``_compile``: that suppresses exceptions so it can read the
    # rewritten statement without a connection, which would have swallowed the
    # very TypeError this test exists for. Assert on the emitted log instead.
    with capture_logs() as logs, contextlib.suppress(Exception):
        session.execute(select(Contact))

    warnings = [entry for entry in logs if entry["event"] == "unlabelled_tenancy_query"]
    assert warnings, f"no warning emitted for an unlabelled query; got {logs}"
    assert warnings[0]["security_event"] is True
    assert "Contact" in warnings[0]["entities"]

    # And phase 1 does not change behaviour: still unfiltered.
    assert "WHERE" not in _compile(Session(), select(Contact))


def test_enforcing_mode_raises_and_names_the_entities(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Phase 2: the same call site fails closed, naming what to label."""
    import app.db.tenancy as tenancy_module

    monkeypatch.setattr(tenancy_module, "ENFORCE_LABELLING", True)

    with pytest.raises(UnlabelledTenancyError) as exc:
        session.execute(select(Contact))

    assert "Contact" in str(exc.value)


def test_enforcing_mode_leaves_global_models_alone(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Phase 2 must not break login: ``users`` has no tenant to label."""
    import app.db.tenancy as tenancy_module

    monkeypatch.setattr(tenancy_module, "ENFORCE_LABELLING", True)

    # Reaches the database layer and fails there, not in the tenancy listener.
    with pytest.raises(Exception) as exc:  # noqa: B017 - no connection available
        session.execute(select(User))
    assert not isinstance(exc.value, UnlabelledTenancyError)


def test_session_workspace_id_reads_back_what_was_set(session: Session) -> None:
    assert session_workspace_id(session) is None
    scope_session_to_workspace(session, WS_A)
    assert session_workspace_id(session) == WS_A
    assert session.info[WORKSPACE_KEY] == WS_A


def test_system_marker_records_its_reason(session: Session) -> None:
    mark_session_as_system(session, reason="reminder_worker sweeps all workspaces")
    assert session.info[SYSTEM_KEY] == "reminder_worker sweeps all workspaces"


def test_phase_two_error_names_both_escape_hatches() -> None:
    """The error has to tell whoever hits it what to do, not just what broke."""
    message = str(UnlabelledTenancyError(["Contact"]))
    assert "scope_session_to_workspace" in message
    assert "mark_session_as_system" in message
    assert "Contact" in message
