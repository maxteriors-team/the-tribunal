"""Compatibility layer for Elementor Pro's server-side form webhooks.

Elementor sends ``application/x-www-form-urlencoded`` fields keyed by their
human-readable labels or, in Advanced Data mode, nested ``fields``/``meta``
records. The public lead endpoint otherwise uses a typed JSON contract. This
route adapter normalizes Elementor's payload before FastAPI
performs normal Pydantic validation, so the endpoint keeps one canonical model
and one OpenAPI operation.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Coroutine, Mapping
from typing import Any
from urllib.parse import parse_qsl, urlparse

from fastapi import HTTPException, Request, status
from fastapi.routing import APIRoute
from starlette.datastructures import MutableHeaders
from starlette.responses import Response

from app.core.origin_validation import is_allowed_origin

ELEMENTOR_FORM_CONTENT_TYPE = "application/x-www-form-urlencoded"
MAX_ELEMENTOR_BODY_BYTES = 64 * 1024
MAX_ELEMENTOR_FIELDS = 100
_ELEMENTOR_ADVANCED_PART = re.compile(
    r"^(fields|meta)\[([^\[\]]+)\]\[(title|value|raw_value)\](?:\[\])?$"
)

ELEMENTOR_REQUEST_BODY_OPENAPI: dict[str, Any] = {
    "requestBody": {
        "content": {
            ELEMENTOR_FORM_CONTENT_TYPE: {
                "schema": {
                    "type": "object",
                    "required": ["Full Name", "Phone"],
                    "properties": {
                        "Full Name": {"type": "string"},
                        "Phone": {"type": "string"},
                        "Email": {"type": "string", "format": "email"},
                        "Address": {"type": "string"},
                        "Message": {"type": "string"},
                        "SMS Consent": {"type": "string"},
                        "Page URL": {"type": "string", "format": "uri"},
                        "Referrer": {"type": "string", "format": "uri"},
                    },
                }
            }
        }
    }
}


def _field_key(value: str) -> str:
    """Normalize labels/IDs without accepting fuzzy substring matches."""
    return "".join(character for character in value.casefold() if character.isalnum())


def _field_value(fields: Mapping[str, str], *aliases: str) -> str | None:
    for alias in aliases:
        value = fields.get(_field_key(alias))
        if value is not None and value.strip():
            return value.strip()
    return None


def _checked(value: str | None) -> bool:
    """Interpret an Elementor checkbox; unchecked fields are normally omitted."""
    if value is None:
        return False
    return value.strip().casefold() not in {"", "0", "false", "no", "off", "unchecked"}


def _flatten_elementor_fields(form_fields: Mapping[str, str]) -> dict[str, str]:
    """Flatten Elementor Basic and Advanced Data into label-keyed values."""
    flat_fields: dict[str, str] = {}
    advanced_parts: dict[tuple[str, str], dict[str, str]] = {}

    for key, value in form_fields.items():
        match = _ELEMENTOR_ADVANCED_PART.fullmatch(key)
        if match:
            section, item_id, part = match.groups()
            advanced_parts.setdefault((section, item_id), {})[part] = value
        elif "[" not in key:
            flat_fields[key] = value

    for parts in advanced_parts.values():
        title = parts.get("title")
        field_value = parts.get("value", parts.get("raw_value"))
        if title and field_value is not None:
            flat_fields[title] = field_value

    return flat_fields


def normalize_elementor_payload(form_fields: Mapping[str, str]) -> dict[str, Any]:
    """Map Elementor field labels to the canonical public lead JSON contract."""
    flattened = _flatten_elementor_fields(form_fields)
    fields = {_field_key(label): value for label, value in flattened.items()}
    payload: dict[str, Any] = {}

    first_name = _field_value(fields, "First Name", "First")
    last_name = _field_value(fields, "Last Name", "Last")
    if not first_name:
        full_name = _field_value(fields, "Full Name", "Name")
        if full_name:
            name_parts = full_name.split(maxsplit=1)
            first_name = name_parts[0]
            if len(name_parts) == 2 and not last_name:
                last_name = name_parts[1]

    scalar_fields: tuple[tuple[str, str | None], ...] = (
        ("first_name", first_name),
        ("last_name", last_name),
        ("phone_number", _field_value(fields, "Phone Number", "Phone", "Phone No", "Mobile")),
        ("email", _field_value(fields, "Email", "Email Address")),
        ("company_name", _field_value(fields, "Company Name", "Company")),
        ("address", _field_value(fields, "Address", "Property Address", "Service Address")),
        ("notes", _field_value(fields, "Message", "Project Details", "Comments", "Notes")),
        ("source_detail", _field_value(fields, "Source Detail")),
        ("utm_source", _field_value(fields, "UTM Source")),
        ("utm_medium", _field_value(fields, "UTM Medium")),
        ("utm_campaign", _field_value(fields, "UTM Campaign")),
        ("utm_content", _field_value(fields, "UTM Content")),
        ("utm_term", _field_value(fields, "UTM Term")),
        ("gclid", _field_value(fields, "GCLID", "Google Click ID")),
        ("fbclid", _field_value(fields, "FBCLID", "Facebook Click ID")),
        ("landing_page", _field_value(fields, "Page URL", "Landing Page")),
        ("referrer", _field_value(fields, "Referrer", "Referer")),
    )
    for key, value in scalar_fields:
        if value is not None:
            payload[key] = value

    consent = _field_value(
        fields,
        "SMS Consent",
        "Text Consent",
        "Text Message Consent",
        "I Agree To Receive Text Messages",
    )
    if consent is not None:
        payload["sms_consent"] = _checked(consent)

    return payload


def _wordpress_site_from_user_agent(user_agent: str) -> str | None:
    """Extract the site URL from WordPress's standard webhook user agent."""
    product, separator, site_url = user_agent.partition(";")
    if not separator or not product.strip().casefold().startswith("wordpress/"):
        return None
    site_url = site_url.strip()
    try:
        parsed = urlparse(site_url)
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    return site_url


def validate_elementor_webhook_origin(
    request: Request,
    allowed_domains: list[str],
    *,
    landing_page: str | None = None,
) -> bool:
    """Authorize a normalized server-to-server WordPress webhook.

    Browsers cannot set ``User-Agent`` themselves. A non-browser caller can
    spoof it, so this check remains paired with the source-specific public key
    and the endpoint's database-backed rate limit. If Elementor Advanced Data
    includes a page URL, that URL must agree with the same domain allowlist.
    """
    if request.headers.get("origin"):
        return False
    wordpress_site = getattr(request.state, "elementor_wordpress_site", None)
    if not isinstance(wordpress_site, str) or not is_allowed_origin(
        wordpress_site, allowed_domains
    ):
        return False
    return landing_page is None or is_allowed_origin(landing_page, allowed_domains)


def _elementor_form_data(raw_body: bytes) -> dict[str, Any]:
    if len(raw_body) > MAX_ELEMENTOR_BODY_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="Form submission is too large",
        )
    try:
        pairs = parse_qsl(
            raw_body.decode("utf-8"),
            keep_blank_values=True,
            max_num_fields=MAX_ELEMENTOR_FIELDS,
        )
    except (UnicodeDecodeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Invalid form submission",
        ) from exc
    return normalize_elementor_payload(dict(pairs))


def _json_request(request: Request, body: bytes, wordpress_site: str | None) -> Request:
    scope = dict(request.scope)
    scope["headers"] = list(scope.get("headers") or [])
    scope["state"] = dict(scope.get("state") or {})
    scope["state"]["elementor_wordpress_site"] = wordpress_site
    headers = MutableHeaders(scope=scope)
    headers["content-type"] = "application/json"
    headers["content-length"] = str(len(body))
    sent = False

    async def receive() -> dict[str, Any]:
        nonlocal sent
        if sent:
            return {"type": "http.request", "body": b"", "more_body": False}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(scope, receive)


class ElementorLeadFormRoute(APIRoute):
    """Normalize Elementor POST bodies before FastAPI validates the endpoint."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original_handler = super().get_route_handler()

        async def route_handler(request: Request) -> Response:
            content_type = request.headers.get("content-type", "").partition(";")[0].strip().lower()
            if request.method == "POST" and content_type == ELEMENTOR_FORM_CONTENT_TYPE:
                normalized = _elementor_form_data(await request.body())
                encoded = json.dumps(normalized, separators=(",", ":")).encode("utf-8")
                wordpress_site = _wordpress_site_from_user_agent(
                    request.headers.get("user-agent", "")
                )
                request = _json_request(request, encoded, wordpress_site)
            return await original_handler(request)

        return route_handler
