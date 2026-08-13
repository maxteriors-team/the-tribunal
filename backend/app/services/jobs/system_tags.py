"""Durable customer equipment tags derived from completed installation jobs.

Tags describe systems the customer actually owns, not interests or campaign
membership. Classification reads structured project/approved-quote snapshots;
it never guesses from a job title or note.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.models.field_service import Job

LIGHTING_SYSTEM_TAG = "Lighting System"
LUXOR_SYSTEM_TAG = "Luxor System"
PERMANENT_LIGHT_SYSTEM_TAG = "Permanent Light System"
LUXOR_UPGRADE_CANDIDATE_TAG = "Luxor Upgrade Candidate"

# Stable catalog identity from the Maxteriors price book. The name fallback is
# deliberately narrow and only reads a sold proposal line/fulfillment part; it
# supports historical snapshots whose catalog key was not preserved.
_LUXOR_CATALOG_KEYS = frozenset({"best-luxor", "best-lux-300"})
_LUXOR_PART_SKUS = frozenset({"59409312", "59409010"})


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _quote_document(job: Job) -> Mapping[str, Any]:
    quote = getattr(job, "source_quote", None)
    return _mapping(getattr(quote, "proposal_document", None))


def _project_items(job: Job) -> list[Mapping[str, Any]]:
    project = getattr(job, "lighting_project", None)
    project_document = _mapping(getattr(project, "document", None))
    return [
        _mapping(item)
        for shot in _sequence(project_document.get("shots"))
        for item in _sequence(_mapping(_mapping(shot).get("design")).get("items"))
    ]


def _selected_tier_lines(job: Job) -> list[Mapping[str, Any]]:
    document = _quote_document(job)
    selected_tier = str(document.get("selected_tier") or "")
    return [
        _mapping(line)
        for tier in _sequence(document.get("tiers"))
        if str(_mapping(tier).get("key") or "") == selected_tier
        for line in _sequence(_mapping(tier).get("lines"))
    ]


def is_luxor_install(job: Job) -> bool:
    """Return whether structured project/quote data proves a Luxor was sold.

    New lighting projects preserve transformer SKUs on placed items. Approved
    wizard quotes also snapshot the selected tier's item key and fulfillment
    SKUs, which covers jobs converted before the plan was fully drawn.
    """
    for row in _project_items(job):
        keys = {
            str(row.get("catalogSku") or row.get("catalog_sku") or "").casefold(),
            str(row.get("productId") or row.get("product_id") or "").casefold(),
        }
        if keys & _LUXOR_CATALOG_KEYS:
            return True

    for line_row in _selected_tier_lines(job):
        item_id = str(line_row.get("item_id") or "").casefold()
        name = str(line_row.get("name") or "").casefold()
        if item_id in _LUXOR_CATALOG_KEYS or (
            bool(line_row.get("transformer")) and "luxor" in name
        ):
            return True

    document = _quote_document(job)
    for part in _sequence(document.get("fulfillment")):
        row = _mapping(part)
        if str(row.get("sku") or "") in _LUXOR_PART_SKUS:
            return True
    return False


def _has_known_non_luxor_transformer(job: Job) -> bool:
    """Return whether a specific non-Luxor landscape controller was sold."""
    if is_luxor_install(job):
        return False
    for row in _project_items(job):
        product_id = str(row.get("productId") or row.get("product_id") or "").casefold()
        catalog_key = str(
            row.get("catalogSku")
            or row.get("catalog_sku")
            or row.get("catalogItemId")
            or row.get("catalog_item_id")
            or ""
        ).strip()
        if product_id == "fixture-transformer" and catalog_key:
            return True
    return any(bool(line.get("transformer")) for line in _selected_tier_lines(job))


def _is_permanent_install(job: Job) -> bool:
    """Return whether the sold quote contains permanent lighting."""
    document = _quote_document(job)
    if str(document.get("service") or "").casefold() == "permanent":
        return True
    if "permanent" in {
        str(category).casefold() for category in _sequence(document.get("categories"))
    }:
        return True
    return any(
        str(_mapping(section).get("key") or "").casefold() == "permanent"
        for section in _sequence(document.get("category_sections"))
    )


def completed_install_tags(job: Job) -> tuple[str, ...]:
    """Tags proven by a completed job's structured installation record.

    ``Lighting System`` is the broad ownership segment. Specific equipment tags
    stack underneath it, so one contact can legitimately own both a landscape
    Luxor system and permanent roofline lights.
    """
    landscape = getattr(job, "lighting_project_id", None) is not None
    permanent = _is_permanent_install(job)
    if not landscape and not permanent:
        return ()

    tags = [LIGHTING_SYSTEM_TAG]
    luxor = landscape and is_luxor_install(job)
    if luxor:
        tags.append(LUXOR_SYSTEM_TAG)
    if landscape and not luxor and _has_known_non_luxor_transformer(job):
        tags.append(LUXOR_UPGRADE_CANDIDATE_TAG)
    if permanent:
        tags.append(PERMANENT_LIGHT_SYSTEM_TAG)
    return tuple(tags)
