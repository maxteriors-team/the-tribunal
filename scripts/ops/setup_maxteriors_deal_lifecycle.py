#!/usr/bin/env python3
"""Safely configure Maxteriors deal-lifecycle automation.

The command is dry-run-only unless ``--apply`` is present. The first write saves
an internal snapshot beside the lifecycle config so ``--rollback --apply`` can
restore the exact prior value. Re-running an unchanged setup or rollback is a
no-op; unexpected edits after setup abort rather than being overwritten.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import logging
import sys
from collections import defaultdict
from copy import deepcopy
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

_HARNESS = next(
    path / "backend" / "scripts" / "_harness.py"
    for path in Path(__file__).resolve().parents
    if (path / "backend" / "scripts" / "_harness.py").is_file()
)
if str(_HARNESS.parent) not in sys.path:
    sys.path.insert(0, str(_HARNESS.parent))

_harness_module = importlib.import_module("_harness")
EXIT_OK: int = int(_harness_module.EXIT_OK)
ScriptAbortError = _harness_module.ScriptAbortError
bootstrap = _harness_module.bootstrap
log_event = _harness_module.log_event
run = _harness_module.run
script_sessionmaker = _harness_module.script_sessionmaker

TARGET_EMAIL = "admin@maxteriors.com"
CONFIG_KEY = "deal_lifecycle"
BACKUP_KEY = "_maxteriors_deal_lifecycle_setup_v1"
STAGE_NAMES = {
    "new_lead_stage_id": "New Lead",
    "contacted_no_answer_stage_id": "Contacted (No Answer)",
    "visit_demo_scheduled_stage_id": "Visit/Demo Scheduled/Call",
    "qualified_stage_id": "Qualified and No Show",
    "quote_follow_up_stage_id": "Quote Sent / Follow Up",
    "won_stage_id": "Won",
    "job_completed_stage_id": "Job Completed",
    "unqualified_stage_id": "Unqualified (archived)",
}


@dataclass(slots=True)
class SetupPlan:
    """Resolved, transaction-local setup plan."""

    workspace: Any
    workspace_name: str
    member_email: str
    member_user_id: int
    pipeline_id: str | None
    stage_ids: dict[str, str]
    before_settings: dict[str, Any]
    after_settings: dict[str, Any]
    rollback: bool

    @property
    def changed(self) -> bool:
        return self.before_settings != self.after_settings

    def preview(self) -> dict[str, Any]:
        return {
            "mode": "rollback" if self.rollback else "setup",
            "workspace": self.workspace_name,
            "workspace_id": str(self.workspace.id),
            "member_email": self.member_email,
            "member_user_id": self.member_user_id,
            "pipeline_id": self.pipeline_id,
            "stage_ids": self.stage_ids,
            "would_change": self.changed,
            "before": self.before_settings.get(CONFIG_KEY),
            "after": self.after_settings.get(CONFIG_KEY),
            "rollback_snapshot": (
                "remove" if self.rollback else "preserve exact previous lifecycle config"
            ),
        }


def _configure_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Commit the displayed change. Without this flag the command is read-only.",
    )
    parser.add_argument(
        "--rollback",
        action="store_true",
        help="Restore the exact lifecycle value saved by the last applied setup.",
    )


def _validated_backup(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ScriptAbortError(f"workspace {BACKUP_KEY!r} snapshot is malformed")
    if set(raw) != {"previous_present", "previous", "applied"}:
        raise ScriptAbortError(f"workspace {BACKUP_KEY!r} snapshot has unexpected fields")
    previous_present = raw["previous_present"]
    previous = raw["previous"]
    if (
        not isinstance(previous_present, bool)
        or not isinstance(raw["applied"], dict)
        or (previous_present and not isinstance(previous, dict))
        or (not previous_present and previous is not None)
    ):
        raise ScriptAbortError(f"workspace {BACKUP_KEY!r} snapshot is malformed")
    return raw


async def _resolve_workspace(
    db: AsyncSession,
    *,
    member_email: str,
    lock: bool,
) -> tuple[Any, int]:
    from sqlalchemy import select

    from app.core.encryption import hash_value
    from app.db.tenancy import mark_session_as_system
    from app.models.user import User
    from app.models.workspace import Workspace, WorkspaceMembership

    mark_session_as_system(
        db,
        reason="admin setup locates the unique workspace for a fixed member email",
    )

    statement = (
        select(Workspace, User.id)
        .join(WorkspaceMembership, WorkspaceMembership.workspace_id == Workspace.id)
        .join(User, User.id == WorkspaceMembership.user_id)
        .where(
            User.email_hash == hash_value(member_email),
            User.is_active.is_(True),
            Workspace.is_active.is_(True),
        )
    )
    if lock:
        statement = statement.with_for_update()
    matches = list((await db.execute(statement)).all())
    if len(matches) != 1:
        raise ScriptAbortError(
            f"expected exactly one active workspace containing active member {member_email}; "
            f"found {len(matches)}"
        )

    workspace, user_id = matches[0]
    return workspace, user_id


async def _resolve_stages(
    db: AsyncSession,
    *,
    workspace_id: Any,
    lock: bool,
) -> tuple[Any, dict[str, Any]]:
    from sqlalchemy import select

    from app.models.pipeline import Pipeline, PipelineStage

    statement = (
        select(PipelineStage, Pipeline)
        .join(Pipeline, Pipeline.id == PipelineStage.pipeline_id)
        .where(
            Pipeline.workspace_id == workspace_id,
            PipelineStage.name.in_(STAGE_NAMES.values()),
        )
    )
    if lock:
        statement = statement.with_for_update()

    by_name: dict[str, list[tuple[Any, Any]]] = defaultdict(list)
    for stage, pipeline in (await db.execute(statement)).all():
        by_name[stage.name].append((stage, pipeline))

    resolved: dict[str, Any] = {}
    pipelines: dict[Any, Any] = {}
    for field_name, stage_name in STAGE_NAMES.items():
        matches = by_name[stage_name]
        if len(matches) != 1:
            raise ScriptAbortError(
                f"expected exactly one {stage_name!r} stage in the workspace; found {len(matches)}"
            )
        stage, pipeline = matches[0]
        resolved[field_name] = stage.id
        pipelines[pipeline.id] = pipeline

    if len(pipelines) != 1:
        raise ScriptAbortError("required stages do not all belong to one pipeline")
    pipeline = next(iter(pipelines.values()))
    if not pipeline.is_active:
        raise ScriptAbortError(f"matched pipeline {pipeline.name!r} is inactive")
    return pipeline, resolved


async def build_plan(
    db: AsyncSession,
    *,
    member_email: str = TARGET_EMAIL,
    rollback: bool = False,
    lock: bool = False,
) -> SetupPlan:
    """Resolve one safe setup or rollback plan without mutating data."""
    from pydantic import ValidationError

    from app.schemas.deal_lifecycle import DealLifecycleSettings

    workspace, member_user_id = await _resolve_workspace(
        db,
        member_email=member_email,
        lock=lock,
    )
    before_settings = deepcopy(workspace.settings or {})
    after_settings = deepcopy(before_settings)

    if rollback:
        raw_backup = after_settings.get(BACKUP_KEY)
        if raw_backup is None:
            return SetupPlan(
                workspace=workspace,
                workspace_name=workspace.name,
                member_email=member_email,
                member_user_id=member_user_id,
                pipeline_id=None,
                stage_ids={},
                before_settings=before_settings,
                after_settings=after_settings,
                rollback=True,
            )
        backup = _validated_backup(raw_backup)
        if after_settings.get(CONFIG_KEY) != backup["applied"]:
            raise ScriptAbortError(
                "deal lifecycle config changed after setup; refusing to overwrite operator edits"
            )
        if backup["previous_present"]:
            after_settings[CONFIG_KEY] = deepcopy(backup["previous"])
        else:
            after_settings.pop(CONFIG_KEY, None)
        after_settings.pop(BACKUP_KEY, None)
        return SetupPlan(
            workspace=workspace,
            workspace_name=workspace.name,
            member_email=member_email,
            member_user_id=member_user_id,
            pipeline_id=None,
            stage_ids={},
            before_settings=before_settings,
            after_settings=after_settings,
            rollback=True,
        )

    pipeline, stages = await _resolve_stages(
        db,
        workspace_id=workspace.id,
        lock=lock,
    )
    existing = after_settings.get(CONFIG_KEY)
    existing_config = None
    if existing is not None:
        try:
            existing_config = DealLifecycleSettings.model_validate(existing)
        except ValidationError as exc:
            raise ScriptAbortError(
                "stored deal lifecycle config is invalid; refusing to replace it"
            ) from exc

    desired = DealLifecycleSettings(
        pipeline_id=pipeline.id,
        **stages,
        follow_up_assignee_user_id=member_user_id,
        end_of_day_cutoff=(
            existing_config.end_of_day_cutoff if existing_config is not None else "17:00"
        ),
    ).model_dump(mode="json")

    raw_backup = after_settings.get(BACKUP_KEY)
    if raw_backup is not None:
        backup = deepcopy(_validated_backup(raw_backup))
        if existing != backup["applied"]:
            raise ScriptAbortError(
                "deal lifecycle config changed after setup; rollback or reconcile it first"
            )
    elif existing == desired:
        return SetupPlan(
            workspace=workspace,
            workspace_name=workspace.name,
            member_email=member_email,
            member_user_id=member_user_id,
            pipeline_id=str(pipeline.id),
            stage_ids={key: str(value) for key, value in stages.items()},
            before_settings=before_settings,
            after_settings=after_settings,
            rollback=False,
        )
    else:
        backup = {
            "previous_present": CONFIG_KEY in before_settings,
            "previous": deepcopy(existing),
            "applied": desired,
        }

    backup["applied"] = desired
    after_settings[BACKUP_KEY] = backup
    after_settings[CONFIG_KEY] = desired
    return SetupPlan(
        workspace=workspace,
        workspace_name=workspace.name,
        member_email=member_email,
        member_user_id=member_user_id,
        pipeline_id=str(pipeline.id),
        stage_ids={key: str(value) for key, value in stages.items()},
        before_settings=before_settings,
        after_settings=after_settings,
        rollback=False,
    )


async def apply_setup(
    db: AsyncSession,
    *,
    member_email: str = TARGET_EMAIL,
    rollback: bool = False,
) -> SetupPlan:
    """Apply one locked setup plan; intended for integration tests and the CLI."""
    plan = await build_plan(db, member_email=member_email, rollback=rollback, lock=True)
    if plan.changed:
        plan.workspace.settings = plan.after_settings
        await db.commit()
    else:
        await db.rollback()
    return plan


def _same_preview(left: SetupPlan, right: SetupPlan) -> bool:
    return (
        left.workspace.id == right.workspace.id
        and left.before_settings == right.before_settings
        and left.after_settings == right.after_settings
    )


async def _execute(ctx: Any, args: argparse.Namespace) -> int:
    async with (
        script_sessionmaker(ctx) as session_factory,
        session_factory() as db,
    ):
        preview = await build_plan(db, rollback=args.rollback)
        print(json.dumps(preview.preview(), indent=2, sort_keys=True))
        await db.rollback()

        if not args.apply or not preview.changed:
            log_event(
                ctx.logger,
                logging.INFO,
                "setup preview complete" if not args.apply else "configuration already matches",
                changed=preview.changed,
            )
            return EXIT_OK

        action = (
            "rollback Maxteriors deal lifecycle"
            if args.rollback
            else "configure Maxteriors deal lifecycle"
        )
        ctx.confirm(action)
        locked = await build_plan(db, rollback=args.rollback, lock=True)
        if not _same_preview(preview, locked):
            await db.rollback()
            raise ScriptAbortError("workspace data changed after preview; rerun the command")

        locked.workspace.settings = locked.after_settings
        await db.commit()
        log_event(
            ctx.logger,
            logging.INFO,
            "deal lifecycle rollback applied" if args.rollback else "deal lifecycle setup applied",
            workspace_id=str(locked.workspace.id),
        )
    return EXIT_OK


def main() -> int:
    base_ctx, args = bootstrap(
        description=(
            "Configure Maxteriors deal lifecycle. Defaults to a read-only preview; "
            "writes require explicit --apply."
        ),
        writes=False,
        logger_name="scripts.setup_maxteriors_deal_lifecycle",
        configure=_configure_parser,
    )
    ctx = replace(base_ctx, dry_run=not args.apply)
    ctx.announce(
        "prepare Maxteriors deal lifecycle",
        apply=args.apply,
        rollback=args.rollback,
        member_email=TARGET_EMAIL,
    )
    return asyncio.run(_execute(ctx, args))


if __name__ == "__main__":
    raise SystemExit(run(main))
