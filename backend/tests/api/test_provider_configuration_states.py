"""Provider-backed routes return actionable configuration errors."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.api.v1 import find_leads_ai as find_leads_ai_api
from app.api.v1 import phone_numbers as phone_numbers_api
from app.api.v1 import prospects as prospects_api
from app.core.config import settings
from app.schemas.find_leads_ai import AIImportLeadsRequest
from app.schemas.phone_number import SearchPhoneNumbersRequest
from app.schemas.prospect_search import PeopleDiscoveryRequest
from app.schemas.scraping import BusinessResult, BusinessSearchRequest
from app.services.ai.openai_credentials import OpenAICredentialError
from app.services.exceptions import ServiceUnavailableError
from app.services.scraping.google_places import GooglePlacesNotConfiguredError


@pytest.mark.asyncio
async def test_telnyx_search_returns_machine_readable_setup_error(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "telnyx_api_key", "")

    integration_result = MagicMock()
    integration_result.scalar_one_or_none.return_value = None
    db = AsyncMock()
    db.execute.return_value = integration_result

    with pytest.raises(HTTPException) as exc_info:
        await phone_numbers_api.search_phone_numbers(
            uuid.uuid4(),
            SearchPhoneNumbersRequest(area_code="512"),
            SimpleNamespace(),
            db,
            SimpleNamespace(),
        )

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail["code"] == "telnyx_provider_not_configured"
    assert exc_info.value.detail["details"]["action"] == "search for phone numbers"


@pytest.mark.asyncio
async def test_ai_search_distinguishes_missing_scraping_provider(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        find_leads_ai_api,
        "enforce_scraping_rate_limit",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        find_leads_ai_api.GooglePlacesService,
        "search_businesses",
        AsyncMock(side_effect=GooglePlacesNotConfiguredError("not configured")),
    )
    monkeypatch.setattr(
        find_leads_ai_api.GooglePlacesService, "close", AsyncMock(return_value=None)
    )

    with pytest.raises(HTTPException) as exc_info:
        await find_leads_ai_api.search_businesses_ai(
            uuid.uuid4(),
            BusinessSearchRequest(query="roofers in Austin"),
            SimpleNamespace(),
            AsyncMock(),
            SimpleNamespace(),
        )

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail["code"] == "scraping_provider_not_configured"
    assert exc_info.value.detail["details"]["provider"] == "google_places"


@pytest.mark.asyncio
async def test_ai_import_distinguishes_missing_openai_provider(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "enable_ai_enrichment", True)
    monkeypatch.setattr(
        find_leads_ai_api,
        "create_workspace_openai_client",
        AsyncMock(side_effect=OpenAICredentialError("not configured")),
    )
    workspace = SimpleNamespace(id=uuid.uuid4())
    request = AIImportLeadsRequest(
        leads=[
            BusinessResult(
                place_id="place-1",
                name="Acme Roofing",
                website="https://acme.example",
            )
        ],
        enable_enrichment=True,
    )

    with pytest.raises(HTTPException) as exc_info:
        await find_leads_ai_api.import_leads_ai(
            workspace.id,
            request,
            SimpleNamespace(),
            AsyncMock(),
            workspace,
        )

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail["code"] == "openai_provider_not_configured"
    assert exc_info.value.detail["details"]["action"] == "enrich"


@pytest.mark.asyncio
async def test_people_query_requires_company_search_provider(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "google_places_api_key", "")

    with pytest.raises(ServiceUnavailableError) as exc_info:
        await prospects_api.launch_people_discovery(
            uuid.uuid4(),
            PeopleDiscoveryRequest(query="roofers in Austin"),
            SimpleNamespace(id=uuid.uuid4()),
            AsyncMock(),
            SimpleNamespace(),
        )

    assert exc_info.value.code == "people_search_provider_not_configured"
    assert exc_info.value.details["provider"] == "google_places"
