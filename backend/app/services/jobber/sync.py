"""Idempotent, workspace-scoped sync of Jobber team members into technicians.

Design notes:

- **Idempotency** keys on ``(workspace_id, external_source='jobber',
  external_id=<Jobber user id>)`` — re-running upserts the same rows instead of
  duplicating. Backed by the partial unique index added in migration
  ``b3d8f1a2c4e5``.
- **Crews are CRM-managed.** Jobber has no crew entity, so this never pulls or
  mutates crews from Jobber data. It will only *ensure* a single local
  ``--default-crew`` exists and slot **newly created** technicians into it;
  existing crew assignments are never clobbered.
- **Deactivation is opt-in.** With ``deactivate_missing=True`` a previously
  imported technician that no longer appears in Jobber is marked inactive
  (never hard-deleted — dispatch history and FK links must survive).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterable, Iterable
from dataclasses import dataclass, field
from typing import Any

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.field_service import Crew, Technician
from app.services.jobber.mapping import (
    EXTERNAL_SOURCE,
    JobberMappingError,
    jobber_user_to_technician_data,
)

logger = structlog.get_logger()

# Technician fields this sync owns from Jobber. Crew assignment, color, skills
# and user-login links are deliberately excluded so local edits to them survive
# a re-sync.
_SYNCED_FIELDS = ("name", "email", "phone")


@dataclass
class JobberSyncResult:
    """Outcome of a technician sync run (counts + ids for reporting)."""

    created: int = 0
    updated: int = 0
    unchanged: int = 0
    deactivated: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)
    default_crew_id: uuid.UUID | None = None

    @property
    def processed(self) -> int:
        return self.created + self.updated + self.unchanged

    def as_dict(self) -> dict[str, Any]:
        return {
            "created": self.created,
            "updated": self.updated,
            "unchanged": self.unchanged,
            "deactivated": self.deactivated,
            "skipped": self.skipped,
            "processed": self.processed,
            "errors": self.errors,
            "default_crew_id": (str(self.default_crew_id) if self.default_crew_id else None),
        }


class JobberTechnicianSync:
    """Upserts Jobber ``users`` into a workspace's technicians."""

    def __init__(self, db: AsyncSession, workspace_id: uuid.UUID) -> None:
        self.db = db
        self.workspace_id = workspace_id

    async def ensure_crew(self, name: str, *, color: str = "#6366f1") -> Crew:
        """Return the workspace crew named ``name``, creating it if absent.

        Match is case-insensitive on the trimmed name so ``"Install"`` and
        ``"install "`` resolve to one crew rather than colliding on the unique
        ``(workspace_id, name)`` constraint.
        """
        cleaned = name.strip()
        if not cleaned:
            raise ValueError("crew name must not be empty")

        existing = (
            await self.db.execute(
                select(Crew).where(
                    Crew.workspace_id == self.workspace_id,
                    func.lower(Crew.name) == cleaned.lower(),
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing

        crew = Crew(workspace_id=self.workspace_id, name=cleaned, color=color)
        self.db.add(crew)
        await self.db.flush()
        await self.db.refresh(crew)
        logger.info("jobber_sync_crew_created", crew_id=str(crew.id), name=cleaned)
        return crew

    async def _load_existing(self) -> dict[str, Technician]:
        """All Jobber-sourced technicians in this workspace, keyed by ext id."""
        rows = (
            (
                await self.db.execute(
                    select(Technician).where(
                        Technician.workspace_id == self.workspace_id,
                        Technician.external_source == EXTERNAL_SOURCE,
                    )
                )
            )
            .scalars()
            .all()
        )
        return {tech.external_id: tech for tech in rows if tech.external_id}

    async def sync(
        self,
        users: AsyncIterable[dict[str, Any]] | Iterable[dict[str, Any]],
        *,
        default_crew_id: uuid.UUID | None = None,
        deactivate_missing: bool = False,
    ) -> JobberSyncResult:
        """Upsert ``users`` (Jobber nodes) into technicians.

        ``users`` may be an async iterator (live client) or a plain iterable
        (tests/replays). New technicians are created active; existing rows have
        only :data:`_SYNCED_FIELDS` refreshed. ``default_crew_id`` is applied to
        **created** rows only.
        """
        result = JobberSyncResult(default_crew_id=default_crew_id)
        existing = await self._load_existing()
        seen: set[str] = set()

        async for node in _aiter(users):
            try:
                data = jobber_user_to_technician_data(node)
            except JobberMappingError as exc:
                result.skipped += 1
                result.errors.append(str(exc))
                logger.warning("jobber_sync_skip", error=str(exc))
                continue

            ext_id = data["external_id"]
            seen.add(ext_id)
            current = existing.get(ext_id)

            if current is None:
                technician = Technician(
                    workspace_id=self.workspace_id,
                    crew_id=default_crew_id,
                    is_active=True,
                    **data,
                )
                self.db.add(technician)
                # Register it so a duplicate id later in the same feed resolves
                # to an update (no-op) rather than a second insert.
                existing[ext_id] = technician
                result.created += 1
                continue

            # Reactivate a returning technician and refresh owned fields only.
            changed = False
            if not current.is_active:
                current.is_active = True
                changed = True
            for f in _SYNCED_FIELDS:
                if getattr(current, f) != data[f]:
                    setattr(current, f, data[f])
                    changed = True
            if changed:
                result.updated += 1
            else:
                result.unchanged += 1

        if deactivate_missing:
            for ext_id, tech in existing.items():
                if ext_id not in seen and tech.is_active:
                    tech.is_active = False
                    result.deactivated += 1

        await self.db.flush()
        logger.info("jobber_sync_complete", **result.as_dict())
        return result


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #
async def _aiter(
    source: AsyncIterable[dict[str, Any]] | Iterable[dict[str, Any]],
) -> AsyncIterable[dict[str, Any]]:
    """Adapt a sync or async iterable to a uniform async iterator."""
    if isinstance(source, AsyncIterable):
        async for item in source:
            yield item
    else:
        for item in source:
            yield item
