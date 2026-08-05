"""Address autocomplete for operator-entered addresses.

Mounted under a workspace and readable by any member: the operator typing a
customer's address is the same person allowed to read the contact record. The
provider API key stays server-side, and each call is metered per workspace
because the Google-backed path is billed.

A provider failure returns an empty candidate list rather than an error. The
address field is a plain text input with a suggestion list bolted on, so a dead
upstream must degrade to "type it yourself", never block the contact from being
saved.
"""

from fastapi import APIRouter, Query

from app.api.deps import CanReadCRM, WorkspaceAccess
from app.schemas.address import (
    AddressParts,
    AddressResolveRequest,
    AddressSuggestionsResponse,
)
from app.services.addresses.address_lookup import AddressLookupError, AddressLookupService
from app.services.rate_limiting.address_lookup_limiter import enforce_address_lookup_rate_limit

router = APIRouter()

# Below this an autocomplete costs a paid call to return the whole phone book.
MIN_QUERY_LENGTH = 3


@router.get("/suggest", response_model=AddressSuggestionsResponse)
async def suggest_addresses(
    workspace: WorkspaceAccess,
    membership: CanReadCRM,
    q: str = Query(min_length=1, max_length=200, description="Partially typed address"),
    session_token: str | None = Query(
        default=None,
        max_length=128,
        description="Groups the keystrokes of one address entry into a single billed session",
    ),
) -> AddressSuggestionsResponse:
    """Suggest addresses for a partially typed address."""
    service = AddressLookupService()

    if len(q.strip()) < MIN_QUERY_LENGTH:
        return AddressSuggestionsResponse(provider=service.provider, suggestions=[])

    await enforce_address_lookup_rate_limit(workspace.id)

    try:
        suggestions = await service.suggest(q, session_token=session_token)
    except AddressLookupError:
        return AddressSuggestionsResponse(provider=service.provider, suggestions=[])
    finally:
        await service.close()

    return AddressSuggestionsResponse(provider=service.provider, suggestions=suggestions)


@router.post("/resolve", response_model=AddressParts)
async def resolve_address(
    payload: AddressResolveRequest,
    workspace: WorkspaceAccess,
    membership: CanReadCRM,
) -> AddressParts:
    """Expand a picked suggestion into the fields a contact stores.

    Returns empty parts when the suggestion cannot be expanded, so the caller
    keeps whatever the operator already typed instead of wiping the field.
    """
    await enforce_address_lookup_rate_limit(workspace.id)

    service = AddressLookupService()
    try:
        parts = await service.resolve(payload.suggestion_id, session_token=payload.session_token)
    except AddressLookupError:
        return AddressParts()
    finally:
        await service.close()

    return parts or AddressParts()
