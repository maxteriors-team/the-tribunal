#!/usr/bin/env python3
"""Mint a per-workspace Mac relay webhook token (audit finding H-4).

The relay webhook authenticates each host against one ``phone_numbers`` row, and
that row's ``workspace_id`` — not the request body — decides the tenant. This
script issues the credential for one such row.

Only the SHA-256 digest is persisted (``phone_numbers.mac_relay_token_hash``),
mirroring ``api_keys.key_hash``. The plaintext is printed **exactly once**, here;
it is unrecoverable afterwards, so paste it straight into the relay host's
config. Losing it means rotating, not reading.

Usage
-----

    # By phone number id:
    cd backend && uv run python scripts/ops/issue_mac_relay_token.py \
        --env local --phone-number-id <uuid>

    # By E.164 number (or the row's mac_relay_sender_id):
    cd backend && uv run python scripts/ops/issue_mac_relay_token.py \
        --env local --number +12125550101

    # Preview without writing:
    cd backend && uv run python scripts/ops/issue_mac_relay_token.py \
        --env local --number +12125550101 --dry-run

Issuing over an existing token revokes the old one, which stops the relay host
still using it — so that requires an explicit ``--rotate``.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import uuid
from pathlib import Path

# --- harness bootstrap: locate ``backend/`` so ``app`` + ``scripts`` import ----
_BACKEND_DIR = next(
    p / "backend"
    for p in Path(__file__).resolve().parents
    if (p / "backend" / "scripts" / "_harness.py").is_file()
)
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from scripts._harness import (  # noqa: E402
    EXIT_FAILURE,
    EXIT_OK,
    EXIT_USAGE,
    ExecutionContext,
    bootstrap,
    log_event,
    run,
)

logger = logging.getLogger("mac-relay-token")


def _configure(parser: argparse.ArgumentParser) -> None:
    """Add the row selector and the rotation guard."""
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument(
        "--phone-number-id",
        metavar="UUID",
        help="The phone_numbers.id to issue a relay token for.",
    )
    target.add_argument(
        "--number",
        metavar="E164",
        help="The E.164 number (or mac_relay_sender_id) to issue a relay token for.",
    )
    parser.add_argument(
        "--rotate",
        action="store_true",
        help="Replace an existing token. The current one stops working immediately.",
    )


async def _run(ctx: ExecutionContext, args: argparse.Namespace) -> int:
    """Issue the token and print the plaintext once."""
    from sqlalchemy import or_, select

    from app.db.session import AsyncSessionLocal
    from app.models.phone_number import PhoneNumber
    from app.services.telephony.mac_relay_auth import (
        generate_mac_relay_token,
        hash_mac_relay_token,
    )
    from app.utils.phone import normalize_phone_safe

    selector = args.phone_number_id or args.number
    ctx.announce("issue Mac relay token", target=selector)

    async with AsyncSessionLocal() as db:
        if args.phone_number_id:
            try:
                row_id = uuid.UUID(args.phone_number_id)
            except ValueError:
                log_event(logger, logging.ERROR, "invalid UUID", value=args.phone_number_id)
                return EXIT_USAGE
            phone = await db.get(PhoneNumber, row_id)
        else:
            candidates = [args.number]
            normalized = normalize_phone_safe(args.number)
            if normalized and normalized not in candidates:
                candidates.append(normalized)
            phone = (
                await db.execute(
                    select(PhoneNumber)
                    .where(
                        or_(
                            PhoneNumber.phone_number.in_(candidates),
                            PhoneNumber.mac_relay_sender_id.in_(candidates),
                        )
                    )
                    .limit(1)
                )
            ).scalar_one_or_none()

        if phone is None:
            log_event(logger, logging.ERROR, "phone number not found", target=selector)
            return EXIT_FAILURE

        if phone.mac_relay_token_hash and not args.rotate:
            log_event(
                logger,
                logging.ERROR,
                "this number already has a relay token; pass --rotate to replace it",
                phone_number_id=str(phone.id),
            )
            return EXIT_USAGE

        if not phone.is_active:
            # resolve_mac_relay_credential() requires is_active, so a token here
            # would authenticate nothing.
            log_event(
                logger,
                logging.ERROR,
                "phone number is inactive; its relay token would never resolve",
                phone_number_id=str(phone.id),
            )
            return EXIT_FAILURE

        ctx.confirm(f"issue a Mac relay token for {phone.phone_number}")

        if ctx.dry_run:
            log_event(
                logger,
                logging.INFO,
                "dry-run: would issue a relay token",
                phone_number_id=str(phone.id),
                workspace_id=str(phone.workspace_id),
                rotating=bool(phone.mac_relay_token_hash),
            )
            return EXIT_OK

        token = generate_mac_relay_token()
        phone.mac_relay_token_hash = hash_mac_relay_token(token)
        await db.commit()

        log_event(
            logger,
            logging.INFO,
            "relay token issued",
            phone_number_id=str(phone.id),
            workspace_id=str(phone.workspace_id),
            rotated=bool(args.rotate),
        )
        _print_token(phone.phone_number, token)

    return EXIT_OK


def _print_token(phone_number: str, token: str) -> None:
    """Show the plaintext once, to stdout, clearly marked as unrecoverable."""
    print()
    print(f"  Mac relay token for {phone_number}")
    print(f"    {token}")
    print()
    print("  Shown once — only its SHA-256 digest is stored. Copy it into the")
    print("  relay host's config now; recovering it later is impossible.")
    print()


def main() -> int:
    """Parse arguments and issue the token."""
    ctx, args = bootstrap(
        description=__doc__ or "Issue a per-workspace Mac relay token.",
        writes=True,
        logger_name="mac-relay-token",
        configure=_configure,
    )
    return asyncio.run(_run(ctx, args))


if __name__ == "__main__":
    raise SystemExit(run(main))
