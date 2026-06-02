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

* Rows whose ciphertext already decrypts under the *new* key are left alone
  (idempotent — safe to re-run).
* Rows whose ciphertext fails under both keys are logged and skipped, never
  overwritten with garbage.
* ``LookupHash`` columns are re-derived from the decrypted plaintext so the
  ``*_hash`` siblings stay aligned with the new key.
* ``--dry-run`` decrypts and re-encrypts in memory, then rolls back.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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
    _derive_fernet_key,
    _get_fernet,
    decrypt_json,
    encrypt_json,
    hash_phone,
    hash_value,
)
from app.db.session import AsyncSessionLocal  # noqa: E402
from scripts._harness import (  # noqa: E402
    EXIT_FAILURE,
    EXIT_OK,
    ExecutionContext,
    ScriptAbortError,
    bootstrap,
    log_event,
    run,
)

logger = logging.getLogger("rotate")


def _encrypt_value(plaintext: str) -> str:
    """Encrypt a string under the *current* (new) Fernet key."""
    return _get_fernet().encrypt(plaintext.encode()).decode()


def _decrypt_value(token: str) -> str:
    """Decrypt a Fernet token under the *current* (new) key.

    Raises :class:`InvalidToken` when the token was not produced by the new key,
    which the rotation loop uses to detect rows still on the old key.
    """
    return _get_fernet().decrypt(token.encode()).decode()


@dataclass(slots=True, frozen=True)
class RotationStats:
    table: str
    scanned: int
    rotated: int
    skipped_invalid: int


class _DryRunRollbackError(Exception):
    """Sentinel raised in --dry-run mode to roll back the transaction."""


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
    running app resolves lookups.
    """
    if column == "phone_number":
        return hash_phone
    return hash_value


async def _rotate_string_columns(
    session: AsyncSession,
    *,
    model: type[Any],
    columns: tuple[str, ...],
    hash_columns: dict[str, str],
    old_fernet: Fernet,
) -> RotationStats:
    """Rotate one model's ``EncryptedString`` columns + their ``LookupHash`` siblings."""
    scanned = rotated = invalid = 0
    table_name: str = getattr(model, "__tablename__", model.__name__)

    result = await session.execute(select(model))
    for row in result.scalars().all():
        scanned += 1
        row_changed = False
        for col in columns:
            ct = getattr(row, col)
            if ct is None:
                continue
            # Already encrypted under the new key?
            try:
                _decrypt_value(ct)
                continue
            except InvalidToken:
                pass
            # Decrypt under the old key.
            try:
                plaintext = old_fernet.decrypt(ct.encode()).decode()
            except InvalidToken:
                invalid += 1
                logger.warning(
                    "skip %s.id=%s col=%s: ciphertext invalid under both keys",
                    table_name,
                    getattr(row, "id", "?"),
                    col,
                )
                continue
            setattr(row, col, _encrypt_value(plaintext))
            hash_col = hash_columns.get(col)
            if hash_col is not None:
                setattr(row, hash_col, _lookup_hash_for(col)(plaintext))
            row_changed = True
        if row_changed:
            rotated += 1

    await session.flush()
    return RotationStats(
        table=table_name,
        scanned=scanned,
        rotated=rotated,
        skipped_invalid=invalid,
    )


async def _rotate_workspace_credentials(
    session: AsyncSession, *, old_fernet: Fernet
) -> RotationStats:
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


async def _run(ctx: ExecutionContext) -> int:
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

    from app.models.contact import Contact
    from app.models.human_profile import HumanProfile
    from app.models.lead_magnet_lead import LeadMagnetLead
    from app.models.link_click import LinkClick
    from app.models.user import User

    targets: list[tuple[type[Any], tuple[str, ...], dict[str, str]]] = [
        (
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
        (
            User,
            ("email", "phone_number"),
            {"email": "email_hash", "phone_number": "phone_hash"},
        ),
        (
            HumanProfile,
            ("email", "phone_number"),
            {"email": "email_hash", "phone_number": "phone_hash"},
        ),
        (
            LeadMagnetLead,
            ("email", "phone_number", "name"),
            {"email": "email_hash", "phone_number": "phone_hash"},
        ),
        (LinkClick, ("ip_address",), {}),
    ]

    started = time.monotonic()
    all_stats: list[RotationStats] = []
    try:
        async with AsyncSessionLocal() as session, session.begin():
            for model, cols, hash_cols in targets:
                stats = await _rotate_string_columns(
                    session,
                    model=model,
                    columns=cols,
                    hash_columns=hash_cols,
                    old_fernet=old_fernet,
                )
                all_stats.append(stats)
                log_event(
                    logger,
                    logging.INFO,
                    "rotated table",
                    table=stats.table,
                    scanned=stats.scanned,
                    rotated=stats.rotated,
                    invalid=stats.skipped_invalid,
                )
            ws_stats = await _rotate_workspace_credentials(session, old_fernet=old_fernet)
            all_stats.append(ws_stats)
            log_event(
                logger,
                logging.INFO,
                "rotated table",
                table=ws_stats.table,
                scanned=ws_stats.scanned,
                rotated=ws_stats.rotated,
                invalid=ws_stats.skipped_invalid,
            )
            if ctx.dry_run:
                log_event(logger, logging.WARNING, "dry-run: rolling back, no writes committed")
                raise _DryRunRollbackError
    except _DryRunRollbackError:
        log_event(logger, logging.INFO, "dry-run complete; no changes persisted")
        return EXIT_OK

    elapsed = time.monotonic() - started
    total_rotated = sum(s.rotated for s in all_stats)
    total_invalid = sum(s.skipped_invalid for s in all_stats)
    log_event(
        logger,
        logging.INFO,
        "done",
        elapsed_s=round(elapsed, 2),
        rotated=total_rotated,
        invalid=total_invalid,
    )
    return EXIT_FAILURE if total_invalid else EXIT_OK


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
