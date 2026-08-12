"""Create/refresh the Perm Light Lead automation for a lead source.

Wires an event-based ``lead_created`` automation to a lead source so every
brand-new lead captured through that source is:

  1. tagged ``Perm Light Lead`` and ``Facebook`` (what the operator sees and
     filters on in the contacts list); then
  2. sent a personalized intro SMS (phone normalized to E.164 by the worker,
     ``{first_name}`` falling back to "there").

It also sets the lead source's own ``source_type`` to ``facebook_ads``, which is
where structured attribution lives: every contact captured through the form
carries this source as its first/latest touch, so the ROI dashboard counts these
leads under "Facebook Ads" instead of "Other". Tags are the human label; the
channel is the number.

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
import uuid
from collections.abc import Iterable, Sequence
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
DEFAULT_TAGS = ("Perm Light Lead", "Facebook")
DEFAULT_SOURCE_DETAIL = "permholidaylights instant quote"
# Suffixed at runtime with what the automation actually does, so the name an
# operator reads in the dashboard never claims a text that was suppressed.
DEFAULT_NAME_BASE = "Perm Light Lead"
DEFAULT_MESSAGE = (
    "Hi {first_name}, it's Max with Maxteriors — got your permanent roofline "
    "lighting estimate. Happy to answer any questions or get your free design "
    "consultation booked. When's a good time to reach you?"
)

TRIGGER_TYPE = "lead_created"

# Channel this funnel's leads are attributed to. ``keep`` leaves whatever the
# lead source already has; any other value must be a ``LeadSourceType`` member.
DEFAULT_SOURCE_TYPE = "facebook_ads"
KEEP_SOURCE_TYPE = "keep"

# Post-capture actions on the lead source that already message the lead. When
# the source does its own outbound touch, adding ``send_sms`` here means every
# lead gets texted twice.
SELF_MESSAGING_SOURCE_ACTIONS = ("auto_text", "auto_call")

# ``--sms`` modes. ``auto`` is the safe default: include the SMS only when the
# lead source is not already messaging on capture.
SMS_AUTO = "auto"
SMS_ON = "on"
SMS_OFF = "off"
SMS_MODES = (SMS_AUTO, SMS_ON, SMS_OFF)


def _normalize_tags(tags: Iterable[str]) -> list[str]:
    """Trim, drop blanks, and de-duplicate while preserving operator order."""
    seen: dict[str, None] = {}
    for raw in tags:
        tag = str(raw).strip()
        if tag and tag.casefold() not in {k.casefold() for k in seen}:
            seen[tag] = None
    return list(seen)


def _build_actions(tags: Sequence[str], message: str, *, with_sms: bool) -> list[dict[str, Any]]:
    """Tag first (so an unsendable phone still gets tagged), then optionally text."""
    actions: list[dict[str, Any]] = [{"type": "add_tag", "config": {"tag": tag}} for tag in tags]
    if with_sms:
        actions.append(
            {
                "type": "send_sms",
                "config": {"message": message, "fallbacks": {"first_name": "there"}},
            }
        )
    return actions


def _resolve_sms(mode: str, source_action: str) -> tuple[bool, str]:
    """Decide whether the automation should send its own SMS.

    Returns ``(with_sms, reason)``. A lead source set to ``auto_text``/
    ``auto_call`` already messages every lead the moment the form posts, so in
    ``auto`` mode the automation stays tag-only rather than sending a second
    message to a real customer. ``on`` forces the SMS anyway (deliberate
    double-touch), ``off`` always suppresses it.
    """
    if mode == SMS_OFF:
        return False, "--sms off"
    if mode == SMS_ON:
        return True, "--sms on"
    if source_action in SELF_MESSAGING_SOURCE_ACTIONS:
        return False, f"lead source action is {source_action!r} and already messages the lead"
    return True, f"lead source action is {source_action!r} and does not message the lead"


def _build_trigger_config(public_key: str, source_id: str, source_detail: str) -> dict[str, Any]:
    return {
        "lead_source_public_key": public_key,
        "lead_source_id": source_id,
        "source_detail": source_detail,
    }


def _parse_labels(args: argparse.Namespace, logger: logging.Logger) -> tuple[list[str], Any] | None:
    """Resolve the tags and channel from CLI input before any DB work.

    Returns ``(tags, channel)`` where ``channel`` is a ``LeadSourceType`` or
    ``None`` to leave the lead source's channel alone. Returns ``None`` (after
    logging) when the input is unusable, so a typo fails before the confirm
    prompt instead of writing a config nothing dispatches on.
    """
    from app.models.lead_source import LeadSourceType

    tags = _normalize_tags(args.tag or DEFAULT_TAGS)
    if not tags:
        log_event(logger, logging.ERROR, "--tag produced no usable tag names")
        return None

    if args.source_type == KEEP_SOURCE_TYPE:
        return tags, None
    try:
        return tags, LeadSourceType(args.source_type)
    except ValueError:
        log_event(
            logger,
            logging.ERROR,
            "unknown --source-type",
            value=args.source_type,
            valid=",".join([*(m.value for m in LeadSourceType), KEEP_SOURCE_TYPE]),
        )
        return None


def _log_source_plan(
    ctx: ExecutionContext,
    source: Any,
    *,
    want_channel: Any,
    public_key: str,
) -> None:
    """Report what the run found and what it intends to change on the source.

    Split out of :func:`_apply` so the decision trail (channel move, whether the
    automation will message on top of a source that already does) is one
    readable block instead of noise inside the write path.
    """
    logger = ctx.logger
    current_channel = getattr(source.source_type, "value", source.source_type)
    log_event(
        logger,
        logging.INFO,
        "resolved lead source",
        public_key=public_key,
        lead_source_id=str(source.id),
        workspace_id=str(source.workspace_id),
        source_action=source.action,
        source_type=current_channel,
    )

    # Structured attribution: every contact captured here points at this source
    # as first/latest touch, so the channel set on the source is what the ROI
    # dashboard reports for these leads.
    if want_channel is not None and source.source_type != want_channel:
        log_event(
            logger,
            logging.INFO,
            "would set lead source channel" if ctx.dry_run else "set lead source channel",
            from_source_type=current_channel,
            to_source_type=want_channel.value,
        )


async def _apply(ctx: ExecutionContext, args: argparse.Namespace) -> int:
    from sqlalchemy import select

    from app.db.session import AsyncSessionLocal
    from app.models.automation import Automation
    from app.models.lead_source import LeadSource

    logger = ctx.logger
    public_key: str = args.public_key
    message: str = args.message
    source_detail: str = args.source_detail

    parsed = _parse_labels(args, logger)
    if parsed is None:
        return EXIT_FAILURE
    tags, want_channel = parsed

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
        _log_source_plan(ctx, source, want_channel=want_channel, public_key=public_key)
        channel_change = want_channel is not None and source.source_type != want_channel

        # Double-texting guard: if the source itself auto-texts/-calls on
        # capture, an SMS action here is a second outbound touch to a real
        # customer. Default (``--sms auto``) keeps the automation tag-only.
        with_sms, sms_reason = _resolve_sms(args.sms, source.action)
        log_event(
            logger,
            logging.INFO if with_sms else logging.WARNING,
            "automation will send its own SMS" if with_sms else "automation is tag-only (no SMS)",
            reason=sms_reason,
            source_action=source.action,
        )

        name = args.name or f"{DEFAULT_NAME_BASE} — {'tag + auto text' if with_sms else 'tag only'}"
        trigger_config = _build_trigger_config(public_key, str(source.id), source_detail)
        actions = _build_actions(tags, message, with_sms=with_sms)

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
            name=name,
            trigger_type=TRIGGER_TYPE,
            tags=",".join(tags),
            source_detail=source_detail,
            actions=len(actions),
        )

        if ctx.dry_run:
            if args.backfill:
                await _backfill_tags(
                    ctx, db, workspace_id=workspace_id, source_id=source.id, tags=tags
                )
            log_event(logger, logging.WARNING, "dry-run: no changes committed")
            return EXIT_OK

        ctx.confirm(f"{verb} the '{name}' automation")

        if channel_change and want_channel is not None:
            source.source_type = want_channel

        if existing is not None:
            existing.name = name
            existing.description = args.description
            existing.trigger_type = TRIGGER_TYPE
            existing.trigger_config = trigger_config
            existing.actions = actions
            existing.is_active = True
            automation = existing
        else:
            automation = Automation(
                workspace_id=workspace_id,
                name=name,
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
            tags=",".join(tags),
            sends_sms=with_sms,
            source_type=getattr(source.source_type, "value", source.source_type),
        )

        if args.backfill:
            await _backfill_tags(ctx, db, workspace_id=workspace_id, source_id=source.id, tags=tags)
        return EXIT_OK


async def _backfill_tags(
    ctx: ExecutionContext,
    db: Any,
    *,
    workspace_id: uuid.UUID,
    source_id: uuid.UUID,
    tags: Sequence[str],
) -> None:
    """Apply the same tags to leads this source already captured.

    The automation only fires for leads created after it exists, so without this
    the funnel's history stays unlabelled and any tag-filtered list or campaign
    silently misses every past lead. Contacts are selected by
    ``first_touch_lead_source_id`` (the structured attribution the form writes),
    not by a notes substring, so the selector matches what the ROI dashboard
    already counts for this source.

    Uses the same idempotent ``TagService.add_tag_to_contact`` call the worker's
    ``add_tag`` action uses, so a re-run adds nothing and backfilled rows are
    indistinguishable from live ones.
    """
    from sqlalchemy import select

    from app.models.contact import Contact
    from app.services.tags.tag_service import TagService

    logger = ctx.logger
    contact_ids = list(
        (
            await db.execute(
                select(Contact.id).where(
                    Contact.workspace_id == workspace_id,
                    Contact.first_touch_lead_source_id == source_id,
                )
            )
        )
        .scalars()
        .all()
    )

    if not contact_ids:
        log_event(logger, logging.INFO, "backfill: no existing leads for this source")
        return

    log_event(
        logger,
        logging.INFO,
        "backfill: would tag existing leads" if ctx.dry_run else "backfill: tagging existing leads",
        contacts=len(contact_ids),
        tags=",".join(tags),
    )
    if ctx.dry_run:
        return

    service = TagService(db)
    for contact_id in contact_ids:
        for tag in tags:
            await service.add_tag_to_contact(
                workspace_id=workspace_id,
                contact_id=contact_id,
                name=tag,
            )
    await db.commit()

    log_event(
        logger,
        logging.INFO,
        "backfill complete",
        contacts=len(contact_ids),
        tags=",".join(tags),
    )


def _configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--public-key",
        default=DEFAULT_PUBLIC_KEY,
        help=f"Lead source public key to wire (default: {DEFAULT_PUBLIC_KEY}).",
    )
    parser.add_argument(
        "--tag",
        action="append",
        default=None,
        help=(
            "Tag applied to each matching lead; repeat for several "
            f"(default: {', '.join(DEFAULT_TAGS)})."
        ),
    )
    parser.add_argument(
        "--source-type",
        default=DEFAULT_SOURCE_TYPE,
        help=(
            "Channel recorded on the lead source itself, which is what the ROI "
            f"dashboard reports for these leads (default: {DEFAULT_SOURCE_TYPE}; "
            f"pass {KEEP_SOURCE_TYPE!r} to leave it alone)."
        ),
    )
    parser.add_argument(
        "--source-detail",
        default=DEFAULT_SOURCE_DETAIL,
        help="Fallback source_detail to match (case-insensitive).",
    )
    parser.add_argument(
        "--name",
        default=None,
        help=f"Automation name (default: '{DEFAULT_NAME_BASE} — <what it does>').",
    )
    parser.add_argument("--description", default=None, help="Automation description.")
    parser.add_argument("--message", default=DEFAULT_MESSAGE, help="SMS body template.")
    parser.add_argument(
        "--sms",
        choices=SMS_MODES,
        default=SMS_AUTO,
        help=(
            "Whether the automation sends its own SMS. 'auto' (default) skips it "
            "when the lead source already auto-texts/-calls on capture, so leads "
            "are not messaged twice; 'on' forces it; 'off' never sends."
        ),
    )
    parser.add_argument(
        "--backfill",
        action="store_true",
        help=(
            "Also apply the tags to leads this source already captured "
            "(idempotent; the automation alone only affects future leads)."
        ),
    )


def main() -> int:
    ctx, args = bootstrap(
        description="Create/refresh the Perm Light Lead automation for a lead source.",
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
