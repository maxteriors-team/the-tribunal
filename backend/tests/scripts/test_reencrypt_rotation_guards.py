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

_SCRIPT = (
    Path(__file__).resolve().parents[3] / "scripts" / "ops" / "reencrypt_with_old_key.py"
)


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
