"""Last season's holiday-lighting customers, as a queryable audience.

A metro-Detroit exteriors business loses most of its revenue December–March, and
holiday lighting is the line that fills it. The cheapest bookings in that line are
not leads at all — they are the homes that were already lit last year: the crew
knows the roof, the measurement is on file, and the customer has already decided
they like Christmas lights.

Until this module the product could not *find* those people. ``CHRISTMAS_LIGHTS``
service plans were written on approval and read back by exactly one list-endpoint
filter; the contact filter engine cannot reach jobs, quotes, or plans at all; and
the pre-booking warm audience is service-blind and date-blind — a 2019
gutter-cleaning customer and last November's lighting customer are the same row to
it. So "text everyone who had lights last year" was not an expressible query.

**What counts as a signup.** The :class:`~app.models.recurring_job.RecurringJobTemplate`
the approval provisioner writes for every seasonal sale
(:mod:`app.services.recurring_jobs.service_plan_provisioner`). That row *is* the
record of the signup, and it is covered by the ``(workspace_id, plan_type)`` index,
so this predicate stays an indexed ``EXISTS`` rather than a JSONB scan across
every quote's ``category_sections``. The deliberate cost: a Christmas quote
approved before the provisioner shipped has no plan row and is invisible here.

**Which season a signup belongs to.** Seasons are sold months before they are
installed and run across New Year, so the calendar year of a signup is the wrong
answer twice over: a sale in September 2025 and a late add in December 2025 are
both the 2025 season, and so is a January 2026 add-on while the lights are still
up. The boundary that actually separates two seasons is the **takedown anchor** —
once the lights come down, the next sale belongs to the next season. Season
arithmetic therefore keys off ``ChristmasConfig.season_takedown_month/day``, the
per-workspace anchor the provisioner already schedules against, rather than
inventing a second season calendar.
"""

from __future__ import annotations

import uuid
from calendar import monthrange
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import and_, exists
from sqlalchemy.sql.elements import ColumnElement

from app.models.contact import Contact
from app.models.recurring_job import RecurringJobTemplate, ServicePlanType
from app.models.workspace import Workspace
from app.schemas.pricing import ChristmasConfig


@dataclass(frozen=True, slots=True)
class ChristmasSeason:
    """The season currently being sold, and where the previous one ended.

    ``year`` labels the season by the calendar year its install falls in (the
    "2026 season" is installed in autumn 2026). ``started_at`` is the takedown
    anchor that closed the season before it — the cutoff every prior-season
    query is measured against.
    """

    year: int
    started_at: datetime


def _anchor(year: int, month: int, day: int) -> datetime:
    """A season anchor within ``year``, clamped to a day that month has.

    Mirrors the clamping in
    :mod:`app.services.recurring_jobs.service_plan_provisioner` so a workspace
    configured for e.g. the 31st of a short month resolves to the same instant in
    both places.
    """
    return datetime(year, month, min(day, monthrange(year, month)[1]), tzinfo=UTC)


def current_season(config: ChristmasConfig, *, now: datetime | None = None) -> ChristmasSeason:
    """Which season a workspace is selling right now.

    A moment on or after this year's takedown anchor belongs to this year's
    season; anything earlier is still last year's season running out (the lights
    are physically up). That single comparison is what makes a December signup
    and the following January's add-on land in the same season.
    """
    moment = now or datetime.now(UTC)
    boundary = _anchor(moment.year, config.season_takedown_month, config.season_takedown_day)
    if moment >= boundary:
        return ChristmasSeason(year=moment.year, started_at=boundary)
    return ChristmasSeason(
        year=moment.year - 1,
        started_at=_anchor(
            moment.year - 1, config.season_takedown_month, config.season_takedown_day
        ),
    )


def resolve_christmas_season(
    workspace: Workspace, *, now: datetime | None = None
) -> ChristmasSeason:
    """The current season for a workspace, from its saved pricing config."""
    # Imported here rather than at module scope: ``app.services.quotes`` eagerly
    # imports ``QuoteService``, so a top-level import would create a package
    # cycle through the provisioner.
    from app.services.quotes.pricing_config import get_pricing_config

    return current_season(get_pricing_config(workspace).christmas, now=now)


def prior_season_christmas_condition(
    workspace_id: uuid.UUID,
    season: ChristmasSeason,
    *,
    seasons_back: int | None = None,
) -> ColumnElement[bool]:
    """Contacts who signed up for holiday lighting in an earlier season.

    Correlates on :class:`~app.models.contact.Contact`, so it composes with the
    existing audience predicates and with any query already selecting contacts.

    ``seasons_back`` bounds how far to reach: ``1`` is strictly last season (the
    warmest renewal list), ``3`` is a win-back sweep, ``None`` is every season on
    record. Bounding is a floor on the signup date, so a customer who bought in
    several seasons is still matched by their most recent one.
    """
    clauses = [
        RecurringJobTemplate.contact_id == Contact.id,
        RecurringJobTemplate.workspace_id == workspace_id,
        RecurringJobTemplate.plan_type == str(ServicePlanType.CHRISTMAS_LIGHTS),
        RecurringJobTemplate.created_at < season.started_at,
    ]
    if seasons_back is not None:
        # ``season.started_at`` closed the previous season, so stepping back
        # ``seasons_back`` whole years from it is the floor of the oldest season
        # still in range.
        floor = _anchor(
            season.year - seasons_back,
            season.started_at.month,
            season.started_at.day,
        )
        clauses.append(RecurringJobTemplate.created_at >= floor)
    return exists().where(and_(*clauses))
