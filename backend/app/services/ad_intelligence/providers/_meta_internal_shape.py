"""Shared normalizer for Meta's *internal* ad shape.

Both the licensed third-party provider
(:mod:`app.services.ad_intelligence.providers.meta_thirdparty`) and the
self-scrape provider
(:mod:`app.services.ad_intelligence.providers.meta_scraper`) receive ad dicts in
the **same** internal Meta shape the public Ad Library ``search_ads`` endpoint
returns:

* ``ad_archive_id`` / ``adArchiveID`` ids,
* ``snapshot.body.text`` / ``snapshot.caption`` / ``snapshot.cards[]`` /
  ``snapshot.link_url`` / ``snapshot.display_format`` creative fields,
* ``start_date`` / ``end_date`` epoch seconds,
* ``is_active`` flag and ``publisher_platform`` list.

This module owns that one normalizer (``normalize_ad`` + ``group_advertisers``)
so the two providers never drift. It is pure: no I/O, no settings, no logging —
just dict-in / value-objects-out, which keeps it trivially unit-testable and
lets the scraper assert byte-for-byte normalization parity with the licensed
provider.
"""

from __future__ import annotations

from collections import OrderedDict, defaultdict
from datetime import UTC, datetime
from typing import Any

from app.services.ad_intelligence.types import NormalizedAd, NormalizedAdvertiser
from app.services.lead_discovery.dedupe import extract_host

__all__ = ["flatten", "group_advertisers", "normalize_ad"]

# Map Meta's ``display_format`` enum to our coarse media classification.
_DISPLAY_FORMAT_MEDIA = {
    "image": "image",
    "img": "image",
    "video": "video",
    "dpa": "carousel",
    "dco": "carousel",
    "carousel": "carousel",
}


def flatten(items: list[Any]) -> list[dict[str, Any]]:
    """Flatten one level of nesting.

    Both the third-party envelopes and the internal ``payload.results`` wrap
    each ad (or ad group) in a list, so ``results`` is a list-of-lists of ad
    dicts. This collapses that to a flat list of dicts.
    """
    out: list[dict[str, Any]] = []
    for item in items:
        if isinstance(item, dict):
            out.append(item)
        elif isinstance(item, list):
            out.extend(x for x in item if isinstance(x, dict))
    return out


def group_advertisers(
    raw_ads: list[dict[str, Any]],
    *,
    platform: str,
    country: str | None,
) -> list[NormalizedAdvertiser]:
    """Group internal-shape ad dicts by page id into normalized advertisers."""
    grouped: OrderedDict[str, list[dict[str, Any]]] = OrderedDict()
    for ad in raw_ads:
        page_id = _str(_dig(ad, "page_id") or _dig(ad, "snapshot", "page_id"))
        if not page_id:
            continue
        grouped.setdefault(page_id, []).append(ad)

    advertisers: list[NormalizedAdvertiser] = []
    for page_id, ads in grouped.items():
        normalized = tuple(normalize_ad(ad) for ad in ads)
        page_name = _str(_dig(ads[0], "page_name") or _dig(ads[0], "snapshot", "page_name"))
        website_url, website_host = _best_landing(normalized)
        advertisers.append(
            NormalizedAdvertiser(
                platform=platform,
                advertiser_key=page_id,
                page_id=page_id,
                advertiser_name=page_name,
                page_url=f"https://www.facebook.com/{page_id}",
                website_url=website_url,
                website_host=website_host,
                country_code=country,
                ads=normalized,
                raw={"page_id": page_id, "page_name": page_name, "ad_count": len(ads)},
            )
        )
    return advertisers


def normalize_ad(ad: dict[str, Any]) -> NormalizedAd:
    """Map one internal-shape ad dict into a :class:`NormalizedAd`."""
    raw_snapshot = ad.get("snapshot")
    snapshot: dict[str, Any] = raw_snapshot if isinstance(raw_snapshot, dict) else {}
    ad_id = _str(ad.get("ad_archive_id") or ad.get("id") or ad.get("adArchiveID")) or ""

    body = _str(_dig(snapshot, "body", "text") or _dig(ad, "body") or _dig(ad, "ad_creative_body"))
    caption = _str(snapshot.get("caption") or ad.get("caption"))
    raw_cards = snapshot.get("cards")
    cards: list[dict[str, Any]] = raw_cards if isinstance(raw_cards, list) else []
    first_card: dict[str, Any] = cards[0] if cards else {}
    title = _str(first_card.get("title") or snapshot.get("title"))
    link_url = _str(
        first_card.get("link_url") or snapshot.get("link_url") or _caption_to_url(caption)
    )
    link_host = extract_host(link_url)

    is_active = bool(ad.get("is_active", ad.get("isActive", True)))
    start = _parse_epoch(ad.get("start_date") or ad.get("startDate"))
    stop = _parse_epoch(ad.get("end_date") or ad.get("endDate"))

    platforms_raw = ad.get("publisher_platform") or ad.get("publisher_platforms") or []
    platforms = tuple(str(p) for p in platforms_raw if p) if isinstance(platforms_raw, list) else ()

    display_format = _str(snapshot.get("display_format") or ad.get("display_format"))
    media_type = _DISPLAY_FORMAT_MEDIA.get((display_format or "").lower(), "unknown")
    if media_type == "unknown" and len(cards) > 1:
        media_type = "carousel"

    return NormalizedAd(
        ad_external_id=ad_id,
        body=body,
        title=title,
        link_caption=caption,
        link_url=link_url,
        link_host=link_host,
        cta_type=_str(snapshot.get("cta_type") or ad.get("cta_type")),
        snapshot_url=_str(ad.get("url") or ad.get("snapshot_url")),
        media_type=media_type,
        platforms=platforms,
        ad_delivery_start_time=start,
        ad_delivery_stop_time=stop,
        is_active=is_active,
        raw={k: v for k, v in ad.items() if k not in ("url", "snapshot_url")},
    )


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def _dig(obj: Any, *keys: str) -> Any:
    cur = obj
    for key in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def _str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _caption_to_url(caption: str | None) -> str | None:
    if not caption:
        return None
    candidate = caption.strip()
    if "://" in candidate:
        return candidate
    if "." in candidate and " " not in candidate:
        return f"https://{candidate}"
    return None


def _best_landing(ads: tuple[NormalizedAd, ...]) -> tuple[str | None, str | None]:
    host_counts: dict[str, int] = defaultdict(int)
    url_by_host: dict[str, str] = {}
    for ad in ads:
        if ad.link_host:
            host_counts[ad.link_host] += 1
            if ad.link_url:
                url_by_host.setdefault(ad.link_host, ad.link_url)
    if not host_counts:
        return None, None
    best = max(host_counts, key=lambda k: host_counts[k])
    return url_by_host.get(best), best


def _parse_epoch(value: object) -> datetime | None:
    """Parse a Unix epoch (seconds) or ISO string into a UTC datetime."""
    if value in (None, "", 0):
        return None
    if isinstance(value, int | float):
        try:
            return datetime.fromtimestamp(float(value), tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value).strip()
    if text.isdigit():
        return datetime.fromtimestamp(int(text), tz=UTC)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
