"""SMS-consent behavior of the public offer opt-in route (10DLC/TCR 803).

The consent checkbox is optional and unchecked by default: submitting without
it must succeed and must NOT mark the contact as SMS-opted-in. Only an
explicit ``sms_consent: true`` (with a phone number) records consent.
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_db
from app.api.v1 import offers as offers_module
from app.models.contact import Contact
from app.schemas.lead_source import LeadSubmitRequest
from app.schemas.offer import OptInRequest

WS_ID = uuid.uuid4()


def test_optin_request_defaults_consent_to_false() -> None:
    request = OptInRequest(phone_number="+15551234567")
    assert request.sms_consent is False


def test_lead_submit_request_defaults_consent_to_false() -> None:
    """Website lead form (10DLC CTA): omitting the checkbox must parse as False."""
    request = LeadSubmitRequest(first_name="Meg", phone_number="5551234567")
    assert request.sms_consent is False


def test_lead_submit_request_accepts_explicit_consent() -> None:
    request = LeadSubmitRequest(first_name="Meg", phone_number="5551234567", sms_consent=True)
    assert request.sms_consent is True


@asynccontextmanager
async def _test_lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield


def _make_offer() -> MagicMock:
    offer = MagicMock()
    offer.id = uuid.uuid4()
    offer.workspace_id = WS_ID
    offer.name = "Roof Special"
    offer.require_email = False
    offer.require_phone = True
    offer.require_name = False
    offer.opt_ins = 0
    return offer


def _result(scalar: object = None, scalars_all: list | None = None) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = scalar
    result.scalars.return_value.all.return_value = scalars_all or []
    return result


def _make_app(execute_results: list[MagicMock], db: AsyncMock) -> FastAPI:
    db.execute = AsyncMock(side_effect=execute_results)
    # The auto-pipeline helper loads the workspace via db.get; return one with
    # the feature disabled so opt-in consent tests stay focused (the helper
    # early-returns without consuming the execute sequence).
    disabled_ws = MagicMock()
    disabled_ws.settings = {"auto_pipeline": {"enabled": False}}
    db.get = AsyncMock(return_value=disabled_ws)
    app = FastAPI(lifespan=_test_lifespan)
    app.include_router(offers_module.public_router, prefix="/api/v1/p/offers")

    async def override_db() -> AsyncIterator[AsyncMock]:
        yield db

    app.dependency_overrides[get_db] = override_db
    return app


async def _post_optin(app: FastAPI, payload: dict) -> object:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        return await client.post("/api/v1/p/offers/roof-special/opt-in", json=payload)


@pytest.fixture
def db() -> AsyncMock:
    return AsyncMock()


async def test_submit_without_consent_succeeds_and_does_not_opt_in(db: AsyncMock) -> None:
    """The checkbox is optional — omitting it must not block or force opt-in."""
    offer = _make_offer()
    # offer lookup → no contact by phone → no lead magnets
    app = _make_app([_result(offer), _result(None), _result(None, [])], db)

    response = await _post_optin(app, {"phone_number": "+15551234567", "name": "Meg Z"})

    assert response.status_code == 200
    created = db.add.call_args[0][0]
    assert isinstance(created, Contact)
    # Default column value applies ("unknown") — consent must NOT be set here.
    assert created.sms_consent_status != "opted_in"
    assert created.sms_consent_collected_at is None


async def test_submit_with_consent_records_opt_in(db: AsyncMock) -> None:
    offer = _make_offer()
    app = _make_app([_result(offer), _result(None), _result(None, [])], db)

    response = await _post_optin(
        app,
        {"phone_number": "+15551234567", "name": "Meg Z", "sms_consent": True},
    )

    assert response.status_code == 200
    created = db.add.call_args[0][0]
    assert created.sms_consent_status == "opted_in"
    assert created.sms_consent_source == "offer:roof-special"
    assert created.sms_consent_collected_at is not None


async def test_consent_without_phone_is_not_recorded(db: AsyncMock) -> None:
    """A ticked box with no phone number can't be SMS consent."""
    offer = _make_offer()
    offer.require_phone = False
    app = _make_app([_result(offer), _result(None), _result(None, [])], db)

    response = await _post_optin(
        app,
        {"email": "meg@example.com", "sms_consent": True},
    )

    assert response.status_code == 200
    created = db.add.call_args[0][0]
    assert created.sms_consent_status != "opted_in"


async def test_unchecked_box_never_downgrades_existing_consent(db: AsyncMock) -> None:
    existing = MagicMock()
    existing.id = 42
    existing.sms_consent_status = "opted_in"
    offer = _make_offer()
    offer.require_email = True
    # offer lookup → contact found by email → no lead magnets
    app = _make_app([_result(offer), _result(existing), _result(None, [])], db)

    response = await _post_optin(
        app,
        {"email": "meg@example.com", "phone_number": "+15551234567"},
    )

    assert response.status_code == 200
    assert existing.sms_consent_status == "opted_in"
