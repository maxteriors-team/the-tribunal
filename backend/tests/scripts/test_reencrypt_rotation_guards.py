"""Guards against a key rotation that reports success while doing nothing.

The original script declared rotation targets whose model columns were still
plaintext, hit ``InvalidToken`` on every row, counted them as "skipped", and
exited 0 — so an operator could believe the key had been rotated when the data
was never touched (audit finding H-2). These tests pin the two failure modes
that must now exit non-zero.
"""

import importlib.util
import sys
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.encryption import EncryptedString, LookupHash

_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "ops" / "reencrypt_with_old_key.py"


def _load_script():
    """Import the ops script by path (it lives outside the app package)."""
    spec = importlib.util.spec_from_file_location("reencrypt_with_old_key", _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


rotate = _load_script()


class _Base(DeclarativeBase):
    pass


class GoodModel(_Base):
    """A correctly migrated model: encrypted column + clear lookup hash."""

    __tablename__ = "good_model"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(EncryptedString())
    email_hash: Mapped[str] = mapped_column(LookupHash())


class PlaintextModel(_Base):
    """The bug this guard exists for: declared for rotation but NOT encrypted."""

    __tablename__ = "plaintext_model"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(sa.String(255))


class EncryptedHashModel(_Base):
    """A lookup hash must stay comparable, so it must not be encrypted."""

    __tablename__ = "encrypted_hash_model"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(EncryptedString())
    email_hash: Mapped[str] = mapped_column(EncryptedString())


class TestTargetValidation:
    def test_correctly_migrated_target_passes(self) -> None:
        target = rotate.RotationTarget(GoodModel, ("email",), {"email": "email_hash"})
        assert rotate.validate_targets([target]) == []
        rotate.ensure_targets_valid([target])  # must not raise

    def test_plaintext_column_is_rejected(self) -> None:
        """A String column declared for rotation is the silent no-op bug."""
        problems = rotate.validate_targets([rotate.RotationTarget(PlaintextModel, ("email",))])

        assert len(problems) == 1
        assert "PlaintextModel.email" in problems[0]
        assert "not EncryptedString" in problems[0]

    def test_plaintext_column_aborts_with_nonzero_exit(self) -> None:
        with pytest.raises(rotate.ScriptAbortError) as exc:
            rotate.ensure_targets_valid([rotate.RotationTarget(PlaintextModel, ("email",))])

        assert exc.value.exit_code == rotate.EXIT_FAILURE
        assert exc.value.exit_code != 0

    def test_missing_column_is_rejected(self) -> None:
        problems = rotate.validate_targets([rotate.RotationTarget(GoodModel, ("nope",))])

        assert len(problems) == 1
        assert "no such column" in problems[0]

    def test_encrypted_lookup_hash_is_rejected(self) -> None:
        problems = rotate.validate_targets(
            [rotate.RotationTarget(EncryptedHashModel, ("email",), {"email": "email_hash"})]
        )

        assert any("must be stored in the clear" in p for p in problems)

    def test_real_rotation_targets_are_all_encrypted(self) -> None:
        """The shipped target list must match the shipped models."""
        assert rotate.validate_targets(rotate.rotation_targets()) == []


class TestReportExitCodes:
    def test_clean_rotation_passes(self) -> None:
        report = rotate.RotationReport(
            (rotate.RotationStats("contacts", scanned=10, rotated=10, skipped_invalid=0),)
        )

        assert report.passed
        assert report.exit_code == rotate.EXIT_OK
        assert "RESULT: PASS" in report.render()

    def test_wholly_skipped_table_fails(self) -> None:
        """Scanned rows but zero re-encrypted is the silent-failure case."""
        stats = rotate.RotationStats("contacts", scanned=10, rotated=0, skipped_invalid=10)
        report = rotate.RotationReport((stats,))

        assert stats.failed
        assert stats.status == "FAIL"
        assert not report.passed
        assert report.exit_code == rotate.EXIT_FAILURE

        rendered = report.render()
        assert "RESULT: FAIL" in rendered
        assert "0 of 10 scanned rows re-encrypted" in rendered
        assert "STILL ENCRYPTED UNDER THE OLD KEY" in rendered

    def test_partially_skipped_table_fails(self) -> None:
        """A partial skip must not be reported as success either."""
        stats = rotate.RotationStats("contacts", scanned=10, rotated=7, skipped_invalid=3)
        report = rotate.RotationReport((stats,))

        assert stats.degraded
        assert stats.status == "PARTIAL"
        assert report.exit_code == rotate.EXIT_FAILURE
        assert "3 left behind" in report.render()

    def test_empty_table_is_not_a_failure(self) -> None:
        """Nothing to rotate is a legitimate pass, not a silent no-op."""
        report = rotate.RotationReport(
            (rotate.RotationStats("link_clicks", scanned=0, rotated=0, skipped_invalid=0),)
        )

        assert report.passed
        assert report.exit_code == rotate.EXIT_OK

    def test_summary_reports_per_table_counts(self) -> None:
        report = rotate.RotationReport(
            (
                rotate.RotationStats("contacts", scanned=5, rotated=5, skipped_invalid=0),
                rotate.RotationStats("users", scanned=3, rotated=3, skipped_invalid=0),
            )
        )
        rendered = report.render()

        assert "contacts" in rendered
        assert "users" in rendered
        assert report.total_scanned == 8
        assert report.total_rotated == 8

    def test_one_failing_table_fails_the_whole_run(self) -> None:
        report = rotate.RotationReport(
            (
                rotate.RotationStats("contacts", scanned=5, rotated=5, skipped_invalid=0),
                rotate.RotationStats("users", scanned=4, rotated=0, skipped_invalid=4),
            )
        )

        assert not report.passed
        assert report.exit_code == rotate.EXIT_FAILURE


class TestSessionTargetsRequestedEnvironment:
    """Guards against the rotation running against the *wrong database*.

    ``app.db.session`` builds ``AsyncSessionLocal`` from the ambient
    ``DATABASE_URL`` at import time, which ``backend/.env`` points at the
    developer's dev database. A module-scope import therefore freezes that URL
    before ``bootstrap()`` promotes ``PRODUCTION_DATABASE_URL``, so ``--env
    production`` silently reads and *writes* local rows while every log line
    says "production" — re-encrypting the dev database under the production key
    and leaving production itself untouched. It reports success, and the row
    counts it prints are real, just from the wrong database.
    """

    def test_script_does_not_bind_the_ambient_session_factory(self) -> None:
        """The module must not capture ``AsyncSessionLocal`` at import time."""
        assert not hasattr(rotate, "AsyncSessionLocal"), (
            "reencrypt_with_old_key imported AsyncSessionLocal at module scope; "
            "it freezes the ambient DATABASE_URL and makes --env production "
            "rotate the local database. Use script_sessionmaker(ctx) instead."
        )

    def test_script_resolves_its_session_from_the_harness(self) -> None:
        """The session factory must come from ``script_sessionmaker(ctx)``."""
        assert hasattr(rotate, "script_sessionmaker"), (
            "reencrypt_with_old_key must build its session via "
            "script_sessionmaker(ctx) so the resolved --env URL wins "
            "regardless of import order."
        )

    def test_run_passes_the_context_to_the_session_factory(self) -> None:
        """``_run`` must hand the *resolved context* to the factory.

        Calling ``script_sessionmaker()`` with anything but ``ctx`` would
        resolve a different environment than the operator asked for.
        """
        source = _SCRIPT.read_text(encoding="utf-8")

        assert "script_sessionmaker(ctx)" in source
        assert "AsyncSessionLocal()" not in source


class TestEveryEncryptedColumnIsRotated:
    """Guards the inverse of ``validate_targets``: encrypted -> declared.

    ``validate_targets`` proves each *declared* column is really encrypted. The
    dangerous direction is the other one: a column that is encrypted but never
    declared is skipped by the rotation, and once the old key is discarded its
    data is unreadable forever — surfacing as an ``InvalidToken`` 500 on every
    page that loads the row.

    This was not hypothetical. ``conversations`` and ``messages`` moved onto
    ``EncryptedString`` (SMS bodies, call transcripts, recording URLs) while the
    target list still named only contacts/users, so a rotation would have
    orphaned 30 of the 46 encrypted columns in the schema — including
    ``global_opt_outs.phone_number``, which gates every outbound send.
    """

    def test_no_encrypted_column_is_left_undeclared(self) -> None:
        """Every EncryptedString column in the schema must be rotatable."""
        undeclared = rotate.undeclared_encrypted_columns(rotate.rotation_targets())

        assert undeclared == [], (
            "these columns are encrypted at rest but are not declared in "
            "rotation_targets(), so a key rotation would silently leave them "
            "under the discarded key: " + ", ".join(undeclared)
        )

    def test_declared_targets_are_all_well_formed(self) -> None:
        """The expanded target list must still pass the existing validation."""
        assert rotate.validate_targets(rotate.rotation_targets()) == []

    def test_guard_detects_a_dropped_target(self) -> None:
        """Removing a covered model must be reported, not ignored."""
        targets = tuple(t for t in rotate.rotation_targets() if t.model.__name__ != "Message")
        undeclared = rotate.undeclared_encrypted_columns(targets)

        assert any(c.startswith("Message.body") for c in undeclared)
        assert any(c.startswith("Message.transcript") for c in undeclared)

    def test_undeclared_column_aborts_before_touching_data(self) -> None:
        """An undeclared encrypted column must abort the run non-zero."""
        targets = tuple(t for t in rotate.rotation_targets() if t.model.__name__ != "GlobalOptOut")

        with pytest.raises(rotate.ScriptAbortError) as excinfo:
            rotate.ensure_full_coverage(targets)

        assert excinfo.value.exit_code == rotate.EXIT_FAILURE
        assert "not" in str(excinfo.value)

    def test_conversation_and_message_payloads_are_covered(self) -> None:
        """Pin the columns that carry the bulk of customer PII."""
        by_model = {t.model.__name__: t for t in rotate.rotation_targets()}

        assert "body" in by_model["Message"].columns
        assert "transcript" in by_model["Message"].columns
        assert "contact_phone" in by_model["Conversation"].columns
        # The lookup hash must be re-derived or inbound matching silently breaks.
        assert by_model["Conversation"].hash_columns["contact_phone"] == "contact_phone_hash"


class TestAbsentTableIsReportedNotSkipped:
    """A declared model whose migration has not reached this environment.

    Rotation must neither crash (``UndefinedTableError`` rolls back every table
    already rotated in the transaction) nor render identically to an empty
    table — an operator has to be able to tell "nothing to do" apart from
    "never looked".
    """

    def test_absent_table_is_not_a_failure(self) -> None:
        stats = rotate.RotationStats(
            "agent_training_examples", scanned=0, rotated=0, skipped_invalid=0, absent=True
        )

        assert not stats.failed
        assert not stats.degraded
        assert stats.status == "absent"
        assert rotate.RotationReport((stats,)).passed

    def test_absent_status_is_distinct_from_an_empty_table(self) -> None:
        empty = rotate.RotationStats("caller_memories", scanned=0, rotated=0, skipped_invalid=0)
        absent = rotate.RotationStats(
            "agent_training_examples", scanned=0, rotated=0, skipped_invalid=0, absent=True
        )

        assert empty.status == "ok"
        assert absent.status == "absent"

    def test_absent_table_appears_in_the_summary(self) -> None:
        report = rotate.RotationReport(
            (
                rotate.RotationStats("contacts", scanned=5, rotated=5, skipped_invalid=0),
                rotate.RotationStats(
                    "agent_training_examples",
                    scanned=0,
                    rotated=0,
                    skipped_invalid=0,
                    absent=True,
                ),
            )
        )
        rendered = report.render()

        assert "agent_training_examples" in rendered
        assert "absent" in rendered
        assert report.exit_code == rotate.EXIT_OK
