"""Radius search around a job site — the "who else is on this street" query.

A crew that just spent a day on a driveway is the cheapest advertising a
home-service business will ever buy: the neighbours watched the work happen, saw
the truck, and can see the result from their own porch. This module is the
geographic half of turning that into pipeline — given a finished job's site, find
the other :class:`~app.models.field_service.ServiceLocation` rows close enough to
have watched.

Design constraints this file works inside:

- **No PostGIS.** ``backend/pyproject.toml`` has no ``geoalchemy2``/PostGIS
  dependency, so there is no ``ST_DWithin`` to call. The search is therefore a
  two-stage filter: a **bounding-box prefilter** in SQL (index-friendly, uses the
  plain ``latitude``/``longitude`` floats) followed by a **haversine refinement**
  in Python that trims the box's corners down to a true circle.
- **Latitude/longitude only.** ``ServiceLocation.city`` and ``postal_code`` are
  :class:`app.core.encryption.EncryptedString` — Fernet ciphertext in ``TEXT``,
  non-deterministic — so they cannot appear in a ``WHERE`` clause or a
  ``GROUP BY``. ``latitude``/``longitude`` are deliberately plain ``Float``
  columns (see the module docstring of :mod:`app.models.field_service`), so they
  are the *only* geographic predicate available. Never "optimize" this by
  matching postal codes.
- **Nulls are data, not errors.** A site created by hand or imported without
  geocoding has ``latitude is None``. Those rows are skipped, never crashed on.

The pure functions (:func:`haversine_meters`, :func:`bounding_box`,
:func:`refine_candidates`) hold all the maths and all the exclusion rules, so
correctness is provable without a database. :func:`find_nearby_locations` is the
thin tenant-scoped SQL wrapper around them.
"""

from __future__ import annotations

import math
import uuid
from collections.abc import Collection, Iterable
from dataclasses import dataclass
from typing import Protocol

import structlog
from sqlalchemy import Float, and_, cast, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.scope import select_workspace_owned
from app.models.field_service import Job, ServiceLocation

logger = structlog.get_logger()

# IUGG mean Earth radius in metres. A spherical model is accurate to ~0.5% —
# three orders of magnitude tighter than the uncertainty in "which houses saw the
# crew", so an ellipsoidal (Vincenty/geodesic) model would be false precision.
EARTH_RADIUS_METERS = 6_371_008.8

# A neighbour radius is a walk down the street, not a market. The floor keeps a
# misconfigured 0 from silently disabling the feature; the ceiling keeps a
# fat-fingered 150_000 from turning a door-hanger run into a city-wide scrape.
MIN_RADIUS_METERS = 10
MAX_RADIUS_METERS = 5_000
DEFAULT_RADIUS_METERS = 150

# Cap on persisted/returned neighbours per job.
DEFAULT_MAX_NEIGHBORS = 50
MAX_NEIGHBORS_CEILING = 500

# The SQL prefilter fetches more rows than the caller wants, because the box's
# corners get trimmed by the haversine refinement (a square circumscribing a
# circle is ~27% larger). Ordered nearest-first, so the hard ``LIMIT`` below
# bounds memory without dropping close-in neighbours.
_PREFILTER_MULTIPLIER = 4
_PREFILTER_FLOOR = 200
_PREFILTER_CEILING = 5_000

# Below this cosine the longitude-per-metre conversion explodes (polar). No
# home-service workspace operates there; degrade to "all longitudes" and let the
# haversine refinement do the real work rather than dividing by ~0.
_POLAR_COS_EPSILON = 1e-6


class RadiusCandidate(Protocol):
    """The shape :func:`refine_candidates` needs off a candidate row.

    Structural, not nominal, so the refinement can be exercised against plain
    stubs in a unit test while production passes real
    :class:`~app.models.field_service.ServiceLocation` rows.
    """

    @property
    def id(self) -> uuid.UUID: ...

    @property
    def contact_id(self) -> int: ...

    @property
    def latitude(self) -> float | None: ...

    @property
    def longitude(self) -> float | None: ...


@dataclass(frozen=True, slots=True)
class BoundingBox:
    """Latitude/longitude window that fully contains a circle on the sphere.

    ``wraps_antimeridian`` is set when the window crosses ±180° longitude, in
    which case ``min_lng > max_lng`` and the longitude predicate must be an ``OR``
    of two ranges rather than a ``BETWEEN``.
    """

    min_lat: float
    max_lat: float
    min_lng: float
    max_lng: float
    wraps_antimeridian: bool
    # True when the circle reaches a pole (or is polar enough that a longitude
    # window is meaningless), so every longitude is inside the box.
    spans_all_longitudes: bool


@dataclass(frozen=True, slots=True)
class NearbyLocation[RowT]:
    """A candidate row that survived the refinement, with its true distance."""

    row: RowT
    distance_meters: float


def haversine_meters(
    origin_lat: float,
    origin_lng: float,
    target_lat: float,
    target_lng: float,
) -> float:
    """Great-circle distance in metres between two WGS84 points.

    Uses ``atan2`` rather than ``asin`` so the result stays numerically stable for
    antipodal points, and clamps the intermediate to ``[0, 1]`` so floating-point
    drift on identical coordinates cannot push ``sqrt`` negative.
    """
    lat1 = math.radians(origin_lat)
    lat2 = math.radians(target_lat)
    delta_lat = lat2 - lat1
    delta_lng = math.radians(target_lng - origin_lng)

    inner = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lng / 2) ** 2
    )
    inner = min(1.0, max(0.0, inner))
    return 2 * EARTH_RADIUS_METERS * math.atan2(math.sqrt(inner), math.sqrt(1 - inner))


def bounding_box(origin_lat: float, origin_lng: float, radius_meters: float) -> BoundingBox:
    """Smallest lat/lng window guaranteed to contain every point within ``radius_meters``.

    The latitude delta is constant; the longitude delta widens toward the poles,
    so it is computed at the box edge *nearest a pole* (the widest case) rather
    than at ``origin_lat``. Getting that backwards would shrink the box and drop
    real neighbours — a silent false negative, the worst failure mode here.
    """
    radius = max(0.0, radius_meters)
    lat_delta = math.degrees(radius / EARTH_RADIUS_METERS)

    raw_min_lat = origin_lat - lat_delta
    raw_max_lat = origin_lat + lat_delta
    min_lat = max(-90.0, raw_min_lat)
    max_lat = min(90.0, raw_max_lat)

    # Widest longitude span sits at whichever edge is closest to a pole.
    widest_lat = min(90.0, max(abs(min_lat), abs(max_lat)))
    cos_widest = math.cos(math.radians(widest_lat))

    # Touching a pole, or effectively polar: every meridian is in range.
    if raw_min_lat <= -90.0 or raw_max_lat >= 90.0 or cos_widest <= _POLAR_COS_EPSILON:
        return BoundingBox(
            min_lat=min_lat,
            max_lat=max_lat,
            min_lng=-180.0,
            max_lng=180.0,
            wraps_antimeridian=False,
            spans_all_longitudes=True,
        )

    lng_delta = math.degrees(radius / (EARTH_RADIUS_METERS * cos_widest))
    if lng_delta >= 180.0:
        return BoundingBox(
            min_lat=min_lat,
            max_lat=max_lat,
            min_lng=-180.0,
            max_lng=180.0,
            wraps_antimeridian=False,
            spans_all_longitudes=True,
        )

    raw_min_lng = origin_lng - lng_delta
    raw_max_lng = origin_lng + lng_delta
    wraps = raw_min_lng < -180.0 or raw_max_lng > 180.0
    return BoundingBox(
        min_lat=min_lat,
        max_lat=max_lat,
        min_lng=_normalize_longitude(raw_min_lng),
        max_lng=_normalize_longitude(raw_max_lng),
        wraps_antimeridian=wraps,
        spans_all_longitudes=False,
    )


def _normalize_longitude(longitude: float) -> float:
    """Fold a longitude into ``[-180, 180)``."""
    return (longitude + 180.0) % 360.0 - 180.0


def refine_candidates[RowT: RadiusCandidate](
    candidates: Iterable[RowT],
    *,
    origin_lat: float,
    origin_lng: float,
    radius_meters: float,
    exclude_location_ids: Collection[uuid.UUID] = (),
    exclude_contact_ids: Collection[int] = (),
    limit: int = DEFAULT_MAX_NEIGHBORS,
) -> list[NearbyLocation[RowT]]:
    """Trim bounding-box candidates to a true circle, nearest first.

    All of the feature's correctness rules live here, in one pure function:

    - a row with a missing ``latitude`` **or** ``longitude`` is skipped (an
      ungeocoded site is not a neighbour, and must not raise);
    - the job's own site and every other site owned by the *same customer* are
      excluded — mailing a door hanger to the house you just worked, or to that
      customer's rental across the street, is the embarrassing bug here;
    - the radius boundary is **inclusive**: a location exactly ``radius_meters``
      away is a neighbour;
    - results are capped at ``limit`` *after* sorting by distance, so the cap
      keeps the closest neighbours rather than an arbitrary slice.

    Ties are broken on ``id`` so the ordering is total and a regenerate produces
    the same batch given the same inputs.
    """
    if limit <= 0:
        return []

    excluded_locations = set(exclude_location_ids)
    excluded_contacts = set(exclude_contact_ids)

    matches: list[NearbyLocation[RowT]] = []
    for candidate in candidates:
        latitude = candidate.latitude
        longitude = candidate.longitude
        if latitude is None or longitude is None:
            continue
        if candidate.id in excluded_locations or candidate.contact_id in excluded_contacts:
            continue
        distance = haversine_meters(origin_lat, origin_lng, latitude, longitude)
        if distance > radius_meters:
            continue
        matches.append(NearbyLocation(row=candidate, distance_meters=distance))

    matches.sort(key=lambda match: (match.distance_meters, str(match.row.id)))
    return matches[:limit]


def clamp_radius_meters(radius_meters: float | int | None) -> float:
    """Clamp a caller/config-supplied radius into the supported window."""
    if radius_meters is None:
        return float(DEFAULT_RADIUS_METERS)
    return float(min(MAX_RADIUS_METERS, max(MIN_RADIUS_METERS, radius_meters)))


def clamp_max_neighbors(max_neighbors: int | None) -> int:
    """Clamp a caller/config-supplied result cap into the supported window."""
    if max_neighbors is None:
        return DEFAULT_MAX_NEIGHBORS
    return min(MAX_NEIGHBORS_CEILING, max(1, max_neighbors))


def _prefilter_limit(max_results: int) -> int:
    """How many bounding-box rows to pull before the haversine refinement."""
    return min(_PREFILTER_CEILING, max(_PREFILTER_FLOOR, max_results * _PREFILTER_MULTIPLIER))


async def resolve_job_exclusions(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    job_id: uuid.UUID,
) -> tuple[set[uuid.UUID], set[int]]:
    """Location ids and contact ids to exclude for ``job_id``.

    Returns the job's own site plus its customer, so every site that customer
    owns drops out of the neighbour list. Workspace-scoped: a job id from another
    tenant resolves to no exclusions rather than reading across the boundary.
    """
    row = (
        await db.execute(
            select(Job.service_location_id, Job.contact_id).where(
                Job.workspace_id == workspace_id,
                Job.id == job_id,
            )
        )
    ).first()
    if row is None:
        return set(), set()

    location_ids: set[uuid.UUID] = set()
    if row.service_location_id is not None:
        location_ids.add(row.service_location_id)
    return location_ids, {row.contact_id}


async def find_nearby_locations(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    origin_lat: float,
    origin_lng: float,
    radius_meters: float = DEFAULT_RADIUS_METERS,
    exclude_job_id: uuid.UUID | None = None,
    max_results: int = DEFAULT_MAX_NEIGHBORS,
    active_only: bool = True,
) -> list[NearbyLocation[ServiceLocation]]:
    """Service locations within ``radius_meters`` of a point, nearest first.

    Stage 1 is the SQL bounding box: workspace-scoped, non-null coordinates,
    inside the lat/lng window, ordered by a cheap planar distance so the hard
    prefilter ``LIMIT`` keeps the closest rows. Stage 2 is
    :func:`refine_candidates`, which applies the true haversine distance, the
    own-site/same-customer exclusions, and the cap.

    ``exclude_job_id`` is resolved to the job's own service location *and* its
    customer, so none of that customer's sites can appear in their own neighbour
    list.
    """
    radius = clamp_radius_meters(radius_meters)
    cap = clamp_max_neighbors(max_results)

    exclude_location_ids: set[uuid.UUID] = set()
    exclude_contact_ids: set[int] = set()
    if exclude_job_id is not None:
        exclude_location_ids, exclude_contact_ids = await resolve_job_exclusions(
            db, workspace_id=workspace_id, job_id=exclude_job_id
        )

    box = bounding_box(origin_lat, origin_lng, radius)
    criteria: list[object] = [
        ServiceLocation.latitude.is_not(None),
        ServiceLocation.longitude.is_not(None),
        ServiceLocation.latitude >= box.min_lat,
        ServiceLocation.latitude <= box.max_lat,
    ]
    if active_only:
        criteria.append(ServiceLocation.is_active.is_(True))
    if not box.spans_all_longitudes:
        if box.wraps_antimeridian:
            # The window straddles ±180°, so it is the union of two ranges.
            criteria.append(
                or_(
                    ServiceLocation.longitude >= box.min_lng,
                    ServiceLocation.longitude <= box.max_lng,
                )
            )
        else:
            criteria.append(
                and_(
                    ServiceLocation.longitude >= box.min_lng,
                    ServiceLocation.longitude <= box.max_lng,
                )
            )
    if exclude_location_ids:
        criteria.append(ServiceLocation.id.not_in(exclude_location_ids))
    if exclude_contact_ids:
        criteria.append(ServiceLocation.contact_id.not_in(exclude_contact_ids))

    # Planar squared distance, longitude scaled by cos(latitude) so a degree of
    # longitude is comparable to a degree of latitude. Ordering only — the real
    # distance test is the haversine refinement below. (For an antimeridian-
    # straddling box this ordering is wrong near the seam; harmless at the ≤5km
    # radii this feature supports, where the prefilter limit is never reached.)
    lng_scale = max(_POLAR_COS_EPSILON, math.cos(math.radians(origin_lat)))
    lat_offset = cast(ServiceLocation.latitude, Float) - origin_lat
    lng_offset = (cast(ServiceLocation.longitude, Float) - origin_lng) * lng_scale
    planar_distance = lat_offset * lat_offset + lng_offset * lng_offset

    query = (
        select_workspace_owned(ServiceLocation, workspace_id, *criteria)
        .order_by(planar_distance, ServiceLocation.id)
        .limit(_prefilter_limit(cap))
    )
    candidates = (await db.execute(query)).scalars().all()

    nearby = refine_candidates(
        candidates,
        origin_lat=origin_lat,
        origin_lng=origin_lng,
        radius_meters=radius,
        exclude_location_ids=exclude_location_ids,
        exclude_contact_ids=exclude_contact_ids,
        limit=cap,
    )
    logger.debug(
        "jobsite_radius_search",
        workspace_id=str(workspace_id),
        radius_meters=radius,
        candidates=len(candidates),
        matches=len(nearby),
    )
    return nearby
