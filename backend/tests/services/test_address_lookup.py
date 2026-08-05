"""Address autocomplete provider behaviour.

Both upstreams are stubbed with ``httpx.MockTransport``: what matters here is
that a real provider payload lands in the contact's address columns correctly,
and that a broken upstream degrades instead of exploding.
"""

import httpx
import pytest

from app.services.addresses.address_lookup import (
    AddressLookupError,
    AddressLookupService,
)


def _service_with(handler, *, api_key: str = "") -> AddressLookupService:
    service = AddressLookupService(api_key=api_key)
    service._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return service


# --- provider selection ----------------------------------------------------


def test_provider_is_census_without_a_key() -> None:
    assert AddressLookupService(api_key="").provider == "census"


def test_provider_is_google_when_a_key_is_configured() -> None:
    assert AddressLookupService(api_key="test-key").provider == "google_places"


# --- census ----------------------------------------------------------------

CENSUS_MATCH = {
    "result": {
        "addressMatches": [
            {
                "matchedAddress": "1600 PENNSYLVANIA AVE NW, WASHINGTON, DC, 20500",
                "addressComponents": {
                    "fromAddress": "1600",
                    "preDirection": "",
                    "preType": "",
                    "streetName": "PENNSYLVANIA",
                    "suffixType": "AVE",
                    "suffixDirection": "NW",
                    "city": "WASHINGTON",
                    "state": "DC",
                    "zip": "20500",
                },
            }
        ]
    }
}


async def test_census_suggestion_carries_structured_parts() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "geocoding.geo.census.gov" in str(request.url)
        assert request.url.params["benchmark"] == "Public_AR_Current"
        return httpx.Response(200, json=CENSUS_MATCH)

    service = _service_with(handler)
    suggestions = await service.suggest("1600 pennsylvania ave")
    await service.close()

    assert len(suggestions) == 1
    suggestion = suggestions[0]
    # Resolvable without a second round trip — the census candidate list is
    # already structured, so picking a row must not need another call.
    assert suggestion.parts is not None
    assert suggestion.parts.address_line1 == "1600 Pennsylvania Ave NW"
    assert suggestion.parts.address_city == "Washington"
    assert suggestion.parts.address_state == "DC"
    assert suggestion.parts.address_zip == "20500"
    assert suggestion.id.startswith("census:")


async def test_census_empty_result_returns_no_suggestions() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"result": {"addressMatches": []}})

    service = _service_with(handler)
    assert await service.suggest("nowhere at all") == []
    await service.close()


# --- google ----------------------------------------------------------------

GOOGLE_AUTOCOMPLETE = {
    "suggestions": [
        {
            "placePrediction": {
                "placeId": "ChIJ123",
                "text": {"text": "1600 Amphitheatre Pkwy, Mountain View, CA, USA"},
                "structuredFormat": {
                    "mainText": {"text": "1600 Amphitheatre Pkwy"},
                    "secondaryText": {"text": "Mountain View, CA, USA"},
                },
            }
        },
        # A query prediction (no placePrediction) must not become a dead row.
        {"queryPrediction": {"text": {"text": "amphitheatre parkway"}}},
    ]
}

GOOGLE_DETAILS = {
    "formattedAddress": "1600 Amphitheatre Pkwy, Mountain View, CA 94043, USA",
    "addressComponents": [
        {"longText": "1600", "shortText": "1600", "types": ["street_number"]},
        {"longText": "Amphitheatre Parkway", "shortText": "Amphitheatre Pkwy", "types": ["route"]},
        {"longText": "Mountain View", "shortText": "Mountain View", "types": ["locality"]},
        {
            "longText": "California",
            "shortText": "CA",
            "types": ["administrative_area_level_1"],
        },
        {"longText": "94043", "shortText": "94043", "types": ["postal_code"]},
    ],
}


async def test_google_suggestions_skip_query_predictions_and_carry_no_parts() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["api_key"] = request.headers.get("X-Goog-Api-Key")
        return httpx.Response(200, json=GOOGLE_AUTOCOMPLETE)

    service = _service_with(handler, api_key="test-key")
    suggestions = await service.suggest("1600 amphi", session_token="session-1")
    await service.close()

    assert seen["api_key"] == "test-key"
    assert "places:autocomplete" in str(seen["url"])
    assert len(suggestions) == 1
    assert suggestions[0].id == "google:ChIJ123"
    assert suggestions[0].label == "1600 Amphitheatre Pkwy"
    assert suggestions[0].description == "Mountain View, CA, USA"
    # Google parts arrive only on resolve, which is what keeps one address entry
    # inside a single billed autocomplete session.
    assert suggestions[0].parts is None


async def test_google_resolve_maps_components_onto_contact_columns() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/places/ChIJ123")
        assert request.url.params["sessionToken"] == "session-1"
        return httpx.Response(200, json=GOOGLE_DETAILS)

    service = _service_with(handler, api_key="test-key")
    parts = await service.resolve("google:ChIJ123", session_token="session-1")
    await service.close()

    assert parts is not None
    assert parts.address_line1 == "1600 Amphitheatre Parkway"
    assert parts.address_city == "Mountain View"
    assert parts.address_state == "CA"
    assert parts.address_zip == "94043"


async def test_resolve_ignores_ids_from_another_provider() -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - must not run
        raise AssertionError("census ids must never reach the Google upstream")

    service = _service_with(handler, api_key="test-key")
    assert await service.resolve("census:0") is None
    await service.close()


async def test_resolve_rejects_a_place_id_that_could_traverse_the_url() -> None:
    # The id lands in a URL path, and httpx normalises `..` segments — an
    # unchecked id would aim our API key at an arbitrary Google endpoint.
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - must not run
        raise AssertionError(f"traversal id must never be requested: {request.url}")

    service = _service_with(handler, api_key="test-key")
    assert await service.resolve("google:../../v1/places:searchText") is None
    assert await service.resolve("google:") is None
    await service.close()


# --- failure modes ---------------------------------------------------------


async def test_upstream_error_raises_a_typed_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="upstream down")

    service = _service_with(handler)
    with pytest.raises(AddressLookupError):
        await service.suggest("1600 pennsylvania ave")
    await service.close()


async def test_blank_query_never_calls_the_provider() -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - must not run
        raise AssertionError("a blank query must not cost a provider call")

    service = _service_with(handler, api_key="test-key")
    assert await service.suggest("   ") == []
    await service.close()
