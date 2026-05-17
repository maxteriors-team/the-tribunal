"""Website scraper service for extracting social media links."""

import re
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
import structlog
from bs4 import BeautifulSoup

logger = structlog.get_logger()

# Social media URL patterns
SOCIAL_PATTERNS: dict[str, re.Pattern[str]] = {
    "linkedin": re.compile(
        r"https?://(?:www\.)?linkedin\.com/(?:company|in)/[^/\s\"\'<>]+",
        re.IGNORECASE,
    ),
    "facebook": re.compile(
        r"https?://(?:www\.)?facebook\.com/[^/\s\"\'<>]+",
        re.IGNORECASE,
    ),
    "twitter": re.compile(
        r"https?://(?:www\.)?(?:twitter\.com|x\.com)/[^/\s\"\'<>]+",
        re.IGNORECASE,
    ),
    "instagram": re.compile(
        r"https?://(?:www\.)?instagram\.com/[^/\s\"\'<>]+",
        re.IGNORECASE,
    ),
    "youtube": re.compile(
        r"https?://(?:www\.)?youtube\.com/(?:@|channel/|c/|user/)[^/\s\"\'<>]+",
        re.IGNORECASE,
    ),
    "tiktok": re.compile(
        r"https?://(?:www\.)?tiktok\.com/@[^/\s\"\'<>]+",
        re.IGNORECASE,
    ),
}

# URLs to exclude (generic/not-useful)
EXCLUDED_PATTERNS = [
    r"/sharer",
    r"/share",
    r"/intent/",
    r"linkedin\.com/shareArticle",
    r"facebook\.com/sharer",
    r"twitter\.com/intent",
]


class WebsiteScraperError(Exception):
    """Base exception for website scraper errors."""

    pass


class WebsiteScraperService:
    """Service for scraping website metadata and social links."""

    def __init__(
        self,
        timeout: float = 10.0,
        max_retries: int = 3,
    ) -> None:
        """Initialize the website scraper service.

        Args:
            timeout: Request timeout in seconds
            max_retries: Maximum number of retry attempts
        """
        self.timeout = timeout
        self.max_retries = max_retries
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(connect=5.0, read=self.timeout, write=10.0, pool=5.0),
                limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
                follow_redirects=True,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    ),
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.5",
                },
            )
        return self._client

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    def _is_excluded_url(self, url: str) -> bool:
        """Check if a URL should be excluded (share links, etc)."""
        return any(re.search(pattern, url, re.IGNORECASE) for pattern in EXCLUDED_PATTERNS)

    def _clean_social_url(self, url: str, platform: str) -> str | None:
        """Clean and validate a social media URL."""
        if not url or self._is_excluded_url(url):
            return None

        # Parse and reconstruct clean URL
        parsed = urlparse(url)
        if not parsed.netloc:
            return None

        # Remove query params and fragments for cleaner URLs
        clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path.rstrip('/')}"

        # Validate it still matches the pattern
        pattern = SOCIAL_PATTERNS.get(platform)
        if pattern and pattern.match(clean_url):
            return clean_url

        return None

    def _extract_social_links(self, html: str, base_url: str) -> dict[str, str | None]:
        """Extract social media links from HTML content.

        Args:
            html: Raw HTML content
            base_url: Base URL for resolving relative links

        Returns:
            Dictionary of platform -> URL mappings
        """
        social_links: dict[str, str | None] = {
            "linkedin": None,
            "facebook": None,
            "twitter": None,
            "instagram": None,
            "youtube": None,
            "tiktok": None,
        }

        try:
            soup = BeautifulSoup(html, "html.parser")

            # Extract from href attributes
            for link in soup.find_all("a", href=True):
                href = str(link["href"])
                # Resolve relative URLs
                if not href.startswith(("http://", "https://")):
                    href = urljoin(base_url, href)

                for platform, pattern in SOCIAL_PATTERNS.items():
                    if social_links[platform] is None:
                        match = pattern.search(href)
                        if match:
                            clean_url = self._clean_social_url(match.group(0), platform)
                            if clean_url:
                                social_links[platform] = clean_url

            # Also search in page content for any missed links
            for platform, pattern in SOCIAL_PATTERNS.items():
                if social_links[platform] is None:
                    matches = pattern.findall(html)
                    for match in matches:
                        clean_url = self._clean_social_url(match, platform)
                        if clean_url:
                            social_links[platform] = clean_url
                            break

        except Exception as e:
            logger.warning(
                "social_link_extraction_error",
                error=str(e),
                base_url=base_url,
            )

        return social_links

    def _extract_meta_info(self, html: str) -> dict[str, str | None]:
        """Extract meta information from HTML.

        Args:
            html: Raw HTML content

        Returns:
            Dictionary with title and description
        """
        meta_info: dict[str, str | None] = {
            "title": None,
            "description": None,
        }

        try:
            soup = BeautifulSoup(html, "html.parser")

            # Get title
            title_tag = soup.find("title")
            if title_tag and title_tag.string:
                meta_info["title"] = title_tag.string.strip()[:500]

            # Get meta description
            desc_tag = soup.find("meta", attrs={"name": "description"})
            if desc_tag and desc_tag.get("content"):
                meta_info["description"] = str(desc_tag["content"]).strip()[:1000]

            # Fallback to og:description
            if not meta_info["description"]:
                og_desc = soup.find("meta", property="og:description")
                if og_desc and og_desc.get("content"):
                    meta_info["description"] = str(og_desc["content"]).strip()[:1000]

        except Exception as e:
            logger.warning("meta_extraction_error", error=str(e))

        return meta_info

    def _detect_ad_pixels(self, html: str) -> dict[str, bool]:
        """Detect advertising and analytics pixels in HTML content.

        Args:
            html: Raw HTML content

        Returns:
            Dictionary of pixel type -> detected boolean
        """
        html_lower = html.lower()
        return {
            "meta_pixel": (
                "fbq(" in html or "connect.facebook.net/en_us/fbevents.js" in html_lower
            ),
            "google_ads": (
                "googleadservices.com" in html_lower
                or "google.com/pagead/conversion" in html_lower
                or "gtag('event', 'conversion" in html_lower
            ),
            "google_analytics": (
                "google-analytics.com/analytics.js" in html_lower
                or "googletagmanager.com/gtag/js" in html_lower
            ),
            "gtm": "googletagmanager.com/gtm.js" in html_lower,
            "linkedin_pixel": "snap.licdn.com/li.lms-analytics" in html_lower,
            "tiktok_pixel": "analytics.tiktok.com" in html_lower,
        }

    async def scrape_website(self, url: str) -> dict[str, Any]:
        """Scrape a website for social links and metadata.

        Args:
            url: Website URL to scrape

        Returns:
            Dictionary containing social_links and website_meta

        Raises:
            WebsiteScraperError: If scraping fails after retries
        """
        log = logger.bind(url=url)

        # Normalize URL
        if not url.startswith(("http://", "https://")):
            url = f"https://{url}"

        client = await self._get_client()
        last_error: Exception | None = None

        for attempt in range(self.max_retries):
            try:
                log.debug("scraping_attempt", attempt=attempt + 1)
                response = await client.get(url)
                response.raise_for_status()

                html = response.text
                social_links = self._extract_social_links(html, str(response.url))
                meta_info = self._extract_meta_info(html)
                ad_pixels = self._detect_ad_pixels(html)

                log.info(
                    "website_scraped",
                    social_links_found=sum(1 for v in social_links.values() if v),
                    has_title=bool(meta_info.get("title")),
                    has_description=bool(meta_info.get("description")),
                )

                return {
                    "social_links": social_links,
                    "website_meta": meta_info,
                    "ad_pixels": ad_pixels,
                    "html_content": html,  # For AI analysis
                }

            except httpx.TimeoutException as e:
                last_error = e
                log.warning("scrape_timeout", attempt=attempt + 1)
            except httpx.HTTPStatusError as e:
                last_error = e
                log.warning(
                    "scrape_http_error",
                    status_code=e.response.status_code,
                    attempt=attempt + 1,
                )
                # Don't retry client errors (4xx)
                if 400 <= e.response.status_code < 500:
                    break
            except Exception as e:
                last_error = e
                log.warning("scrape_error", error=str(e), attempt=attempt + 1)

        error_msg = f"Failed to scrape {url} after {self.max_retries} attempts"
        if last_error:
            error_msg = f"{error_msg}: {last_error}"
        raise WebsiteScraperError(error_msg)
