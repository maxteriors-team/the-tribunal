"""Create/refresh the FB Perm Lighting Lead automation for a lead source.

Wires an event-based ``lead_created`` automation to a lead source so every
brand-new lead captured through that source is:

  1. tagged ``FB Perm Lighting Lead``; then
  2. sent a personalized intro SMS (phone normalized to E.164 by the worker,
     ``{first_name}`` falling back to "there").

The automation fires for the target lead source by its stable public key AND,
as a fallback, for any lead whose submission ``source_detail`` matches
``permholidaylights instant quote`` (OR semantics — see
``app.services.automations.events.lead_created_event_matches``). No ``fbclid``
or ``utm_source`` is required.

Idempotent: matched on (workspace, ``lead_created``,
``trigger_config.lead_source_public_key``); re-running updates the existing row
in place instead of creating duplicates.

Usage
-----

    # Preview against local without writing:
    uv run python scripts/ops/setup_lead_automation.py --env local --dry-run

    # Apply to local:
    uv run python scripts/ops/setup_lead_automation.py --env local

    # Apply to production (typed confirmation required):
    uv run python scripts/ops/setup_lead_automation.py --env production \
        --public-key ls_n2dSPTZe
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path
from typing import Any

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

# ── Defaults for the permholidaylights Facebook funnel ───────────────────────

DEFAULT_PUBLIC_KEY = "ls_n2dSPTZe"
DEFAULT_TAG = "FB Perm Lighting Lead"
DEFAULT_SOURCE_DETAIL = "permholidaylights instant quote"
DEFAULT_NAME = "FB Perm Lighting Lead — auto text"
DEFAULT_MESSAGE = (
    "Hi {first_name}, it's Max with Maxteriors — got your permanent roofline "
    "lighting estimate. Happy to answer any questions or get your free design "
    "consultation booked. When's a good time to reach you?"
)

TRIGGER_TYPE = "lead_created"


def _build_actions(tag: str, message: str) -> list[dict[str, Any]]:
    """Tag first (so an unsendable phone still gets tagged), then text."""
    return [
        {"type": "add_tag", "config": {"tag": tag}},
        {
            "type": "send_sms",
            "config": {"message": message, "fallbacks": {"first_name": "there"}},
        },
    ]


def _build_trigger_config(public_key: str, source_id: str, source_detail: str) -> dict[str, Any]:
    return {
        "lead_source_public_key": public_key,
        "lead_source_id": source_id,
        "source_detail": source_detail,
    }


async def _apply(ctx: ExecutionContext, args: argparse.Namespace) -> int:
    from sqlalchemy import select

    from app.db.session import AsyncSessionLocal
    from app.models.automation import Automation
    from app.models.lead_source import LeadSource

    logger = ctx.logger
    public_key: str = args.public_key
    tag: str = args.tag
    message: str = args.message
    source_detail: str = args.source_detail

    async with AsyncSessionLocal() as db:
        # 1) Resolve the lead source (and thus the workspace) by public key.
        source = (
            await db.execute(select(LeadSource).where(LeadSource.public_key == public_key))
        ).scalar_one_or_none()
        if source is None:
            log_event(
                logger,
                logging.ERROR,
                "lead source not found — nothing to wire",
                public_key=public_key,
            )
            return EXIT_FAILURE

        workspace_id = source.workspace_id
        log_event(
            logger,
            logging.INFO,
            "resolved lead source",
            public_key=public_key,
            lead_source_id=str(source.id),
            workspace_id=str(workspace_id),
            source_action=source.action,
        )

        # Warn about double-texting: if the source itself auto-texts/-calls on
        # capture, this automation would be a second outbound touch.
        if source.action in ("auto_text", "auto_call"):
            log_event(
                logger,
                logging.WARNING,
                "lead source has its own post-capture action — leads may get two "
                "outbound touches; set the source action to 'collect' so this "
                "automation owns messaging",
                source_action=source.action,
            )

        trigger_config = _build_trigger_config(public_key, str(source.id), source_detail)
        actions = _build_actions(tag, message)

        # 2) Upsert on (workspace, lead_created, trigger_config.public_key).
        existing = (
            await db.execute(
                select(Automation).where(
                    Automation.workspace_id == workspace_id,
                    Automation.trigger_type == TRIGGER_TYPE,
                    Automation.trigger_config["lead_source_public_key"].astext == public_key,
                )
            )
        ).scalar_one_or_none()

        verb = "update" if existing else "create"
        log_event(
            logger,
            logging.INFO,
            f"would {verb} automation" if ctx.dry_run else f"{verb} automation",
            name=args.name,
            trigger_type=TRIGGER_TYPE,
            tag=tag,
            source_detail=source_detail,
            actions=len(actions),
        )

        if ctx.dry_run:
            log_event(logger, logging.WARNING, "dry-run: no changes committed")
            return EXIT_OK

        ctx.confirm(f"{verb} the '{args.name}' automation")

        if existing is not None:
            existing.name = args.name
            existing.description = args.description
            existing.trigger_type = TRIGGER_TYPE
            existing.trigger_config = trigger_config
            existing.actions = actions
            existing.is_active = True
            automation = existing
        else:
            automation = Automation(
                workspace_id=workspace_id,
                name=args.name,
                description=args.description,
                trigger_type=TRIGGER_TYPE,
                trigger_config=trigger_config,
                actions=actions,
                is_active=True,
            )
            db.add(automation)

        await db.commit()
        await db.refresh(automation)

        log_event(
            logger,
            logging.INFO,
            "automation ready",
            automation_id=str(automation.id),
            workspace_id=str(workspace_id),
            is_active=automation.is_active,
        )
        return EXIT_OK


def _configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--public-key",
        default=DEFAULT_PUBLIC_KEY,
        help=f"Lead source public key to wire (default: {DEFAULT_PUBLIC_KEY}).",
    )
    parser.add_argument(
        "--tag",
        default=DEFAULT_TAG,
        help=f"Tag applied to each matching lead (default: {DEFAULT_TAG!r}).",
    )
    parser.add_argument(
        "--source-detail",
        default=DEFAULT_SOURCE_DETAIL,
        help="Fallback source_detail to match (case-insensitive).",
    )
    parser.add_argument("--name", default=DEFAULT_NAME, help="Automation name.")
    parser.add_argument("--description", default=None, help="Automation description.")
    parser.add_argument("--message", default=DEFAULT_MESSAGE, help="SMS body template.")


def main() -> int:
    ctx, args = bootstrap(
        description="Create/refresh the FB Perm Lighting Lead automation for a lead source.",
        logger_name="setup_lead_automation",
        configure=_configure,
    )
    try:
        return asyncio.run(_apply(ctx, args))
    except ScriptAbortError:
        raise
    except Exception:
        ctx.logger.exception("failed to set up lead automation")
        return EXIT_FAILURE


if __name__ == "__main__":
    raise SystemExit(run(main))
