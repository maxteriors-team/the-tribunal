"""Re-encrypt all Fernet-encrypted columns after an ``ENCRYPTION_KEY`` rotation.

Run this immediately after rotating ``ENCRYPTION_KEY`` in your environment.
The script holds the **old** key in-memory only for the duration of one pass:
it decrypts each row using the old key, then re-encrypts and writes back with
the new key (whatever ``settings.encryption_key`` currently resolves to).

Usage
-----

    OLD_ENCRYPTION_KEY="<previous secret>" \
        uv run python scripts/reencrypt_with_old_key.py [--dry-run]

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

import argparse
import asyncio
import hashlib
import json
import logging
import os
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# Make ``backend`` importable when invoked from the repo root.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_BACKEND_DIR = os.path.join(_REPO_ROOT, "backend")
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from app.core.config import settings  # noqa: E402
from app.core.encryption import (  # noqa: E402
    _derive_fernet_key,
    _derive_hash_key,
    decrypt_json,
    decrypt_value,
    encrypt_json,
    encrypt_value,
)
from app.db.session import AsyncSessionLocal  # noqa: E402

logger = logging.getLogger("rotate")


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
        raise SystemExit(
            "✗ OLD_ENCRYPTION_KEY env var not set. Export the *previous* "
            "secret (the one currently used to encrypt the data on disk) "
            "before running this script."
        )
    return Fernet(_derive_fernet_key(secret))


def _new_lookup_hash() -> Callable[[str], str]:
    """Return a closure that hashes plaintext under the *new* hash key."""
    new_hash_key = _derive_hash_key(settings.encryption_key)

    def _hash(value: str) -> str:
        return hashlib.blake2b(
            value.encode(), key=new_hash_key, digest_size=32
        ).hexdigest()

    return _hash


async def _rotate_string_columns(
    session: AsyncSession,
    *,
    model: type[Any],
    columns: tuple[str, ...],
    hash_columns: dict[str, str],
    old_fernet: Fernet,
) -> RotationStats:
    """Rotate one model's ``EncryptedString`` columns + their ``LookupHash`` siblings."""
    lookup_hash = _new_lookup_hash()
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
                decrypt_value(ct)
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
            setattr(row, col, encrypt_value(plaintext))
            hash_col = hash_columns.get(col)
            if hash_col is not None:
                setattr(row, hash_col, lookup_hash(plaintext))
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
            logger.warning(
                "skip workspace.id=%s: credentials invalid under both keys", ws.id
            )
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


async def _run(dry_run: bool) -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    old_fernet = _old_fernet()

    # Sanity check: refuse if the two keys are identical — that means the
    # rotation hasn't actually happened yet.
    if os.environ["OLD_ENCRYPTION_KEY"] == settings.encryption_key:
        raise SystemExit(
            "✗ OLD_ENCRYPTION_KEY matches the current ENCRYPTION_KEY. "
            "Rotate the live secret first, then re-run this script."
        )

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
                logger.info(
                    "%-40s scanned=%d rotated=%d invalid=%d",
                    stats.table,
                    stats.scanned,
                    stats.rotated,
                    stats.skipped_invalid,
                )
            ws_stats = await _rotate_workspace_credentials(
                session, old_fernet=old_fernet
            )
            all_stats.append(ws_stats)
            logger.info(
                "%-40s scanned=%d rotated=%d invalid=%d",
                ws_stats.table,
                ws_stats.scanned,
                ws_stats.rotated,
                ws_stats.skipped_invalid,
            )
            if dry_run:
                logger.info("dry-run: rolling back, no writes committed")
                raise _DryRunRollbackError
    except _DryRunRollbackError:
        logger.info("dry-run complete; no changes persisted")
        return 0

    elapsed = time.monotonic() - started
    total_rotated = sum(s.rotated for s in all_stats)
    total_invalid = sum(s.skipped_invalid for s in all_stats)
    logger.info(
        "done in %.2fs — rotated=%d invalid=%d", elapsed, total_rotated, total_invalid
    )
    return 1 if total_invalid else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Decrypt + re-encrypt in memory and roll back the transaction.",
    )
    args = parser.parse_args()
    sys.exit(asyncio.run(_run(args.dry_run)))
