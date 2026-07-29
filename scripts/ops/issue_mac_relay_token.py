"""Mint a per-workspace Mac relay webhook token.

Since audit H-4 the relay's bearer token *is* its tenancy decision: it is bound
to one ``phone_numbers`` row, and the webhook scopes every lookup to that row's
workspace. A single global token used to grant message-write access into *any*
workspace, so one compromised customer-operated Mac compromised the platform.

Only the SHA-256 digest is stored (``phone_numbers.mac_relay_token_hash``),
mirroring ``api_keys.key_hash``. The plaintext is printed exactly once, here —
there is no way to recover it later, and re-running this command issues a new
token and invalidates the previous one for that number.

Usage
-----

    # Preview which number would be provisioned, without writing:
    uv run python scripts/ops/issue_mac_relay_token.py --env local \\
        --number +15125550123 --dry-run

    # Issue for local dev:
    uv run python scripts/ops/issue_mac_relay_token.py --env local \\
        --number +15125550123

    # Issue for production (typed confirmation required):
    uv run python scripts/ops/issue_mac_relay_token.py --env production \\
        --number +15125550123

    # Revoke without issuing a replacement:
    uv run python scripts/ops/issue_mac_relay_token.py --env production \\
        --number +15125550123 --revoke

Install the printed token on that Mac's relay daemon as its
``Authorization: Bearer <token>`` value.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

# --- harness bootstrap: make ``app`` importable regardless of CWD ------------
_HARNESS = next(
    p / "backend" / "scripts" / "_harness.py"
    for p in Path(__file__).resolve().parents
    if (p / "backend" / "scripts" / "_harness.py").is_file()
)
if str(_HARNESS.parent) not in sys.path:
    sys.path.insert(0, str(_HARNESS.parent))

from _harness import (  # noqa: E402
    EXIT_FAILURE,
    EXIT_OK,
    ExecutionContext,
    ScriptAbortError,
    bootstrap,
    log_event,
    run,
)


def _configure(parser: argparse.ArgumentParser) -> None:
    """Add the number selector and the revoke switch."""
    parser.add_argument(
        "--number",
        required=True,
        help="E.164 phone number of the relay-backed line, e.g. +15125550123",
    )
    parser.add_argument(
        "--revoke",
        action="store_true",
        help="Clear the stored digest without issuing a replacement.",
    )


async def _apply(ctx: ExecutionContext, args: argparse.Namespace) -> int:
    """Issue or revoke the relay token for one phone number."""
    from sqlalchemy import select

    from app.db.session import AsyncSessionLocal
    from app.models.phone_number import PhoneNumber
    from app.services.telephony.mac_relay_auth import (
        generate_mac_relay_token,
        hash_mac_relay_token,
    )

    logger = ctx.logger
    number = args.number.strip()

    async with AsyncSessionLocal() as db:
        record = (
            await db.execute(select(PhoneNumber).where(PhoneNumber.phone_number == number))
        ).scalar_one_or_none()

        if record is None:
            raise ScriptAbortError(
                f"no phone_numbers row matches {number!r}. "
                "Pass the number exactly as stored, in E.164 form."
            )

        if not record.is_active:
            # Resolution requires is_active, so a token here would never work.
            raise ScriptAbortError(
                f"{number} is inactive; activate it before issuing a relay token."
            )

        verb = "revoke" if args.revoke else "issue"
        log_event(
            logger,
            logging.INFO,
            f"would {verb} relay token" if ctx.dry_run else f"{verb} relay token",
            number=number,
            workspace_id=str(record.workspace_id),
            phone_number_id=str(record.id),
            replaces_existing=bool(record.mac_relay_token_hash),
        )

        if ctx.dry_run:
            return EXIT_OK

        ctx.confirm(f"{verb} the Mac relay token for {number}")

        if args.revoke:
            record.mac_relay_token_hash = None
            await db.commit()
            log_event(logger, logging.INFO, "relay token revoked", number=number)
            return EXIT_OK

        token = generate_mac_relay_token()
        record.mac_relay_token_hash = hash_mac_relay_token(token)
        await db.commit()

        # Printed to stdout rather than logged: log sinks are exactly where a
        # credential should not end up.
        print("\n" + "=" * 72)
        print(f"  Mac relay token for {number}")
        print(f"  workspace: {record.workspace_id}")
        print("=" * 72)
        print(f"\n  {token}\n")
        print("  Shown ONCE — only its SHA-256 digest is stored. Install it as the")
        print("  relay daemon's Authorization: Bearer value. Re-running this command")
        print("  issues a new token and invalidates this one.")
        print("=" * 72 + "\n")
        return EXIT_OK


def main() -> int:
    """Entry point."""
    ctx, args = bootstrap(
        description="Issue or revoke a per-workspace Mac relay webhook token.",
        writes=True,
        logger_name="issue_mac_relay_token",
        configure=_configure,
    )
    try:
        return asyncio.run(_apply(ctx, args))
    except ScriptAbortError:
        raise
    except Exception:
        ctx.logger.exception("failed to issue Mac relay token")
        return EXIT_FAILURE


if __name__ == "__main__":
    raise SystemExit(run(main))
