"""People-extraction discovery provider (``web_people``).

The "scrape the web for people" path. Given a company **domain** (or a free-text
query → company websites via Google Places), it crawls a bounded set of the
company's own first-party pages (team / about / staff / leadership / contact),
extracts **named individuals with titles** from the markup, infers a best-guess
email via :mod:`email_patterns` (always marked ``unverified`` until the
enrichment worker verifies it), and emits one :class:`RawLead` per person.

Compliance (see the plan's hard constraints):

* Only first-party company pages reachable from the company domain are crawled
  — **never** LinkedIn or gated networks.
* ``WebsiteScraperService`` honors robots/ToS and timeouts, and applies the
  SSRF egress guard (``scraping.url_guard``) to every URL and redirect hop, so
  a client-supplied ``params.domain`` can't point the crawl at internal hosts.
* A per-domain page cap (``web_people_max_pages_per_domain``) and a polite
  inter-fetch delay bound the crawl. Per-workspace quota is enforced by
  ``scraping_limiter`` at the API launch boundary.

People extraction from arbitrary HTML is noisy, so every emitted lead carries a
confidence in ``source_metadata`` and a guessed email is never treated as real.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from typing import Any, ClassVar
from urllib.parse import urljoin, urlparse

import structlog
from bs4 import BeautifulSoup, Tag

from app.core.config import settings
from app.services.lead_discovery.dedupe import dedupe_raw_leads, extract_host
from app.services.lead_discovery.email_patterns import candidate_emails, split_full_name
from app.services.lead_discovery.protocol import BaseLeadDiscoveryProvider
from app.services.lead_discovery.providers.google_places import GooglePlacesLeadProvider
from app.services.lead_discovery.types import (
    DiscoveryWarning,
    LeadDiscoveryRequest,
    ProviderResult,
    RawLead,
)
from app.services.scraping.website_scraper import (
    WebsiteScraperError,
    WebsiteScraperService,
)

logger = structlog.get_logger()

SOURCE_TYPE = "web_people"

# A person name: 2–3 capitalized tokens (allows initials, hyphens, apostrophes).
_NAME_RE = re.compile(r"^[A-Z][A-Za-z'\u2019.\-]+(?:\s+[A-Z][A-Za-z'\u2019.\-]+){1,2}$")
# Words that disqualify a "name" candidate (nav/boilerplate noise).
_NAME_STOPWORDS = frozenset(
    {
        "home",
        "about",
        "about us",
        "contact",
        "contact us",
        "our team",
        "team",
        "services",
        "privacy policy",
        "terms",
        "careers",
        "blog",
        "news",
        "get started",
        "learn more",
        "read more",
    }
)
# Role keywords that mark a line as a job title.
_ROLE_KEYWORDS = (
    "ceo",
    "cfo",
    "coo",
    "cto",
    "cmo",
    "cio",
    "founder",
    "co-founder",
    "cofounder",
    "president",
    "vice president",
    "vp",
    "director",
    "manager",
    "head of",
    "head ",
    "lead",
    "chief",
    "officer",
    "owner",
    "partner",
    "principal",
    "engineer",
    "designer",
    "marketing",
    "sales",
    "operations",
    "account",
    "specialist",
    "coordinator",
    "consultant",
    "analyst",
    "architect",
    "counsel",
    "controller",
    "supervisor",
)
# Class/id tokens that mark an element as a person/team card.
_CARD_TOKEN_RE = re.compile(
    r"(team[-_ ]?member|staff[-_ ]?member|member|person|people|employee|"
    r"bio|profile|leadership|founder|our[-_ ]?team|card)",
    re.IGNORECASE,
)
_TITLE_CLASS_RE = re.compile(r"(title|role|position|job|designation)", re.IGNORECASE)
_NAME_CLASS_RE = re.compile(r"(name|fullname|member[-_ ]?name|person[-_ ]?name)", re.IGNORECASE)
# Internal-link hints for pages likely to list people.
_PEOPLE_PAGE_HINTS = (
    "team",
    "about",
    "staff",
    "people",
    "leadership",
    "our-team",
    "meet",
    "company",
    "contact",
)

_MIN_CONFIDENCE = 45


@dataclass(slots=True, frozen=True)
class ExtractedPerson:
    """One person parsed out of a company web page."""

    full_name: str
    title: str | None
    confidence: int
    source_url: str | None = None
    first_name: str = ""
    last_name: str = ""


@dataclass(slots=True)
class _Crawl:
    """Mutable accumulator for one domain crawl."""

    people: list[ExtractedPerson] = field(default_factory=list)
    pages_fetched: int = 0
    warnings: list[DiscoveryWarning] = field(default_factory=list)


def _clean_text(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"\s+", " ", value).strip()


def _attr_text(el: Tag) -> str:
    """Return an element's class+id tokens as one searchable string."""
    classes = el.get("class")
    class_str = " ".join(classes) if isinstance(classes, list) else (classes or "")
    return f"{class_str} {el.get('id') or ''}"


def _looks_like_name(text: str) -> bool:
    cleaned = _clean_text(text)
    if not cleaned or len(cleaned) > 60:
        return False
    if cleaned.lower() in _NAME_STOPWORDS:
        return False
    return bool(_NAME_RE.match(cleaned))


def _looks_like_title(text: str) -> bool:
    cleaned = _clean_text(text).lower()
    if not cleaned or len(cleaned) > 90:
        return False
    return any(keyword in cleaned for keyword in _ROLE_KEYWORDS)


def _leaf_cards(soup: BeautifulSoup) -> list[Tag]:
    """Return person-card elements that don't nest another person card."""
    cards: list[Tag] = []
    for el in soup.find_all(["div", "li", "article", "section"]):
        if not isinstance(el, Tag) or not _CARD_TOKEN_RE.search(_attr_text(el)):
            continue
        # Leaf only: skip containers that hold another matching card.
        nested = any(
            isinstance(child, Tag) and _CARD_TOKEN_RE.search(_attr_text(child))
            for child in el.find_all(["div", "li", "article", "section"])
        )
        if not nested:
            cards.append(el)
    return cards


def _name_from_card(card: Tag) -> tuple[str, int] | None:
    """Return ``(name, base_confidence)`` for a card, or ``None``."""
    # 1) Explicit name-classed element.
    for el in card.find_all(True):
        classes = el.get("class")
        if isinstance(classes, list) and _NAME_CLASS_RE.search(" ".join(classes)):
            text = _clean_text(el.get_text(" "))
            if _looks_like_name(text):
                return text, 80
    # 2) Heading / emphasis tags.
    for tag in ("h1", "h2", "h3", "h4", "h5", "h6", "strong", "b", "a"):
        for el in card.find_all(tag):
            text = _clean_text(el.get_text(" "))
            if _looks_like_name(text):
                return text, 60
    return None


def _title_from_card(card: Tag, name: str) -> str | None:
    # 1) Explicit title-classed element.
    for el in card.find_all(True):
        classes = el.get("class")
        if isinstance(classes, list) and _TITLE_CLASS_RE.search(" ".join(classes)):
            text = _clean_text(el.get_text(" "))
            if text and text != name and len(text) <= 90:
                return text
    # 2) Any short line mentioning a role keyword.
    for el in card.find_all(["p", "span", "div", "h4", "h5", "h6", "em", "small"]):
        text = _clean_text(el.get_text(" "))
        if text and text != name and _looks_like_title(text):
            return text
    return None


def extract_people_from_html(html: str, source_url: str | None = None) -> list[ExtractedPerson]:
    """Extract named people (+ titles) from a company web page (pure).

    Heuristic + noisy by design: returns only candidates at or above the
    minimum confidence, de-duplicated by normalized full name.
    """
    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception:  # noqa: BLE001 - never let parsing crash discovery
        return []

    found: dict[str, ExtractedPerson] = {}
    for card in _leaf_cards(soup):
        name_hit = _name_from_card(card)
        if name_hit is None:
            continue
        name, base = name_hit
        title = _title_from_card(card, name)
        confidence = base + (15 if title else -10)
        if confidence < _MIN_CONFIDENCE:
            continue
        first, last = split_full_name(name)
        key = name.lower()
        candidate = ExtractedPerson(
            full_name=name,
            title=title,
            confidence=min(100, confidence),
            source_url=source_url,
            first_name=first,
            last_name=last,
        )
        existing = found.get(key)
        if existing is None or candidate.confidence > existing.confidence:
            found[key] = candidate

    return sorted(found.values(), key=lambda p: p.confidence, reverse=True)


class WebPeopleLeadProvider(BaseLeadDiscoveryProvider):
    """Crawl first-party company pages and emit one lead per named person."""

    source_type: ClassVar[str] = SOURCE_TYPE

    def __init__(
        self,
        scraper: WebsiteScraperService | None = None,
        places_provider: GooglePlacesLeadProvider | None = None,
        *,
        inter_fetch_delay_seconds: float = 0.5,
    ) -> None:
        self._scraper = scraper or WebsiteScraperService()
        self._owns_scraper = scraper is None
        self._places_provider = places_provider
        self._delay = inter_fetch_delay_seconds
        self._logger = logger.bind(component="web_people_provider")

    async def close(self) -> None:
        if self._owns_scraper:
            await self._scraper.close()
        if self._places_provider is not None:
            await self._places_provider.close()

    async def search(self, request: LeadDiscoveryRequest) -> ProviderResult:
        domains = await self._resolve_domains(request)
        if not domains:
            return ProviderResult(
                source_type=self.source_type,
                leads=(),
                requested_count=request.max_results,
                warnings=(
                    DiscoveryWarning(
                        code="no_domains",
                        message="web_people needs a domain (params.domain/domains) or a query.",
                    ),
                ),
            )

        leads: list[RawLead] = []
        warnings: list[DiscoveryWarning] = []
        raw_count = 0
        per_domain_cap = settings.web_people_max_people_per_domain
        for domain in domains:
            crawl = await self._crawl_domain(domain)
            warnings.extend(crawl.warnings)
            for person in crawl.people[:per_domain_cap]:
                raw_count += 1
                leads.append(self._person_to_lead(person, domain, request))
            if len(leads) >= request.max_results:
                break

        unique_leads, duplicate_count = dedupe_raw_leads(leads[: request.max_results])
        self._logger.info(
            "web_people_search_complete",
            domains=len(domains),
            raw_count=raw_count,
            unique=len(unique_leads),
            duplicates=duplicate_count,
        )
        return ProviderResult(
            source_type=self.source_type,
            leads=unique_leads,
            requested_count=request.max_results,
            raw_count=raw_count,
            duplicate_count=duplicate_count,
            warnings=tuple(warnings),
        )

    async def _resolve_domains(self, request: LeadDiscoveryRequest) -> list[str]:
        params = request.params or {}
        explicit: list[str] = []
        if params.get("domain"):
            explicit.append(str(params["domain"]))
        if isinstance(params.get("domains"), list):
            explicit.extend(str(d) for d in params["domains"] if d)
        hosts = [h for h in (extract_host(d) for d in explicit) if h]
        if hosts:
            # Preserve order, drop dupes.
            return list(dict.fromkeys(hosts))

        # Fall back to a company search via Google Places when only a query
        # was supplied. Each business website becomes a crawl target.
        if not request.query:
            return []
        provider = self._places_provider or GooglePlacesLeadProvider()
        owns = self._places_provider is None
        try:
            result = await provider.search(request)
        except Exception as exc:  # noqa: BLE001 - degrade to no domains
            self._logger.info("places_lookup_failed", error=str(exc))
            return []
        finally:
            if owns:
                await provider.close()
        hosts = [
            host
            for lead in result.leads
            if (host := lead.website_host or extract_host(lead.website))
        ]
        return list(dict.fromkeys(hosts))

    async def _crawl_domain(self, host: str) -> _Crawl:
        crawl = _Crawl()
        max_pages = settings.web_people_max_pages_per_domain
        # ``host`` is client-supplied (params.domain) — the scraper validates
        # this URL against the SSRF egress guard before it opens a socket.
        start_url = f"https://{host}"
        visited: set[str] = set()

        # Fetch the homepage first to discover team/about/contact links.
        home = await self._fetch(start_url, crawl)
        if home is None:
            return crawl
        visited.add(start_url.rstrip("/"))
        crawl.people.extend(extract_people_from_html(home, start_url))

        targets = self._discover_people_links(home, start_url, host)
        for url in targets:
            if crawl.pages_fetched >= max_pages:
                break
            normalized = url.rstrip("/")
            if normalized in visited:
                continue
            visited.add(normalized)
            html = await self._fetch(url, crawl)
            if html is None:
                continue
            crawl.people.extend(extract_people_from_html(html, url))

        # De-dupe people across pages by name, keeping highest confidence.
        best: dict[str, ExtractedPerson] = {}
        for person in crawl.people:
            key = person.full_name.lower()
            existing = best.get(key)
            if existing is None or person.confidence > existing.confidence:
                best[key] = person
        crawl.people = sorted(best.values(), key=lambda p: p.confidence, reverse=True)
        return crawl

    def _discover_people_links(self, html: str, base_url: str, host: str) -> list[str]:
        try:
            soup = BeautifulSoup(html, "html.parser")
        except Exception:  # noqa: BLE001
            return []
        scored: list[tuple[int, str]] = []
        seen: set[str] = set()
        for a in soup.find_all("a", href=True):
            href = str(a["href"])
            text = _clean_text(a.get_text(" ")).lower()
            absolute = urljoin(base_url, href)
            parsed = urlparse(absolute)
            if parsed.scheme not in ("http", "https"):
                continue
            link_host = (parsed.hostname or "").lower().removeprefix("www.")
            # First-party only — never follow off-domain links.
            if link_host != host:
                continue
            haystack = f"{parsed.path.lower()} {text}"
            score = sum(1 for hint in _PEOPLE_PAGE_HINTS if hint in haystack)
            if score == 0:
                continue
            clean = f"{parsed.scheme}://{parsed.netloc}{parsed.path}".rstrip("/")
            if clean in seen:
                continue
            seen.add(clean)
            scored.append((score, clean))
        scored.sort(key=lambda s: s[0], reverse=True)
        return [url for _, url in scored]

    async def _fetch(self, url: str, crawl: _Crawl) -> str | None:
        try:
            if crawl.pages_fetched > 0 and self._delay > 0:
                await asyncio.sleep(self._delay)
            result = await self._scraper.scrape_website(url)
        except WebsiteScraperError as exc:
            crawl.warnings.append(DiscoveryWarning(code="fetch_failed", message=f"{url}: {exc}"))
            return None
        crawl.pages_fetched += 1
        html = result.get("html_content")
        return html if isinstance(html, str) else None

    def _person_to_lead(
        self, person: ExtractedPerson, host: str, request: LeadDiscoveryRequest
    ) -> RawLead:
        candidates = candidate_emails(person.first_name, person.last_name, host)
        guessed = candidates[0] if candidates else None
        source_metadata: dict[str, Any] = {
            "confidence": person.confidence,
            "extraction": "web_people",
            "source_page": person.source_url,
            "email_unverified": guessed is not None,
            "email_pattern": guessed.pattern if guessed else None,
            "email_candidates": [
                {"email": c.email, "pattern": c.pattern, "confidence": c.confidence}
                for c in candidates[:5]
            ],
        }
        if request.query:
            source_metadata["source_query"] = request.query
        return RawLead(
            source_type=SOURCE_TYPE,
            source_external_id=f"{host}:{person.full_name.lower().replace(' ', '_')}",
            name=person.full_name,
            full_name=person.full_name,
            first_name=person.first_name or None,
            last_name=person.last_name or None,
            title=person.title,
            # Guessed email is provisional — never set as a verified identifier.
            email=guessed.email if guessed else None,
            website=f"https://{host}",
            website_host=host,
            country_code=request.country_code,
            region=request.region,
            city=request.city,
            location_label=request.location_label,
            source_metadata=source_metadata,
        )
