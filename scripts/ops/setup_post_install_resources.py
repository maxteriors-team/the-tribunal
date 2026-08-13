"""Create/refresh the post-install "here's how your system works" automation.

Wires a ``job_completed`` automation so every finished job sends the customer
their owner's resources: a text with a tracked short link, and an email with the
same link (the email path linkifies bare URLs, so it arrives clickable).

The link points at the **resources hub**, not at one product guide, on purpose:
``job_completed`` fires for *every* completed job in the workspace — installs,
service calls, holiday-light takedowns — and the worker has no per-job-type
selector (only ``lead_created`` supports trigger_config narrowing today). A hub
is correct for all of them; a Luxor-app guide texted after a takedown is not.

Content served from ``backend/static/guides/`` (public, no PII — see
CLAUDE.md > backend/static):

    index.html      resources hub (what this automation links to)
    luxor-app.html  landscape lighting: running the Luxor app

Idempotent: matched on (workspace, ``job_completed``,
``trigger_config.marker == post_install_resources``); re-running updates the
existing row in place instead of creating a second automation that double-texts
every customer.

Usage
-----

    # Preview against local without writing:
    uv run python ../scripts/ops/setup_post_install_resources.py --env local --dry-run

    # Apply to local:
    uv run python ../scripts/ops/setup_post_install_resources.py --env local

    # Apply to production (typed confirmation required):
    uv run python ../scripts/ops/setup_post_install_resources.py --env production

Run it from ``backend/`` (that is where the ``uv`` project lives).
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import uuid
from pathlib import Path
from typing import Any, NamedTuple
from urllib.parse import urlparse

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

# ── Defaults for the Maxteriors workspace ────────────────────────────────────

# Same workspace the inbound lighting assistant runs in (scripts/demo/create_maxteriors_agent.py).
DEFAULT_WORKSPACE_ID = "ba0e0e99-c7c9-45ec-9625-567d54d6e9c2"

# Branded backend host (scripts/ops/setup_branded_links.sh) serving backend/static/.
# Keep this on the branded domain: it is what the customer reads in the email,
# and what the SMS shortener's /r/{code} target resolves to.
DEFAULT_GUIDE_URL = "https://go.maxteriorslighting.com/static/guides/index.html"

TRIGGER_TYPE = "job_completed"
# Stable idempotency selector — the automation is found by this, not by name,
# so renaming it in the dashboard never causes a duplicate on the next run.
MARKER = "post_install_resources"

DEFAULT_NAME = "Post-install resources"
DEFAULT_DESCRIPTION = (
    "When a job is marked complete, send the customer their owner's resources "
    "(how the app works, schedule, care, how to reach us)."
)

# {url} is substituted by this script before the automation is saved; the
# worker's own {first_name} token is left intact for send time.
DEFAULT_SMS = (
    "Hi {first_name}, it's Max with Maxteriors — your lights are all set. "
    "Here's how to run them from your phone: {url} "
    "Questions or tweaks, just reply."
)

DEFAULT_EMAIL_SUBJECT = "Your new lighting — here's how to run it"

# One source line per rendered line: the body is plain text and the email
# renderer turns each newline into a <br>, so a wrapped paragraph here would
# arrive wrapped in the customer's inbox too.
DEFAULT_EMAIL_BODY = (
    "Hi {first_name},\n"
    "\n"
    "Your install is wrapped up — thanks for having us out.\n"
    "\n"
    "Everything you need to run the system is here, including how the app works, "
    "your nightly schedule, dimming and color, and the quick checks that solve most "
    '"something looks off" nights:\n'
    "\n"
    "{url}\n"
    "\n"
    "Bookmark that link — it stays the same, and we add guides to it.\n"
    "\n"
    "Want anything adjusted? Brightness, shutoff time, aiming after the plants fill "
    "in — just reply to this email or text (248) 593-0266. That's normal service, "
    "not a complaint.\n"
    "\n"
    "— Max\n"
    "Maxteriors\n"
)


def _validate_url(raw: str, logger: logging.Logger) -> str | None:
    """Reject a guide URL that would ship a dead link to a real customer.

    A wrong value here fails silently: the email sends, the text delivers, and
    only the customer discovers the link goes nowhere. So require an absolute
    https URL up front rather than after the first install of the week.
    """
    parsed = urlparse(raw)
    if parsed.scheme != "https" or not parsed.netloc:
        log_event(
            logger,
            logging.ERROR,
            "--guide-url must be an absolute https:// URL",
            value=raw,
        )
        return None
    if parsed.hostname in {"localhost", "127.0.0.1", "::1"}:
        log_event(logger, logging.ERROR, "--guide-url points at localhost", value=raw)
        return None
    return raw


def _fill_url(template: str, guide_url: str, logger: logging.Logger) -> str | None:
    """Substitute ``{url}`` now, leaving ``{first_name}`` for the worker.

    Any other brace token is operator error (the worker would render it blank or
    leave it literal in a customer-facing message), so fail here instead.
    """
    try:
        return template.format(url=guide_url, first_name="{first_name}")
    except (KeyError, IndexError, ValueError) as exc:
        log_event(
            logger,
            logging.ERROR,
            "template has an unsupported placeholder — use {url} and {first_name} only",
            error=str(exc),
        )
        return None


def _build_actions(
    *,
    guide_url: str,
    sms_template: str,
    email_subject: str,
    email_body: str,
    with_sms: bool,
    with_email: bool,
    logger: logging.Logger,
) -> list[dict[str, Any]] | None:
    """Text first (it gets read), email second (it gets kept)."""
    actions: list[dict[str, Any]] = []
    fallbacks = {"first_name": "there"}
    if with_sms:
        message = _fill_url(sms_template, guide_url, logger)
        if message is None:
            return None
        actions.append(
            {
                "type": "send_sms",
                # Installation follow-up is a service message, but the send
                # still requires the contact's explicit consent-of-record and
                # the worker always honors a global STOP/opt-out.
                "config": {
                    "message": message,
                    "fallbacks": fallbacks,
                    "require_consent": True,
                },
            }
        )
    if with_email:
        body = _fill_url(email_body, guide_url, logger)
        if body is None:
            return None
        actions.append(
            {
                "type": "send_email",
                "config": {
                    "subject": email_subject,
                    "message": body,
                    "fallbacks": fallbacks,
                    # Owner instructions directly tied to a completed install,
                    # with no offer or upsell: service/transactional mail.
                    "transactional": True,
                    "business_name": "Maxteriors",
                    "logo_url": (
                        "https://go.maxteriorslighting.com/static/brand/maxteriors-logo.png"
                    ),
                },
            }
        )
    return actions


class _Plan(NamedTuple):
    """Validated CLI input, resolved before any database work."""

    workspace_id: uuid.UUID
    guide_url: str
    with_sms: bool
    with_email: bool


def _parse_plan(args: argparse.Namespace, logger: logging.Logger) -> _Plan | None:
    """Resolve and validate CLI input, or log why the run cannot proceed.

    Everything here fails before the confirm prompt, so a typo never reaches a
    real customer's inbox as a dead link or an automation that sends nothing.
    """
    guide_url = _validate_url(args.guide_url, logger)
    if guide_url is None:
        return None

    with_sms = not args.no_sms
    with_email = not args.no_email
    if not with_sms and not with_email:
        log_event(logger, logging.ERROR, "--no-sms and --no-email leave nothing to send")
        return None

    try:
        workspace_id = uuid.UUID(args.workspace_id)
    except ValueError:
        log_event(logger, logging.ERROR, "--workspace-id is not a UUID", value=args.workspace_id)
        return None

    return _Plan(workspace_id, guide_url, with_sms, with_email)


async def _apply(ctx: ExecutionContext, args: argparse.Namespace) -> int:
    from sqlalchemy import select

    from app.db.session import AsyncSessionLocal
    from app.models.automation import Automation
    from app.models.workspace import Workspace

    logger = ctx.logger

    plan = _parse_plan(args, logger)
    if plan is None:
        return EXIT_FAILURE
    workspace_id, guide_url, with_sms, with_email = plan

    async with AsyncSessionLocal() as db:
        workspace = await db.get(Workspace, workspace_id)
        if workspace is None:
            log_event(
                logger,
                logging.ERROR,
                "workspace not found — nothing to wire",
                workspace_id=str(workspace_id),
            )
            return EXIT_FAILURE

        ctx.announce(
            "wiring post-install resources",
            workspace_id=str(workspace_id),
            workspace=workspace.name,
            guide_url=guide_url,
            sends_sms=with_sms,
            sends_email=with_email,
        )

        # The worker matches event automations on trigger type alone (only
        # lead_created narrows via trigger_config), so this fires for every
        # completed job — service calls and takedowns included. That is why the
        # link is the hub rather than one product's guide.
        log_event(
            logger,
            logging.WARNING,
            "job_completed has no per-job-type filter: every completed job sends this",
            link_target="resources hub",
        )

        actions = _build_actions(
            guide_url=guide_url,
            sms_template=args.sms_message,
            email_subject=args.email_subject,
            email_body=args.email_body,
            with_sms=with_sms,
            with_email=with_email,
            logger=logger,
        )
        if actions is None:
            return EXIT_FAILURE

        existing = (
            await db.execute(
                select(Automation).where(
                    Automation.workspace_id == workspace_id,
                    Automation.trigger_type == TRIGGER_TYPE,
                    Automation.trigger_config["marker"].astext == MARKER,
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
            actions=len(actions),
        )

        if ctx.dry_run:
            for action in actions:
                log_event(
                    logger,
                    logging.INFO,
                    "dry-run action preview",
                    type=action["type"],
                    body=(action["config"].get("message") or "")[:400],
                )
            log_event(logger, logging.WARNING, "dry-run: no changes committed")
            return EXIT_OK

        ctx.confirm(f"{verb} the '{args.name}' automation")

        trigger_config = {"marker": MARKER, "guide_url": guide_url}
        if existing is not None:
            existing.name = args.name
            existing.description = args.description
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
            sends_sms=with_sms,
            sends_email=with_email,
            guide_url=guide_url,
        )
        return EXIT_OK


def _configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--workspace-id",
        default=DEFAULT_WORKSPACE_ID,
        help=f"Workspace to wire (default: {DEFAULT_WORKSPACE_ID}).",
    )
    parser.add_argument(
        "--guide-url",
        default=DEFAULT_GUIDE_URL,
        help=f"Absolute https URL of the resources hub (default: {DEFAULT_GUIDE_URL}).",
    )
    parser.add_argument("--name", default=DEFAULT_NAME, help="Automation name.")
    parser.add_argument(
        "--description", default=DEFAULT_DESCRIPTION, help="Automation description."
    )
    parser.add_argument(
        "--sms-message",
        default=DEFAULT_SMS,
        help="SMS template; {url} is filled in here, {first_name} at send time.",
    )
    parser.add_argument("--email-subject", default=DEFAULT_EMAIL_SUBJECT, help="Email subject.")
    parser.add_argument(
        "--email-body",
        default=DEFAULT_EMAIL_BODY,
        help="Email body template; {url} is filled in here, {first_name} at send time.",
    )
    parser.add_argument("--no-sms", action="store_true", help="Skip the text; send only the email.")
    parser.add_argument(
        "--no-email", action="store_true", help="Skip the email; send only the text."
    )


def main() -> int:
    ctx, args = bootstrap(
        description="Create/refresh the post-install customer resources automation.",
        logger_name="setup_post_install_resources",
        configure=_configure,
    )
    try:
        return asyncio.run(_apply(ctx, args))
    except ScriptAbortError:
        raise
    except Exception:
        ctx.logger.exception("failed to set up post-install resources")
        return EXIT_FAILURE


if __name__ == "__main__":
    raise SystemExit(run(main))
