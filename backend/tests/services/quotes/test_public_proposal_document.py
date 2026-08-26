"""The client proposal page must never see internal pricing or fulfillment details.

``quote.proposal_document`` mixes client presentation data with the staff-only
SKU bill-of-materials the distributor order is built from. The public,
no-auth ``/p/quotes/{token}`` payload embeds that snapshot, so the sanitizer in
:func:`client_safe_document` is the only thing standing between a homeowner and
our part numbers, and these tests pin it down:

* fulfillment, inventory, and Bistro unit-math details are gone from the wire payload;
* the presentation fields the client page actually renders survive;
* the allowlist stays in sync with ``ProposalDocument`` so a newly added field
  fails here rather than silently shipping to clients.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
from pydantic import ValidationError

from app.models.quote import Quote
from app.models.workspace import Workspace
from app.schemas.proposal_wizard import (
    CLIENT_SAFE_DOCUMENT_FIELDS,
    MAX_NIGHT_PREVIEW_IMAGE_CHARS,
    MAX_NIGHT_PREVIEW_IMAGES,
    ProposalDocument,
    ProposalWizardPayload,
    client_safe_document,
)
from app.services.quotes import QuoteService

# Real part numbers from the seeded Maxteriors price book.
PART_SKUS = ("59409312", "59409010", "BM-050-C-AB")

# Fields on ProposalDocument that are deliberately staff-only. Adding a field to
# the document without classifying it here or in the allowlist fails the guard
# test below — the whole point of the allowlist being opt-in.
#
# ``attach_warning`` is the rep-facing cross-sell prompt ("this roof job has no
# gutters on it"). It is preview-only and never persisted, but classifying it
# keeps the guard honest: telling a homeowner what the business wishes it had
# sold them is not client-facing under any circumstances.
INTERNAL_ONLY_FIELDS = frozenset(
    {"fulfillment", "inventory_availability", "attach_warning", "pricing_source"}
)


def _document() -> dict[str, Any]:
    """A stored snapshot carrying both client copy and the internal parts list."""
    return {
        "version": 1,
        "client": {"first_name": "Dana", "last_name": "Homeowner"},
        "tier_order": ["best"],
        "tiers": [],
        "selected_tier": "best",
        "selected_financed_total": 5200.0,
        "notes": "Install week of the 14th.",
        "fulfillment": [
            {"sku": "59409312", "description": "Luxor 300W Transformer", "qty": 1},
            {"sku": "59409010", "description": "Luxor WiFi Module", "qty": 1},
            {"sku": "BM-050-C-AB", "description": "Mounting Bracket", "qty": 4},
        ],
        "inventory_availability": {
            "has_requirements": True,
            "has_shortages": True,
            "shortage_items": 1,
            "not_counted_items": 0,
            "untracked_items": 0,
            "items": [
                {
                    "sku": "59409312",
                    "inventory_item_name": "Luxor 300W Transformer",
                    "required_quantity": 1,
                    "quantity_on_hand": 0,
                    "shortfall": 1,
                    "status": "shortage",
                }
            ],
        },
    }


def test_allowlist_covers_every_document_field() -> None:
    """Every ProposalDocument field is explicitly client-safe or internal-only.

    Guards the opt-in property: a new field lands in neither set and trips here,
    forcing a deliberate call instead of defaulting to exposed.
    """
    declared = set(ProposalDocument.model_fields)
    classified = set(CLIENT_SAFE_DOCUMENT_FIELDS) | set(INTERNAL_ONLY_FIELDS)
    assert declared - classified == set(), (
        "New ProposalDocument field(s) are unclassified. Add each to "
        "CLIENT_SAFE_DOCUMENT_FIELDS (client may see it) or to "
        "INTERNAL_ONLY_FIELDS in this test (staff only)."
    )
    assert CLIENT_SAFE_DOCUMENT_FIELDS.isdisjoint(INTERNAL_ONLY_FIELDS)
    # The allowlist must not name fields the document doesn't have (stale entries).
    assert set(CLIENT_SAFE_DOCUMENT_FIELDS) - declared == set()


def test_sanitizer_drops_fulfillment_and_keeps_presentation() -> None:
    document = _document()
    safe = client_safe_document(document)

    assert safe is not None
    assert "fulfillment" not in safe
    assert "inventory_availability" not in safe
    # Client-facing copy survives untouched.
    assert safe["selected_tier"] == "best"
    assert safe["selected_financed_total"] == 5200.0
    assert safe["notes"] == "Install week of the 14th."
    assert safe["client"] == {"first_name": "Dana", "last_name": "Homeowner"}
    # The caller's stored snapshot is not mutated.
    assert "fulfillment" in document


def test_sanitizer_keeps_only_the_customer_bistro_total() -> None:
    document = _document()
    document["bistro"] = {
        "pricing_mode": "installation",
        "feet": 150,
        "lights_cost": 3708,
        "poles_cost": 1180,
        "raw_total": 4888,
        "total": 4888,
        "installations": [
            {
                "installation": "permanent",
                "feet": 150,
                "pole_count": 3,
                "lights_per_ft": 22,
                "poles_each": 350,
            }
        ],
    }

    safe = client_safe_document(document)

    assert safe is not None
    assert safe["bistro"] == {"total": 4888}
    assert "installations" in document["bistro"]


def test_sanitizer_passes_through_none() -> None:
    assert client_safe_document(None) is None


def test_every_designed_photo_reaches_the_client() -> None:
    """A design spanning several photos arrives whole on the client's link.

    The rep photographs the front, the back and the walkway, draws each, and
    saves once. The homeowner opens the link and must see all three: the
    sanitizer copies fields by name, so a blob whose shape grew is exactly the
    kind of thing that silently arrives with only its hero shot.
    """
    document = _document()
    document["night_preview"] = {
        "image": "data:image/jpeg;base64,FRONT",
        "images": [
            "data:image/jpeg;base64,FRONT",
            "data:image/jpeg;base64,BACK",
            "data:image/jpeg;base64,WALKWAY",
        ],
        "services": ["landscape"],
    }

    safe = client_safe_document(document)

    assert safe is not None
    assert safe["night_preview"]["images"] == [
        "data:image/jpeg;base64,FRONT",
        "data:image/jpeg;base64,BACK",
        "data:image/jpeg;base64,WALKWAY",
    ]
    # The hero key survives too, for a client on a cached bundle that predates
    # multi-photo designs and still reads ``image``.
    assert safe["night_preview"]["image"] == "data:image/jpeg;base64,FRONT"


def test_night_preview_images_are_bounded() -> None:
    """The images inside the opaque blob are capped; the blob itself is not.

    Every one of these is an inline data URL the homeowner downloads over the
    public link, so an unbounded set is their problem before it is the
    database's. Rejected loudly — truncating would ship a proposal missing a
    photo the rep drew, with nothing to say so.
    """
    ok = ProposalWizardPayload(
        night_preview={"images": ["data:image/jpeg;base64,A"] * MAX_NIGHT_PREVIEW_IMAGES}
    )
    assert ok.night_preview is not None

    with pytest.raises(ValidationError):
        ProposalWizardPayload(
            night_preview={"images": ["data:image/jpeg;base64,A"] * (MAX_NIGHT_PREVIEW_IMAGES + 1)}
        )

    with pytest.raises(ValidationError):
        ProposalWizardPayload(night_preview={"images": ["x" * (MAX_NIGHT_PREVIEW_IMAGE_CHARS + 1)]})

    with pytest.raises(ValidationError):
        ProposalWizardPayload(night_preview={"image": "x" * (MAX_NIGHT_PREVIEW_IMAGE_CHARS + 1)})

    # A design with no photos, and the shapes that predate the images list, are
    # all still valid payloads.
    assert ProposalWizardPayload(night_preview=None).night_preview is None
    assert (
        ProposalWizardPayload(
            night_preview={"image": "data:image/jpeg;base64,LEGACY", "dusk": 0.5}
        ).night_preview
        is not None
    )


def test_sanitizer_strips_unknown_future_fields() -> None:
    """An unrecognized key is withheld — opt-in, not opt-out."""
    safe = client_safe_document({"selected_tier": "best", "internal_margin": 0.42})
    assert safe == {"selected_tier": "best"}


@pytest.mark.asyncio
async def test_public_proposal_payload_contains_no_part_skus(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end on the service: no SKU survives into the serialized payload.

    Substring-searches the whole JSON body rather than checking one key, so a
    SKU smuggled through some other field still fails.
    """
    workspace = Workspace(id=uuid.uuid4(), name="Maxteriors Lighting", slug="lit", settings={})
    quote = Quote(
        id=uuid.uuid4(),
        workspace_id=workspace.id,
        number="QUO-000042",
        title="Backyard lighting",
        status="sent",
        currency="USD",
        subtotal=5200,
        tax_amount=0,
        discount_amount=0,
        total=5200,
        proposal_document=_document(),
    )
    quote.line_items = []
    quote.contact = None
    quote.workspace = workspace

    async def _load(self: object, token: str) -> Quote:
        return quote

    monkeypatch.setattr(QuoteService, "_load_by_token", _load)

    proposal = await QuoteService(db=None).get_public_proposal("tok")  # type: ignore[arg-type]

    assert proposal.proposal_document is not None
    assert "fulfillment" not in proposal.proposal_document
    body = json.dumps(proposal.model_dump(mode="json"))
    for sku in PART_SKUS:
        assert sku not in body, f"internal SKU {sku} leaked to the public proposal payload"
    assert "Luxor WiFi Module" not in body
    # Sanity: the client's own content still made it through.
    assert "QUO-000042" in body
    assert "Backyard lighting" in body
