"""Elementor webhook compatibility tests for the public lead endpoint."""

from collections.abc import AsyncIterator

import pytest
from fastapi import APIRouter, FastAPI, HTTPException, Request, status
from httpx import ASGITransport, AsyncClient

from app.api.v1.elementor_webhook import (
    ELEMENTOR_FORM_CONTENT_TYPE,
    ELEMENTOR_REQUEST_BODY_OPENAPI,
    MAX_ELEMENTOR_BODY_BYTES,
    ElementorLeadFormRoute,
    validate_elementor_webhook_origin,
)
from app.core.origin_validation import validate_origin
from app.schemas.lead_source import LeadSubmitRequest

ALLOWED_DOMAIN = "maxteriorslighting.com"
WORDPRESS_USER_AGENT = "WordPress/7.0.4; https://maxteriorslighting.com"


def _build_app() -> FastAPI:
    app = FastAPI()
    router = APIRouter(route_class=ElementorLeadFormRoute)

    @router.post("/lead", openapi_extra=ELEMENTOR_REQUEST_BODY_OPENAPI)
    async def submit(body: LeadSubmitRequest, request: Request) -> dict[str, object]:
        if not validate_origin(request, [ALLOWED_DOMAIN]) and not (
            validate_elementor_webhook_origin(
                request,
                [ALLOWED_DOMAIN],
                landing_page=body.landing_page,
            )
        ):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Origin not allowed")
        return body.model_dump(mode="json")

    app.include_router(router)
    return app


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=_build_app())
    async with AsyncClient(transport=transport, base_url="http://test") as test_client:
        yield test_client


@pytest.mark.asyncio
async def test_native_elementor_payload_is_normalized(client: AsyncClient) -> None:
    response = await client.post(
        "/lead",
        headers={"User-Agent": WORDPRESS_USER_AGENT},
        data={
            "Full Name": "Taylor Test Lead",
            "Phone": "(586) 555-0101",
            "Email": "taylor@example.com",
            "Address": "14040 Pernell Dr, Sterling Heights, MI 48313",
            "Message": "Interested in permanent roofline lighting.",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["first_name"] == "Taylor"
    assert body["last_name"] == "Test Lead"
    assert body["phone_number"] == "+15865550101"
    assert body["email"] == "taylor@example.com"
    assert body["address"] == "14040 Pernell Dr, Sterling Heights, MI 48313"
    assert body["notes"] == "Interested in permanent roofline lighting."
    assert body["sms_consent"] is False


@pytest.mark.asyncio
async def test_checked_consent_and_advanced_page_metadata_are_preserved(
    client: AsyncClient,
) -> None:
    response = await client.post(
        "/lead",
        headers={"User-Agent": WORDPRESS_USER_AGENT},
        data={
            "Full Name": "Sam Sample",
            "Phone": "586-555-0102",
            "SMS Consent": "on",
            "Page URL": "https://maxteriorslighting.com/1-test-page/?utm_source=google",
            "Referrer": "https://www.google.com/",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["sms_consent"] is True
    assert body["landing_page"].startswith("https://maxteriorslighting.com/1-test-page/")
    assert body["referrer"] == "https://www.google.com/"


@pytest.mark.asyncio
async def test_existing_browser_json_contract_is_unchanged(client: AsyncClient) -> None:
    response = await client.post(
        "/lead",
        headers={"Origin": "https://maxteriorslighting.com"},
        json={"first_name": "Jordan", "phone_number": "5865550103"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["phone_number"] == "+15865550103"


@pytest.mark.asyncio
async def test_form_post_rejects_untrusted_wordpress_site(client: AsyncClient) -> None:
    response = await client.post(
        "/lead",
        headers={"User-Agent": "WordPress/7.0.4; https://attacker.example"},
        data={"Full Name": "Bad Actor", "Phone": "5865550104"},
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_advanced_page_url_must_match_wordpress_site(client: AsyncClient) -> None:
    response = await client.post(
        "/lead",
        headers={"User-Agent": WORDPRESS_USER_AGENT},
        data={
            "Full Name": "Bad Page",
            "Phone": "5865550105",
            "Page URL": "https://attacker.example/fake-form/",
        },
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_missing_required_elementor_fields_returns_validation_error(
    client: AsyncClient,
) -> None:
    response = await client.post(
        "/lead",
        headers={"User-Agent": WORDPRESS_USER_AGENT},
        data={"Email": "nobody@example.com"},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_too_many_elementor_fields_are_rejected(client: AsyncClient) -> None:
    response = await client.post(
        "/lead",
        headers={"User-Agent": WORDPRESS_USER_AGENT},
        data={f"Field {index}": "value" for index in range(51)},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_invalid_elementor_encoding_is_rejected(client: AsyncClient) -> None:
    response = await client.post(
        "/lead",
        headers={
            "User-Agent": WORDPRESS_USER_AGENT,
            "Content-Type": ELEMENTOR_FORM_CONTENT_TYPE,
        },
        content=b"Full+Name=Invalid&Phone=5865550106&Message=\xff",
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_oversized_elementor_payload_is_rejected(client: AsyncClient) -> None:
    response = await client.post(
        "/lead",
        headers={
            "User-Agent": WORDPRESS_USER_AGENT,
            "Content-Type": ELEMENTOR_FORM_CONTENT_TYPE,
        },
        content=b"Message=" + (b"x" * MAX_ELEMENTOR_BODY_BYTES),
    )

    assert response.status_code == 413


def test_openapi_documents_json_and_elementor_content_types() -> None:
    request_content = _build_app().openapi()["paths"]["/lead"]["post"]["requestBody"]["content"]

    assert "application/json" in request_content
    assert ELEMENTOR_FORM_CONTENT_TYPE in request_content
