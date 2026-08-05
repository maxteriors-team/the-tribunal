"""Address autocomplete for operator-entered mailing addresses.

Two providers behind one shape, picked at call time:

* **Google Places Autocomplete (New)** whenever ``GOOGLE_PLACES_API_KEY`` is
  configured. True as-you-type prefix matching, worldwide. Billed, so calls are
  grouped into a session (see ``session_token``) and rate limited at the API
  boundary.
* **US Census geocoder** otherwise. Keyless, free, no signup — but it is a
  *geocoder*, not a prefix matcher: it only answers once enough of the address
  is typed, and only for US addresses. That makes it a usable floor rather than
  an equal substitute, so the field degrades instead of disappearing on a
  workspace that never bought a Places key.

Both return :class:`AddressSuggestion` values whose ``parts`` map field-for-field
onto the contact address columns. The Census provider fills ``parts`` inline
(its candidate list is already structured); Google needs a second Place Details
call, which is what ``resolve`` is for.

The API key is never handed to the browser — the frontend only ever talks to
this service through the workspace-scoped endpoints in
``app/api/v1/addresses.py``.
"""

import re
from typing import Any

import httpx
import structlog

from app.core.config import settings
from app.schemas.address import (
    AddressParts,
    AddressProvider,
    AddressSuggestion,
)

logger = structlog.get_logger()

GOOGLE_PLACES_BASE_URL = "https://places.googleapis.com/v1"
CENSUS_GEOCODER_URL = "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"
CENSUS_BENCHMARK = "Public_AR_Current"

MAX_SUGGESTIONS = 6

# An interactive typeahead: a slow answer is worse than no answer, because the
# operator has already typed past it. Deliberately far tighter than the batch
# scraping timeouts in `services/scraping/google_places.py`.
_TIMEOUT = httpx.Timeout(connect=3.0, read=6.0, write=3.0, pool=3.0)

# Suggestion ids carry their provider so a resolve can never be steered at the
# wrong upstream by a hand-crafted id.
_GOOGLE_PREFIX = "google:"
_CENSUS_PREFIX = "census:"

# Google address component types, most specific first, mapped onto our columns.
_GOOGLE_CITY_TYPES = ("locality", "postal_town", "sublocality_level_1", "sublocality")

# Place ids are opaque, but they go into a URL *path*. Without this an id
# containing `../` would be normalised by the client into a call to a different
# Google endpoint, with our API key attached.
_GOOGLE_PLACE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,255}$")


class AddressLookupError(Exception):
    """Upstream address provider failed or was unreachable."""


def _clean(value: str) -> str:
    return " ".join(value.split())


def _titlecase_address(value: str) -> str:
    """Present the Census geocoder's SHOUTED output as a normal address.

    Street directionals and two-letter state codes stay upper case, so
    ``1600 PENNSYLVANIA AVE NW`` reads ``1600 Pennsylvania Ave NW`` rather than
    ``1600 Pennsylvania Ave Nw``.
    """
    directionals = {"N", "S", "E", "W", "NE", "NW", "SE", "SW"}
    words = []
    for word in value.split():
        if word.upper() in directionals:
            words.append(word.upper())
        elif any(char.isdigit() for char in word):
            words.append(word.upper() if word.isalpha() else word)
        else:
            words.append(word.capitalize())
    return " ".join(words)


class AddressLookupService:
    """Provider-agnostic address suggestions for a single request."""

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = (api_key if api_key is not None else settings.google_places_api_key).strip()
        self.log = logger.bind(component="address_lookup")
        self._client: httpx.AsyncClient | None = None

    @property
    def provider(self) -> AddressProvider:
        """Which upstream a lookup would use right now."""
        return "google_places" if self.api_key else "census"

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=_TIMEOUT)
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # -- suggest ------------------------------------------------------------

    async def suggest(
        self,
        query: str,
        *,
        session_token: str | None = None,
    ) -> list[AddressSuggestion]:
        """Return address candidates for a partially typed address."""
        text = _clean(query)
        if not text:
            return []

        if self.provider == "google_places":
            return await self._suggest_google(text, session_token=session_token)
        return await self._suggest_census(text)

    async def _suggest_google(
        self,
        query: str,
        *,
        session_token: str | None,
    ) -> list[AddressSuggestion]:
        payload: dict[str, Any] = {"input": query}
        if session_token:
            payload["sessionToken"] = session_token

        data = await self._request(
            "POST",
            f"{GOOGLE_PLACES_BASE_URL}/places:autocomplete",
            json=payload,
            headers={
                "X-Goog-Api-Key": self.api_key,
                "Content-Type": "application/json",
                "X-Goog-FieldMask": ",".join(
                    [
                        "suggestions.placePrediction.placeId",
                        "suggestions.placePrediction.text.text",
                        "suggestions.placePrediction.structuredFormat.mainText.text",
                        "suggestions.placePrediction.structuredFormat.secondaryText.text",
                    ]
                ),
            },
        )

        suggestions: list[AddressSuggestion] = []
        for entry in data.get("suggestions", [])[:MAX_SUGGESTIONS]:
            prediction = entry.get("placePrediction") or {}
            place_id = prediction.get("placeId")
            if not place_id:
                continue
            structured = prediction.get("structuredFormat") or {}
            main = (structured.get("mainText") or {}).get("text") or ""
            secondary = (structured.get("secondaryText") or {}).get("text") or ""
            full = (prediction.get("text") or {}).get("text") or ""
            suggestions.append(
                AddressSuggestion(
                    id=f"{_GOOGLE_PREFIX}{place_id}",
                    label=main or full,
                    description=secondary,
                )
            )
        return suggestions

    async def _suggest_census(self, query: str) -> list[AddressSuggestion]:
        data = await self._request(
            "GET",
            CENSUS_GEOCODER_URL,
            params={"address": query, "benchmark": CENSUS_BENCHMARK, "format": "json"},
        )

        matches = (data.get("result") or {}).get("addressMatches") or []
        suggestions: list[AddressSuggestion] = []
        for index, match in enumerate(matches[:MAX_SUGGESTIONS]):
            parts = self._census_parts(match)
            if not parts.address_line1:
                continue
            city_state = ", ".join(p for p in (parts.address_city, parts.address_state) if p)
            suggestions.append(
                AddressSuggestion(
                    id=f"{_CENSUS_PREFIX}{index}",
                    label=parts.address_line1,
                    description=_clean(f"{city_state} {parts.address_zip}".strip()),
                    parts=parts,
                )
            )
        return suggestions

    @staticmethod
    def _census_parts(match: dict[str, Any]) -> AddressParts:
        components = match.get("addressComponents") or {}
        street = _clean(
            " ".join(
                str(components.get(key) or "")
                for key in (
                    "fromAddress",
                    "preQualifier",
                    "preDirection",
                    "preType",
                    "streetName",
                    "suffixType",
                    "suffixDirection",
                    "suffixQualifier",
                )
            )
        )
        return AddressParts(
            address_line1=_titlecase_address(street),
            address_city=_titlecase_address(_clean(str(components.get("city") or ""))),
            address_state=_clean(str(components.get("state") or "")).upper(),
            address_zip=_clean(str(components.get("zip") or "")),
        )

    # -- resolve ------------------------------------------------------------

    async def resolve(
        self,
        suggestion_id: str,
        *,
        session_token: str | None = None,
    ) -> AddressParts | None:
        """Return the structured address behind a suggestion id.

        ``None`` means the id belongs to a provider that already returned its
        parts inline (Census) or is not one of ours — never a silent failure,
        which is raised as :class:`AddressLookupError`.
        """
        if not suggestion_id.startswith(_GOOGLE_PREFIX):
            return None

        place_id = suggestion_id[len(_GOOGLE_PREFIX) :]
        if not self.api_key or not _GOOGLE_PLACE_ID_RE.match(place_id):
            return None

        params = {"sessionToken": session_token} if session_token else None
        data = await self._request(
            "GET",
            f"{GOOGLE_PLACES_BASE_URL}/places/{place_id}",
            params=params,
            headers={
                "X-Goog-Api-Key": self.api_key,
                "X-Goog-FieldMask": "addressComponents,formattedAddress",
            },
        )
        return self._google_parts(data)

    @staticmethod
    def _google_parts(place: dict[str, Any]) -> AddressParts:
        by_type: dict[str, dict[str, str]] = {}
        for component in place.get("addressComponents") or []:
            for component_type in component.get("types") or []:
                by_type.setdefault(component_type, component)

        def long_text(*types: str) -> str:
            for component_type in types:
                component = by_type.get(component_type)
                if component and component.get("longText"):
                    return str(component["longText"])
            return ""

        def short_text(component_type: str) -> str:
            component = by_type.get(component_type)
            if component and component.get("shortText"):
                return str(component["shortText"])
            return ""

        line1 = _clean(f"{long_text('street_number')} {long_text('route')}")
        # A place with no street address at all (a city, a park) would otherwise
        # fill line 1 with nothing; fall back to the name Google shows so the
        # operator never gets a silently blank field after picking a row.
        if not line1:
            line1 = _clean(str(place.get("formattedAddress") or "").split(",")[0])

        return AddressParts(
            address_line1=line1,
            address_line2=long_text("subpremise"),
            address_city=long_text(*_GOOGLE_CITY_TYPES),
            address_state=short_text("administrative_area_level_1"),
            address_zip=long_text("postal_code"),
        )

    # -- transport ----------------------------------------------------------

    async def _request(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        client = await self._get_client()
        try:
            response = await client.request(method, url, **kwargs)
        except httpx.HTTPError as exc:
            self.log.warning(
                "address_lookup_transport_error", provider=self.provider, error=str(exc)
            )
            raise AddressLookupError(f"Address provider unreachable: {exc}") from exc

        if response.status_code >= 400:
            # The body can echo the API key back on an auth failure, so only the
            # status reaches the logs.
            self.log.warning(
                "address_lookup_http_error",
                provider=self.provider,
                status_code=response.status_code,
            )
            raise AddressLookupError(f"Address provider returned HTTP {response.status_code}")

        try:
            payload = response.json()
        except ValueError as exc:
            raise AddressLookupError("Address provider returned a non-JSON response") from exc

        if not isinstance(payload, dict):
            raise AddressLookupError("Address provider returned an unexpected payload")
        return payload
