"""Unit tests for the job-site radius search maths and exclusion rules.

Pure — no database, so these run in default CI (``make ci.backend``) rather than
under ``-m integration``. Everything that decides *which houses are neighbours*
lives in :func:`haversine_meters`, :func:`bounding_box`, and
:func:`refine_candidates`, so this file is where the feature's correctness is
proven. The SQL prefilter is covered separately in
``test_neighbor_outreach_service.py``.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass

import pytest

from app.services.field_service.jobsite_radius import (
    DEFAULT_MAX_NEIGHBORS,
    DEFAULT_RADIUS_METERS,
    EARTH_RADIUS_METERS,
    MAX_NEIGHBORS_CEILING,
    MAX_RADIUS_METERS,
    MIN_RADIUS_METERS,
    bounding_box,
    clamp_max_neighbors,
    clamp_radius_meters,
    haversine_meters,
    refine_candidates,
)


@dataclass(frozen=True)
class _Site:
    """Minimal stand-in for a ``ServiceLocation`` row."""

    id: uuid.UUID
    contact_id: int
    latitude: float | None
    longitude: float | None


def _site(
    *,
    lat: float | None,
    lng: float | None,
    contact_id: int = 1,
    site_id: uuid.UUID | None = None,
) -> _Site:
    return _Site(
        id=site_id or uuid.uuid4(),
        contact_id=contact_id,
        latitude=lat,
        longitude=lng,
    )


# --------------------------------------------------------------------------- #
# Haversine correctness against known coordinates
# --------------------------------------------------------------------------- #
class TestHaversine:
    """Distances against independently known reference values."""

    def test_identical_points_are_zero(self) -> None:
        assert haversine_meters(40.7128, -74.0060, 40.7128, -74.0060) == 0.0

    def test_one_degree_of_latitude_is_a_nautical_degree(self) -> None:
        """A degree of latitude is ~111.2 km anywhere on a sphere."""
        distance = haversine_meters(0.0, 0.0, 1.0, 0.0)
        assert distance == pytest.approx(math.radians(1) * EARTH_RADIUS_METERS, rel=1e-9)
        assert distance == pytest.approx(111_195, abs=50)

    def test_one_degree_of_longitude_shrinks_with_latitude(self) -> None:
        """At 60°N a degree of longitude is half its equatorial width (cos 60° = 0.5)."""
        at_equator = haversine_meters(0.0, 0.0, 0.0, 1.0)
        at_sixty = haversine_meters(60.0, 0.0, 60.0, 1.0)
        assert at_sixty == pytest.approx(at_equator * 0.5, rel=1e-3)

    def test_nyc_to_london_matches_published_great_circle(self) -> None:
        """JFK → LHR is ~5,555 km great-circle; allow 0.5% for the spherical model."""
        distance = haversine_meters(40.6413, -73.7781, 51.4700, -0.4543)
        assert distance == pytest.approx(5_554_000, rel=0.005)

    def test_short_street_scale_distance(self) -> None:
        """0.001° of latitude is ~111 m — the scale this feature actually works at."""
        assert haversine_meters(45.0, -93.0, 45.001, -93.0) == pytest.approx(111.2, abs=0.5)

    def test_is_symmetric(self) -> None:
        forward = haversine_meters(44.9778, -93.2650, 44.9800, -93.2700)
        backward = haversine_meters(44.9800, -93.2700, 44.9778, -93.2650)
        assert forward == pytest.approx(backward, rel=1e-12)

    def test_antipodal_points_are_half_the_circumference(self) -> None:
        """The ``atan2`` form must stay stable at the degenerate antipode."""
        distance = haversine_meters(0.0, 0.0, 0.0, 180.0)
        assert distance == pytest.approx(math.pi * EARTH_RADIUS_METERS, rel=1e-9)


# --------------------------------------------------------------------------- #
# Bounding box: must never be smaller than the circle it wraps
# --------------------------------------------------------------------------- #
class TestBoundingBox:
    """The box is a prefilter, so a box that is too *small* loses real neighbours."""

    def test_contains_every_point_on_the_circle(self) -> None:
        origin_lat, origin_lng, radius = 44.9778, -93.2650, 150.0
        box = bounding_box(origin_lat, origin_lng, radius)

        # Walk the circle and assert every point on it is inside the box.
        for bearing_degrees in range(0, 360, 5):
            bearing = math.radians(bearing_degrees)
            lat = origin_lat + math.degrees(radius * math.cos(bearing) / EARTH_RADIUS_METERS)
            lng = origin_lng + math.degrees(
                radius * math.sin(bearing) / (EARTH_RADIUS_METERS * math.cos(math.radians(lat)))
            )
            assert box.min_lat <= lat <= box.max_lat
            assert box.min_lng <= lng <= box.max_lng

    def test_longitude_span_is_computed_at_the_pole_ward_edge(self) -> None:
        """Northern-hemisphere boxes must be at least as wide as at their top edge."""
        box = bounding_box(60.0, 10.0, 1_000.0)
        widest_lat = max(abs(box.min_lat), abs(box.max_lat))
        needed = math.degrees(1_000.0 / (EARTH_RADIUS_METERS * math.cos(math.radians(widest_lat))))
        assert (box.max_lng - 10.0) >= needed - 1e-12

    def test_longitude_span_widens_toward_the_poles(self) -> None:
        equator = bounding_box(0.0, 0.0, 1_000.0)
        high_latitude = bounding_box(70.0, 0.0, 1_000.0)
        assert (high_latitude.max_lng - high_latitude.min_lng) > (equator.max_lng - equator.min_lng)

    def test_antimeridian_crossing_is_flagged_and_normalized(self) -> None:
        box = bounding_box(0.0, 179.999, 1_000.0)
        assert box.wraps_antimeridian is True
        # Normalized into [-180, 180), so min > max — the caller must OR the ranges.
        assert box.min_lng > box.max_lng
        assert -180.0 <= box.min_lng <= 180.0
        assert -180.0 <= box.max_lng <= 180.0

    def test_polar_circle_spans_all_longitudes(self) -> None:
        box = bounding_box(89.9999, 0.0, 5_000.0)
        assert box.spans_all_longitudes is True
        assert (box.min_lng, box.max_lng) == (-180.0, 180.0)
        assert box.max_lat <= 90.0

    def test_latitude_is_clamped_to_the_poles(self) -> None:
        box = bounding_box(-89.9999, 0.0, 5_000.0)
        assert box.min_lat >= -90.0
        assert box.spans_all_longitudes is True

    def test_zero_radius_degenerates_to_the_point(self) -> None:
        box = bounding_box(10.0, 20.0, 0.0)
        assert (box.min_lat, box.max_lat) == (10.0, 10.0)
        assert (box.min_lng, box.max_lng) == (20.0, 20.0)


# --------------------------------------------------------------------------- #
# Refinement: nulls, exclusions, boundary, cap, ordering
# --------------------------------------------------------------------------- #
class TestRefineCandidates:
    """The exclusion rules and the radius boundary."""

    ORIGIN_LAT = 44.9778
    ORIGIN_LNG = -93.2650

    def _refine(self, candidates: list[_Site], **kwargs: object) -> list[_Site]:
        matches = refine_candidates(
            candidates,
            origin_lat=self.ORIGIN_LAT,
            origin_lng=self.ORIGIN_LNG,
            radius_meters=kwargs.pop("radius_meters", 150.0),  # type: ignore[arg-type]
            **kwargs,  # type: ignore[arg-type]
        )
        return [match.row for match in matches]

    # ----- null coordinates ------------------------------------------- #
    def test_null_latitude_is_skipped_not_crashed(self) -> None:
        """An ungeocoded site is not a neighbour, and must not raise."""
        ungeocoded = _site(lat=None, lng=self.ORIGIN_LNG)
        assert self._refine([ungeocoded]) == []

    def test_null_longitude_is_skipped_not_crashed(self) -> None:
        assert self._refine([_site(lat=self.ORIGIN_LAT, lng=None)]) == []

    def test_both_null_is_skipped_not_crashed(self) -> None:
        assert self._refine([_site(lat=None, lng=None)]) == []

    def test_null_coordinates_do_not_suppress_valid_neighbours(self) -> None:
        """One bad row must not poison the rest of the street."""
        good = _site(lat=self.ORIGIN_LAT + 0.0005, lng=self.ORIGIN_LNG, contact_id=2)
        result = self._refine([_site(lat=None, lng=None, contact_id=3), good])
        assert result == [good]

    # ----- exclusions -------------------------------------------------- #
    def test_own_location_is_excluded(self) -> None:
        own_id = uuid.uuid4()
        own = _site(lat=self.ORIGIN_LAT, lng=self.ORIGIN_LNG, contact_id=1, site_id=own_id)
        neighbour = _site(lat=self.ORIGIN_LAT + 0.0005, lng=self.ORIGIN_LNG, contact_id=2)
        result = self._refine([own, neighbour], exclude_location_ids=[own_id])
        assert result == [neighbour]

    def test_same_contact_other_sites_are_excluded(self) -> None:
        """The customer's rental across the street is not a neighbour lead."""
        rental = _site(lat=self.ORIGIN_LAT + 0.0003, lng=self.ORIGIN_LNG, contact_id=7)
        neighbour = _site(lat=self.ORIGIN_LAT + 0.0005, lng=self.ORIGIN_LNG, contact_id=8)
        result = self._refine([rental, neighbour], exclude_contact_ids=[7])
        assert result == [neighbour]

    def test_both_exclusion_sets_apply_together(self) -> None:
        own_id = uuid.uuid4()
        own = _site(lat=self.ORIGIN_LAT, lng=self.ORIGIN_LNG, contact_id=7, site_id=own_id)
        rental = _site(lat=self.ORIGIN_LAT + 0.0003, lng=self.ORIGIN_LNG, contact_id=7)
        stranger = _site(lat=self.ORIGIN_LAT + 0.0006, lng=self.ORIGIN_LNG, contact_id=9)
        result = self._refine(
            [own, rental, stranger],
            exclude_location_ids=[own_id],
            exclude_contact_ids=[7],
        )
        assert result == [stranger]

    def test_no_exclusions_keeps_everything_in_radius(self) -> None:
        first = _site(lat=self.ORIGIN_LAT + 0.0002, lng=self.ORIGIN_LNG, contact_id=1)
        second = _site(lat=self.ORIGIN_LAT + 0.0004, lng=self.ORIGIN_LNG, contact_id=2)
        assert self._refine([first, second]) == [first, second]

    # ----- radius boundary --------------------------------------------- #
    def test_boundary_is_inclusive(self) -> None:
        """A house exactly ``radius_meters`` away is a neighbour (``<=``, not ``<``).

        A point at a *nominal* 150 m lands at 150.000000… 1 after the
        degrees/radians round trip, so the radius is taken from the measured
        distance. That tests the comparison operator, which is the actual
        behaviour under test, instead of testing float64.
        """
        lat_offset = math.degrees(150.0 / EARTH_RADIUS_METERS)
        on_the_line = _site(lat=self.ORIGIN_LAT + lat_offset, lng=self.ORIGIN_LNG, contact_id=2)
        measured = haversine_meters(
            self.ORIGIN_LAT, self.ORIGIN_LNG, on_the_line.latitude or 0.0, self.ORIGIN_LNG
        )
        assert measured == pytest.approx(150.0, abs=1e-6)
        assert self._refine([on_the_line], radius_meters=measured) == [on_the_line]

    def test_a_hair_past_the_boundary_is_excluded(self) -> None:
        """The inclusive bound is exactly inclusive — one micrometre out is out."""
        lat_offset = math.degrees(150.0 / EARTH_RADIUS_METERS)
        on_the_line = _site(lat=self.ORIGIN_LAT + lat_offset, lng=self.ORIGIN_LNG, contact_id=2)
        measured = haversine_meters(
            self.ORIGIN_LAT, self.ORIGIN_LNG, on_the_line.latitude or 0.0, self.ORIGIN_LNG
        )
        assert self._refine([on_the_line], radius_meters=measured - 1e-6) == []

    def test_just_outside_the_radius_is_excluded(self) -> None:
        radius = 150.0
        lat_offset = math.degrees((radius + 5.0) / EARTH_RADIUS_METERS)
        just_outside = _site(lat=self.ORIGIN_LAT + lat_offset, lng=self.ORIGIN_LNG, contact_id=2)
        assert self._refine([just_outside], radius_meters=radius) == []

    def test_just_inside_the_radius_is_included(self) -> None:
        radius = 150.0
        lat_offset = math.degrees((radius - 5.0) / EARTH_RADIUS_METERS)
        just_inside = _site(lat=self.ORIGIN_LAT + lat_offset, lng=self.ORIGIN_LNG, contact_id=2)
        assert self._refine([just_inside], radius_meters=radius) == [just_inside]

    def test_box_corner_is_trimmed_by_the_circle(self) -> None:
        """A diagonal point inside the bounding box but outside the circle drops.

        This is the whole reason the refinement exists — the SQL prefilter would
        have returned this row.
        """
        radius = 150.0
        box = bounding_box(self.ORIGIN_LAT, self.ORIGIN_LNG, radius)
        corner = _site(lat=box.max_lat, lng=box.max_lng, contact_id=2)
        assert box.min_lat <= box.max_lat and box.min_lng <= box.max_lng
        assert haversine_meters(self.ORIGIN_LAT, self.ORIGIN_LNG, box.max_lat, box.max_lng) > radius
        assert self._refine([corner], radius_meters=radius) == []

    def test_zero_radius_keeps_only_the_exact_point(self) -> None:
        exact = _site(lat=self.ORIGIN_LAT, lng=self.ORIGIN_LNG, contact_id=2)
        near = _site(lat=self.ORIGIN_LAT + 0.0001, lng=self.ORIGIN_LNG, contact_id=3)
        assert self._refine([exact, near], radius_meters=0.0) == [exact]

    # ----- cap and ordering -------------------------------------------- #
    def test_results_are_nearest_first(self) -> None:
        far = _site(lat=self.ORIGIN_LAT + 0.0010, lng=self.ORIGIN_LNG, contact_id=2)
        near = _site(lat=self.ORIGIN_LAT + 0.0002, lng=self.ORIGIN_LNG, contact_id=3)
        middle = _site(lat=self.ORIGIN_LAT + 0.0006, lng=self.ORIGIN_LNG, contact_id=4)
        assert self._refine([far, near, middle], radius_meters=500.0) == [near, middle, far]

    def test_cap_keeps_the_closest_not_an_arbitrary_slice(self) -> None:
        sites = [
            _site(lat=self.ORIGIN_LAT + 0.0001 * step, lng=self.ORIGIN_LNG, contact_id=step)
            for step in range(10, 0, -1)
        ]
        matches = refine_candidates(
            sites,
            origin_lat=self.ORIGIN_LAT,
            origin_lng=self.ORIGIN_LNG,
            radius_meters=500.0,
            limit=3,
        )
        assert [match.row.contact_id for match in matches] == [1, 2, 3]

    def test_zero_limit_returns_nothing(self) -> None:
        site = _site(lat=self.ORIGIN_LAT, lng=self.ORIGIN_LNG, contact_id=2)
        assert (
            refine_candidates(
                [site],
                origin_lat=self.ORIGIN_LAT,
                origin_lng=self.ORIGIN_LNG,
                radius_meters=150.0,
                limit=0,
            )
            == []
        )

    def test_distance_is_reported_on_each_match(self) -> None:
        lat_offset = math.degrees(100.0 / EARTH_RADIUS_METERS)
        site = _site(lat=self.ORIGIN_LAT + lat_offset, lng=self.ORIGIN_LNG, contact_id=2)
        matches = refine_candidates(
            [site],
            origin_lat=self.ORIGIN_LAT,
            origin_lng=self.ORIGIN_LNG,
            radius_meters=150.0,
        )
        assert matches[0].distance_meters == pytest.approx(100.0, abs=0.1)

    def test_ordering_is_total_for_equidistant_sites(self) -> None:
        """Ties break on id, so a regenerate produces the same batch."""
        first = _site(
            lat=self.ORIGIN_LAT + 0.0004,
            lng=self.ORIGIN_LNG,
            contact_id=2,
            site_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
        )
        second = _site(
            lat=self.ORIGIN_LAT + 0.0004,
            lng=self.ORIGIN_LNG,
            contact_id=3,
            site_id=uuid.UUID("00000000-0000-0000-0000-000000000002"),
        )
        assert self._refine([second, first]) == [first, second]


# --------------------------------------------------------------------------- #
# Config clamping
# --------------------------------------------------------------------------- #
class TestClamping:
    """A misconfigured radius must degrade, never disable or run wild."""

    def test_radius_defaults_when_unset(self) -> None:
        assert clamp_radius_meters(None) == float(DEFAULT_RADIUS_METERS)

    def test_radius_is_clamped_to_the_supported_window(self) -> None:
        assert clamp_radius_meters(0) == float(MIN_RADIUS_METERS)
        assert clamp_radius_meters(-500) == float(MIN_RADIUS_METERS)
        assert clamp_radius_meters(150_000) == float(MAX_RADIUS_METERS)

    def test_radius_inside_the_window_is_untouched(self) -> None:
        assert clamp_radius_meters(250) == 250.0

    def test_max_neighbors_defaults_and_clamps(self) -> None:
        assert clamp_max_neighbors(None) == DEFAULT_MAX_NEIGHBORS
        assert clamp_max_neighbors(0) == 1
        assert clamp_max_neighbors(10_000) == MAX_NEIGHBORS_CEILING
        assert clamp_max_neighbors(25) == 25
