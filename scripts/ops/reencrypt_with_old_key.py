"""Re-encrypt all Fernet-encrypted columns after an ``ENCRYPTION_KEY`` rotation.

Run this immediately after rotating ``ENCRYPTION_KEY`` in your environment.
The script holds the **old** key in-memory only for the duration of one pass:
it decrypts each row using the old key, then re-encrypts and writes back with
the new key (whatever ``settings.encryption_key`` currently resolves to).

Usage
-----

    OLD_ENCRYPTION_KEY="<previous secret>" \
        uv run python scripts/ops/reencrypt_with_old_key.py --env local [--dry-run]

The new key must already be set as ``ENCRYPTION_KEY`` in the same shell so the
app's normal config-loading path picks it up.

Safety
------

* **Declared targets are validated before anything is read.** Every target
  column must resolve to a real :class:`EncryptedString` column on the model,
  and every declared ``*_hash`` sibling must exist as a real column. A
  misdeclared target aborts the run with a non-zero exit code, naming the
  offending model and column — it is never downgraded to a warning. (A
  rotation target whose model still stores plaintext ``String`` is exactly the
  drift that let a previous rotation "succeed" without touching the data; see
  ``docs/security-audit-2026-07-27.md`` finding H-2.)
* **A wholly-skipped table is a failure, not a skip.** If a table had rows that
  needed rotation and *none* of them could be re-encrypted, the run exits
  non-zero. Any partial skip is surfaced in the summary and also fails the run.
* Rows whose ciphertext already decrypts under the *new* key are left alone
  (idempotent — safe to re-run) and are not counted as failures.
* Rows whose ciphertext fails under both keys are logged and skipped, never
  overwritten with garbage.
* ``LookupHash`` columns are re-derived from the decrypted plaintext so the
  ``*_hash`` siblings stay aligned with the new key.
* ``--dry-run`` decrypts and re-encrypts in memory, then rolls back — and still
  reports the same PASS/FAIL verdict and exit code, so a dry run cannot claim
  success for a rotation that would not actually work.

Implementation note
-------------------

Encrypted columns are read and written as **raw ciphertext** via
``type_coerce(column, Text)``. :class:`EncryptedString` decrypts in
``process_result_value`` and re-raises :class:`InvalidToken` for any value it
cannot read, so rows still sitting on the old key can never be loaded through
the ORM — the very rows this script exists to fix. Bypassing the type decorator
is what makes rotation possible at all; it also means the write path skips the
``before_update`` hash-sync listeners, so this script sets every ``*_hash``
sibling explicitly.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import logging
import os
import pkgutil
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# --- harness bootstrap: locate ``backend/`` so ``app`` + ``scripts`` import ----
_BACKEND_DIR = next(
    p / "backend"
    for p in Path(__file__).resolve().parents
    if (p / "backend" / "scripts" / "_harness.py").is_file()
)
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from app.core.config import settings  # noqa: E402  (settings.encryption_key drives the new hash)
from app.core.encryption import (  # noqa: E402
    EncryptedString,
    _derive_fernet_key,
    _get_fernet,
    decrypt_json,
    encrypt_json,
    hash_phone,
    hash_value,
)
from scripts._harness import (  # noqa: E402
    EXIT_FAILURE,
    EXIT_OK,
    ExecutionContext,
    ScriptAbortError,
    bootstrap,
    log_event,
    run,
    script_sessionmaker,
)

logger = logging.getLogger("rotate")

_RULE = "─" * 88


# ─── Declared rotation targets ───────────────────────────────────────────────


@dataclass(slots=True, frozen=True)
class RotationTarget:
    """One model's encrypted columns plus their lookup-hash siblings.

    ``columns`` are attribute names on the model — every one of them must be an
    :class:`EncryptedString` column. ``hash_columns`` maps a source column to
    the sibling column holding its deterministic lookup hash.
    """

    model: type[Any]
    columns: tuple[str, ...]
    hash_columns: Mapping[str, str] = field(default_factory=dict)

    @property
    def label(self) -> str:
        """Return the table name (falling back to the class name)."""
        table_name = getattr(self.model, "__tablename__", None)
        return str(table_name) if table_name else self.model.__name__


def rotation_targets() -> tuple[RotationTarget, ...]:
    """Return every model/column pair this rotation must cover.

    Imported lazily so the harness can promote a per-environment
    ``DATABASE_URL`` before the model modules pull in app config.

    Entries are **not** removed when a model lags behind: a target listed here
    whose model still stores plaintext is a bug in the *model*, and
    :func:`ensure_targets_valid` will say so loudly rather than let the rotation
    quietly no-op.
    """
    from app.models.agent_training_example import AgentTrainingExample
    from app.models.attendance import AttendanceEntry, AttendanceEvent
    from app.models.caller_memory import CallerMemory
    from app.models.contact import Contact
    from app.models.contact_ai_memory import ContactAIMemory, ContactAIMemoryFact
    from app.models.conversation import Conversation, Message
    from app.models.conversation_booking_draft import ConversationBookingDraft
    from app.models.demo_request import DemoRequest
    from app.models.field_service import ServiceLocation
    from app.models.google_calendar_connection import GoogleCalendarConnection
    from app.models.human_profile import HumanProfile
    from app.models.invoice import Invoice
    from app.models.invoice_payment import InvoicePayment
    from app.models.invoice_payment_receipt_outbox import InvoicePaymentReceiptOutbox
    from app.models.lead_magnet_lead import LeadMagnetLead
    from app.models.lead_prospect import LeadProspect
    from app.models.link_click import LinkClick
    from app.models.message_attachment import MessageAttachment
    from app.models.opt_out import GlobalOptOut
    from app.models.phone_message import PhoneMessage
    from app.models.referral_partner import ReferralPartner
    from app.models.user import User

    return (
        RotationTarget(
            Contact,
            (
                "email",
                "phone_number",
                "address_line1",
                "address_line2",
                "address_city",
                "address_state",
                "address_zip",
            ),
            {"email": "email_hash", "phone_number": "phone_hash"},
        ),
        RotationTarget(Invoice, ("last_emailed_to", "manual_payment_reference")),
        RotationTarget(InvoicePayment, ("reference",)),
        RotationTarget(
            InvoicePaymentReceiptOutbox,
            (
                "recipient_email",
                "customer_name",
                "service_summary",
                "support_email",
                "support_phone",
                "invoice_url",
            ),
        ),
        RotationTarget(
            User,
            ("email", "phone_number"),
            {"email": "email_hash", "phone_number": "phone_hash"},
        ),
        RotationTarget(
            HumanProfile,
            ("email", "phone_number"),
            {"email": "email_hash", "phone_number": "phone_hash"},
        ),
        RotationTarget(
            LeadMagnetLead,
            ("email", "phone_number", "name"),
            {"email": "email_hash", "phone_number": "phone_hash"},
        ),
        RotationTarget(LinkClick, ("ip_address",)),
        RotationTarget(MessageAttachment, ("source_url",)),
        RotationTarget(GoogleCalendarConnection, ("access_token", "refresh_token")),
        # Conversation/message payloads. These carry the bulk of the customer
        # PII in the product (SMS bodies, call transcripts, recording URLs).
        RotationTarget(
            Conversation,
            ("workspace_phone", "contact_phone", "last_message_preview"),
            {
                "workspace_phone": "workspace_phone_hash",
                "contact_phone": "contact_phone_hash",
            },
        ),
        RotationTarget(ConversationBookingDraft, ("email", "confirmation_text")),
        RotationTarget(
            Message,
            (
                "body",
                "subject",
                "recipient_email",
                "sender_email",
                "recording_url",
                "transcript",
            ),
        ),
        RotationTarget(
            ServiceLocation,
            (
                "address_line1",
                "address_line2",
                "city",
                "state",
                "postal_code",
                "access_notes",
            ),
        ),
        RotationTarget(
            PhoneMessage,
            ("caller_name", "callback_number", "reason", "message_body"),
        ),
        RotationTarget(ReferralPartner, ("email", "phone")),
        RotationTarget(
            LeadProspect,
            ("email", "phone_number"),
            {"email": "email_hash", "phone_number": "phone_hash"},
        ),
        RotationTarget(GlobalOptOut, ("phone_number",), {"phone_number": "phone_hash"}),
        RotationTarget(DemoRequest, ("phone_number",), {"phone_number": "phone_hash"}),
        RotationTarget(CallerMemory, ("summary",)),
        RotationTarget(ContactAIMemory, ("summary",)),
        RotationTarget(ContactAIMemoryFact, ("value",)),
        RotationTarget(
            AgentTrainingExample,
            ("customer_message", "ai_response", "ideal_response", "operator_note"),
        ),
        RotationTarget(AttendanceEntry, ("note",)),
        RotationTarget(AttendanceEvent, ("reason",)),
    )


# ─── Startup validation ──────────────────────────────────────────────────────


def _type_name(column: Any) -> str:
    """Return a short, human-readable name for a column's SQLAlchemy type."""
    return type(column.type).__name__


def validate_targets(targets: Sequence[RotationTarget]) -> list[str]:
    """Return every declaration problem found in ``targets`` (empty == valid).

    Read straight off the SQLAlchemy mapper, so it stays correct as models are
    migrated onto :class:`EncryptedString` without this list being touched.

    A target is well-formed when:

    * the model is mapped and its table has a primary key (needed to write a row
      back without going through the ORM);
    * every declared column exists **and** is an :class:`EncryptedString` — a
      plain ``String``/``Text`` column means the data is stored in cleartext and
      rotating it is a no-op;
    * every declared ``*_hash`` sibling names a declared source column and
      exists as a real, non-encrypted column (a lookup hash must stay
      comparable, so it must not itself be encrypted).
    """
    problems: list[str] = []
    for target in targets:
        model_name = target.model.__name__
        mapper = sa.inspect(target.model, raiseerr=False)
        if mapper is None:
            problems.append(
                f"{model_name}: declared as a rotation target but is not a mapped model"
            )
            continue

        if not list(mapper.local_table.primary_key.columns):
            problems.append(
                f"{model_name}: table {mapper.local_table.name!r} has no primary key, "
                "so rotated rows cannot be written back"
            )

        if not target.columns:
            problems.append(f"{model_name}: declared as a rotation target with no columns")

        for name in target.columns:
            column = mapper.columns.get(name)
            if column is None:
                problems.append(
                    f"{model_name}.{name}: declared as a rotation target "
                    "but the model has no such column"
                )
            elif not isinstance(column.type, EncryptedString):
                problems.append(
                    f"{model_name}.{name}: declared as a rotation target but its column type is "
                    f"{_type_name(column)}, not EncryptedString — this data is stored in "
                    "cleartext and rotating the key would leave it untouched"
                )

        for source, hash_name in target.hash_columns.items():
            if source not in target.columns:
                problems.append(
                    f"{model_name}.{hash_name}: declared as the lookup-hash sibling of "
                    f"{source!r}, which is not a declared rotation column"
                )
            hash_column = mapper.columns.get(hash_name)
            if hash_column is None:
                problems.append(
                    f"{model_name}.{hash_name}: declared as the lookup-hash sibling of "
                    f"{source!r} but the model has no such column"
                )
            elif isinstance(hash_column.type, EncryptedString):
                problems.append(
                    f"{model_name}.{hash_name}: lookup-hash siblings must be stored in the clear "
                    "to remain comparable, but this column is an EncryptedString"
                )

    return problems


def undeclared_encrypted_columns(targets: Sequence[RotationTarget]) -> list[str]:
    """Return every mapped ``EncryptedString`` column missing from ``targets``.

    :func:`validate_targets` only proves the *declared* columns are really
    encrypted. It says nothing about the inverse, which is the more dangerous
    direction: a column that is encrypted but never declared is silently skipped
    by the rotation, and once the old key is discarded its data is unreadable
    forever — and the app raises :class:`InvalidToken` on every read of it, so
    the failure surfaces as a 500 on whatever page loads that row.

    Enumerated off the mapper registry rather than a hand-maintained list, so
    adding an ``EncryptedString`` column anywhere fails this check until the
    column is registered for rotation.
    """
    # Import every model module so the registry is complete: a model that no
    # other import path has touched would otherwise be invisible here, which is
    # exactly the blind spot this function exists to close.
    import app.models

    for module in pkgutil.iter_modules(app.models.__path__):
        importlib.import_module(f"app.models.{module.name}")

    from app.db.base import Base

    declared: set[tuple[str, str]] = set()
    for target in targets:
        mapper = sa.inspect(target.model, raiseerr=False)
        if mapper is None:
            continue
        for name in target.columns:
            column = mapper.columns.get(name)
            if column is not None:
                declared.add((mapper.local_table.name, column.name))
    # Rotated by _rotate_workspace_credentials rather than a RotationTarget.
    declared.add(("workspace_integrations", "credentials"))

    missing: list[str] = []
    for mapper in Base.registry.mappers:
        table = mapper.local_table.name if isinstance(mapper.local_table, sa.Table) else ""
        for column in mapper.columns:
            if not isinstance(column.type, EncryptedString):
                continue
            if (table, column.name) not in declared:
                missing.append(f"{mapper.class_.__name__}.{column.key} ({table}.{column.name})")
    return sorted(set(missing))


def ensure_full_coverage(targets: Sequence[RotationTarget]) -> None:
    """Abort when any encrypted column in the schema is missing from ``targets``.

    Separate from :func:`ensure_targets_valid` because this is a property of the
    canonical :func:`rotation_targets` list against the whole mapper registry,
    not of an arbitrary list of targets.

    Raises :class:`ScriptAbortError` carrying :data:`EXIT_FAILURE`, before a
    single row is read.
    """
    undeclared = undeclared_encrypted_columns(targets)
    if not undeclared:
        return

    listed = "\n".join(f"   ✗ {column}" for column in undeclared)
    print(f"\n{_RULE}\n RESULT: FAIL — rotation aborted before any data was touched\n{_RULE}")
    raise ScriptAbortError(
        f"REFUSING TO ROTATE — {len(undeclared)} encrypted column(s) are not "
        f"declared for rotation:\n{listed}\n"
        "   Each column above is encrypted at rest but would be skipped by this\n"
        "   pass, leaving it readable only under the key you are discarding.\n"
        "   Add it to rotation_targets() (with its *_hash sibling, if any) and\n"
        "   re-run. Nothing was read or written.",
        exit_code=EXIT_FAILURE,
    )


def ensure_targets_valid(targets: Sequence[RotationTarget]) -> None:
    """Abort the run when any declared target is misdeclared.

    Hard startup check: raises :class:`ScriptAbortError` carrying
    :data:`EXIT_FAILURE` so the process exits non-zero and CI cannot read the
    run as a success.
    """
    problems = validate_targets(targets)
    if not problems:
        return

    detail = "\n".join(f"   ✗ {problem}" for problem in problems)
    message = (
        f"REFUSING TO ROTATE — {len(problems)} misdeclared rotation "
        f"target(s):\n{detail}\n"
        "   Each column above is listed for re-encryption but is not encrypted at rest.\n"
        "   Migrate the model to EncryptedString() + LookupHash() (see contact.py) and\n"
        "   re-run. Nothing was read or written."
    )
    print(f"\n{_RULE}\n RESULT: FAIL — rotation aborted before any data was touched\n{_RULE}")
    print(message)
    print(f"{_RULE}\n")
    raise ScriptAbortError(message, exit_code=EXIT_FAILURE)


# ─── Per-table results + overall report ──────────────────────────────────────


@dataclass(slots=True, frozen=True)
class RotationStats:
    """Row counts for one rotated table.

    ``skipped_invalid`` counts *rows*, not columns, so it is directly
    comparable with ``scanned``.
    """

    table: str
    scanned: int
    rotated: int
    skipped_invalid: int
    absent: bool = False
    """The table is declared but does not exist in this database.

    A model whose migration has not been applied to this environment has no rows
    to rotate, so this is not a failure — but it must be reported distinctly, or
    it renders identically to a genuinely empty table and an operator cannot
    tell "nothing to do" apart from "never looked".
    """

    @property
    def failed(self) -> bool:
        """Return whether rows needed rotation and nothing was re-encrypted.

        This is the silent-failure case: the table was processed, every row was
        skipped, and the data is still sitting under the old key.
        """
        return self.skipped_invalid > 0 and self.rotated == 0

    @property
    def degraded(self) -> bool:
        """Return whether some rows rotated but others could not be read."""
        return self.skipped_invalid > 0 and self.rotated > 0

    @property
    def status(self) -> str:
        """Return the one-word per-table verdict shown in the summary."""
        if self.failed:
            return "FAIL"
        if self.degraded:
            return "PARTIAL"
        if self.absent:
            return "absent"
        return "ok"


@dataclass(slots=True, frozen=True)
class RotationReport:
    """Every table's result plus the overall pass/fail verdict."""

    stats: tuple[RotationStats, ...]
    dry_run: bool = False

    @property
    def failed_tables(self) -> tuple[RotationStats, ...]:
        """Return tables where nothing at all was re-encrypted."""
        return tuple(s for s in self.stats if s.failed)

    @property
    def degraded_tables(self) -> tuple[RotationStats, ...]:
        """Return tables that rotated but left some rows behind."""
        return tuple(s for s in self.stats if s.degraded)

    @property
    def total_scanned(self) -> int:
        """Return the number of rows examined across all tables."""
        return sum(s.scanned for s in self.stats)

    @property
    def total_rotated(self) -> int:
        """Return the number of rows re-encrypted across all tables."""
        return sum(s.rotated for s in self.stats)

    @property
    def total_skipped(self) -> int:
        """Return the number of rows skipped across all tables."""
        return sum(s.skipped_invalid for s in self.stats)

    @property
    def passed(self) -> bool:
        """Return whether every table completed without skipping a row."""
        return not self.failed_tables and not self.degraded_tables

    @property
    def exit_code(self) -> int:
        """Return the process exit code implied by this report."""
        return EXIT_OK if self.passed else EXIT_FAILURE

    def render(self) -> str:
        """Render the operator-facing summary block.

        Per-table ``scanned / re-encrypted / skipped`` counts followed by a
        single unambiguous PASS/FAIL line, so a no-op run cannot be mistaken for
        a successful rotation in CI output.
        """
        suffix = " (DRY RUN — nothing was committed)" if self.dry_run else ""
        width = max([len(s.table) for s in self.stats] + [len("TOTAL")])
        lines = [
            _RULE,
            f" ENCRYPTION KEY ROTATION — SUMMARY{suffix}",
            _RULE,
            f" {'table':<{width}}  {'scanned':>9}  {'re-encrypted':>12}  {'skipped':>9}   status",
        ]
        for s in self.stats:
            lines.append(
                f" {s.table:<{width}}  {s.scanned:>9}  {s.rotated:>12}  "
                f"{s.skipped_invalid:>9}   {s.status}"
            )
        lines.append(_RULE)
        lines.append(
            f" {'TOTAL':<{width}}  {self.total_scanned:>9}  {self.total_rotated:>12}  "
            f"{self.total_skipped:>9}"
        )

        if self.passed:
            verdict = " RESULT: PASS — every table re-encrypted cleanly under the new key"
            if self.dry_run:
                verdict += "\n         (dry run: rolled back, re-run without --dry-run to commit)"
            lines.append(verdict)
        else:
            lines.append(" RESULT: FAIL — the key rotation did NOT complete")
            for s in self.failed_tables:
                lines.append(
                    f"   ✗ {s.table}: 0 of {s.scanned} scanned rows re-encrypted; "
                    f"{s.skipped_invalid} could not be decrypted under either key"
                )
            for s in self.degraded_tables:
                lines.append(
                    f"   ! {s.table}: {s.rotated} of {s.scanned} scanned rows re-encrypted; "
                    f"{s.skipped_invalid} left behind"
                )
            lines.append(
                "   The rows above are STILL ENCRYPTED UNDER THE OLD KEY. Do not discard\n"
                "   OLD_ENCRYPTION_KEY until this run reports PASS."
            )
        lines.append(_RULE)
        return "\n".join(lines)


class _DryRunRollbackError(Exception):
    """Sentinel raised in --dry-run mode to roll back the transaction."""

    def __init__(self, stats: list[RotationStats]) -> None:
        super().__init__("dry-run rollback")
        self.stats = stats


# ─── Crypto helpers ──────────────────────────────────────────────────────────


def _old_fernet() -> Fernet:
    secret = os.environ.get("OLD_ENCRYPTION_KEY")
    if not secret:
        raise ScriptAbortError(
            "OLD_ENCRYPTION_KEY env var not set. Export the *previous* "
            "secret (the one currently used to encrypt the data on disk) "
            "before running this script."
        )
    return Fernet(_derive_fernet_key(secret))


def _lookup_hash_for(column: str) -> Callable[[str], str]:
    """Return the live app hasher matching a source column.

    ``hash_value`` / ``hash_phone`` both key off the *current*
    ``settings.encryption_key`` (the new key, set before this script runs), so
    re-deriving through them keeps every ``*_hash`` sibling aligned with how the
    running app resolves lookups. Phone columns normalise digits first, so any
    column whose name mentions a phone gets :func:`hash_phone`.
    """
    if "phone" in column:
        return hash_phone
    return hash_value


# ─── Rotation ────────────────────────────────────────────────────────────────


async def _rotate_string_columns(
    session: AsyncSession,
    *,
    target: RotationTarget,
    old_fernet: Fernet,
    new_fernet: Fernet,
) -> RotationStats:
    """Rotate one model's ``EncryptedString`` columns + their ``LookupHash`` siblings."""
    mapper = sa.inspect(target.model)
    table = mapper.local_table
    pk_columns = tuple(table.primary_key.columns)
    source_columns = tuple(mapper.columns[name] for name in target.columns)
    # Raw ciphertext only: EncryptedString would try (and fail) to decrypt every
    # old-key row during result processing, making them unloadable.
    raw_columns = [
        sa.type_coerce(column, sa.Text()).label(f"ct_{index}")
        for index, column in enumerate(source_columns)
    ]

    scanned = rotated = skipped_rows = 0
    pk_count = len(pk_columns)
    rows = (await session.execute(sa.select(*pk_columns, *raw_columns))).all()

    for row in rows:
        scanned += 1
        pk_values = row[:pk_count]
        updates: dict[Any, Any] = {}
        row_skipped = False

        for name, column, ciphertext in zip(
            target.columns, source_columns, row[pk_count:], strict=True
        ):
            if ciphertext is None:
                continue
            try:
                new_fernet.decrypt(ciphertext.encode())
                continue  # already on the new key — idempotent re-run
            except InvalidToken:
                pass
            try:
                plaintext = old_fernet.decrypt(ciphertext.encode()).decode()
            except InvalidToken:
                row_skipped = True
                logger.warning(
                    "skip %s.%s=%s col=%s: ciphertext invalid under both keys",
                    target.label,
                    "/".join(c.name for c in pk_columns),
                    "/".join(str(v) for v in pk_values),
                    name,
                )
                continue
            updates[column] = sa.type_coerce(
                new_fernet.encrypt(plaintext.encode()).decode(), sa.Text()
            )
            hash_name = target.hash_columns.get(name)
            if hash_name is not None:
                updates[mapper.columns[hash_name]] = _lookup_hash_for(name)(plaintext)

        if row_skipped:
            skipped_rows += 1
        if updates:
            await session.execute(
                sa.update(table)
                .where(*(col == val for col, val in zip(pk_columns, pk_values, strict=True)))
                .values(updates)
            )
            rotated += 1

    await session.flush()
    return RotationStats(
        table=target.label,
        scanned=scanned,
        rotated=rotated,
        skipped_invalid=skipped_rows,
    )


async def _rotate_workspace_credentials(
    session: AsyncSession, *, old_fernet: Fernet
) -> RotationStats:
    """Rotate the hand-encrypted JSON credential blob on ``WorkspaceIntegration``."""
    from app.models.workspace import WorkspaceIntegration

    scanned = rotated = invalid = 0
    result = await session.execute(select(WorkspaceIntegration))
    for ws in result.scalars().all():
        scanned += 1
        ct = ws.encrypted_credentials
        if not ct:
            continue
        try:
            decrypt_json(ct)
            continue  # already on the new key
        except InvalidToken:
            pass
        try:
            raw = old_fernet.decrypt(ct.encode()).decode()
            plaintext_dict = json.loads(raw)
        except (InvalidToken, json.JSONDecodeError):
            invalid += 1
            logger.warning("skip workspace.id=%s: credentials invalid under both keys", ws.id)
            continue
        ws.encrypted_credentials = encrypt_json(plaintext_dict)
        rotated += 1

    await session.flush()
    return RotationStats(
        table="workspace_integrations.credentials",
        scanned=scanned,
        rotated=rotated,
        skipped_invalid=invalid,
    )


async def _existing_tables(session: AsyncSession) -> set[str]:
    """Return the table names that actually exist in the target database.

    A declared model whose migration has not reached this environment would
    otherwise abort the whole pass with ``UndefinedTableError`` and roll back
    every table rotated before it.
    """
    rows = await session.execute(
        sa.text("select table_name from information_schema.tables where table_schema = 'public'")
    )
    return set(rows.scalars().all())


async def rotate_all(
    session: AsyncSession,
    *,
    targets: Sequence[RotationTarget],
    old_fernet: Fernet,
    new_fernet: Fernet,
) -> list[RotationStats]:
    """Rotate every declared target plus the workspace credential blobs."""
    all_stats: list[RotationStats] = []
    present = await _existing_tables(session)
    for target in targets:
        if target.label not in present:
            # Loud, and distinct from an empty table in the summary.
            stats = RotationStats(
                table=target.label, scanned=0, rotated=0, skipped_invalid=0, absent=True
            )
            all_stats.append(stats)
            _log_table(stats)
            continue
        stats = await _rotate_string_columns(
            session,
            target=target,
            old_fernet=old_fernet,
            new_fernet=new_fernet,
        )
        all_stats.append(stats)
        _log_table(stats)

    ws_stats = await _rotate_workspace_credentials(session, old_fernet=old_fernet)
    all_stats.append(ws_stats)
    _log_table(ws_stats)
    return all_stats


def _log_table(stats: RotationStats) -> None:
    """Emit one structured record per rotated table."""
    log_event(
        logger,
        logging.WARNING if stats.failed or stats.degraded or stats.absent else logging.INFO,
        "rotated table",
        table=stats.table,
        scanned=stats.scanned,
        rotated=stats.rotated,
        skipped=stats.skipped_invalid,
        status=stats.status,
    )


async def _run(ctx: ExecutionContext) -> int:
    # Hard startup check, before a single row is read: a target that is not
    # actually encrypted makes the whole pass a no-op.
    targets = rotation_targets()
    ensure_targets_valid(targets)
    # ... and the inverse check: nothing encrypted may be left out of the pass.
    ensure_full_coverage(targets)

    old_fernet = _old_fernet()

    # Sanity check: refuse if the two keys are identical — that means the
    # rotation hasn't actually happened yet.
    if os.environ["OLD_ENCRYPTION_KEY"] == settings.encryption_key:
        raise ScriptAbortError(
            "OLD_ENCRYPTION_KEY matches the current ENCRYPTION_KEY. "
            "Rotate the live secret first, then re-run this script."
        )

    ctx.announce("re-encrypt Fernet columns")
    ctx.confirm("re-encrypt all Fernet-encrypted columns")

    # Derived once: _derive_fernet_key runs 310k PBKDF2 iterations, which is
    # ruinous per-value on a large table.
    new_fernet = _get_fernet()

    started = time.monotonic()
    try:
        # The session factory is built here, from ``ctx.env``, rather than
        # imported: ``app.db.session`` freezes ``AsyncSessionLocal`` from the
        # ambient ``DATABASE_URL`` at import time, which is the developer's dev
        # database. Using it would rotate the *local* rows under a key named for
        # production and report success — the exact silent-wrong-database
        # failure ``script_sessionmaker`` exists to prevent.
        async with (
            script_sessionmaker(ctx) as session_factory,
            session_factory() as session,
            session.begin(),
        ):
            all_stats = await rotate_all(
                session,
                targets=targets,
                old_fernet=old_fernet,
                new_fernet=new_fernet,
            )
            if ctx.dry_run:
                log_event(
                    logger,
                    logging.WARNING,
                    "dry-run: rolling back, no writes committed",
                )
                raise _DryRunRollbackError(all_stats)
    except _DryRunRollbackError as rollback:
        all_stats = rollback.stats
        log_event(logger, logging.INFO, "dry-run complete; no changes persisted")

    report = RotationReport(stats=tuple(all_stats), dry_run=ctx.dry_run)
    print(report.render())
    log_event(
        logger,
        logging.INFO if report.passed else logging.ERROR,
        "done",
        elapsed_s=round(time.monotonic() - started, 2),
        scanned=report.total_scanned,
        rotated=report.total_rotated,
        skipped=report.total_skipped,
        result="pass" if report.passed else "fail",
    )
    return report.exit_code


def main() -> int:
    """Parse arguments and run the re-encryption pass."""
    ctx, _ = bootstrap(
        description=__doc__ or "Re-encrypt Fernet columns after ENCRYPTION_KEY rotation.",
        writes=True,
        logger_name="rotate",
    )
    return asyncio.run(_run(ctx))


if __name__ == "__main__":
    raise SystemExit(run(main))
