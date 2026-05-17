"""AI-powered website content analyzer for lead enrichment."""

import asyncio
import json
from typing import Any

import structlog
from bs4 import BeautifulSoup
from openai import APIConnectionError, APITimeoutError, AsyncOpenAI, RateLimitError

from app.core.config import settings
from app.schemas.find_leads_ai import WebsiteSummary

logger = structlog.get_logger()


_STRICT_UNSUPPORTED_KEYS = {"title", "description", "default", "examples"}


def _make_strict_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Transform a Pydantic JSON schema for OpenAI strict mode.

    Strict mode requires all properties in 'required', 'additionalProperties': false,
    and does not support 'title', 'description', 'default', or 'examples' keywords.
    """
    result: dict[str, Any] = {k: v for k, v in schema.items() if k not in _STRICT_UNSUPPORTED_KEYS}
    if "properties" in result:
        result["required"] = list(result["properties"].keys())
        result["additionalProperties"] = False
        result["properties"] = {k: _make_strict_schema(v) for k, v in result["properties"].items()}
    if "items" in result and isinstance(result["items"], dict):
        result["items"] = _make_strict_schema(result["items"])
    if "anyOf" in result:
        result["anyOf"] = [
            _make_strict_schema(v) if isinstance(v, dict) else v for v in result["anyOf"]
        ]
    return result


_WEBSITE_SUMMARY_STRICT_SCHEMA = _make_strict_schema(WebsiteSummary.model_json_schema())

WEBSITE_ANALYSIS_PROMPT = """Analyze this business website content and extract key information.

Return ONLY valid JSON with this structure:
{
    "business_description": "What the business does (1-2 sentences)",
    "services": ["Service 1", "Service 2", ...],  // Up to 5 main services
    "target_market": "Who they serve",
    "unique_selling_points": ["USP 1", "USP 2"],  // Up to 3
    "industry": "Industry category",
    "team_size_estimate": "solo | small (2-5) | medium (6-20) | large (20+) | unknown",
    "years_in_business": null,  // number or null
    "service_areas": ["City 1", "City 2"],  // Up to 10
    "revenue_signals": ["fleet of 10 trucks", "5000+ projects completed"],  // Scale indicators
    "has_financing": false,  // Whether they offer financing options
    "certifications": ["GAF Master Elite", "BBB A+"],  // Industry certifications or accreditations
    "decision_maker_name": null,  // Owner/Founder/CEO name if found on About/Team page
    "decision_maker_title": null  // Their title (Owner, Founder, CEO, President, etc.)
}

If information is not available, use null for strings/numbers or empty arrays for lists.
For team_size_estimate, look for "our team", staff photos, about pages, employee counts.
For revenue_signals, look for fleet sizes, project counts, years in business, service area breadth.
For has_financing, look for "financing available", "payment plans", "0% APR", etc.
For decision_maker_name, look for owner names, founder names, CEO/President
on "About Us", "Our Team", "Meet the Team" pages.
Look for patterns like "Founded by [Name]", "[Name], Owner", "Meet [Name]".
Only include if clearly identified.
For decision_maker_title, extract their title/role
(Owner, Founder, CEO, President, Managing Partner, etc.)"""


class AIContentAnalyzerService:
    """Service for AI-powered website content analysis."""

    def __init__(self, api_key: str | None = None) -> None:
        self._openai = AsyncOpenAI(api_key=api_key or settings.openai_api_key)
        self.logger = logger.bind(component="ai_content_analyzer")

    def _extract_text(self, html: str, max_chars: int = 8000) -> str:
        """Extract readable text from HTML, truncated for token limits."""
        soup = BeautifulSoup(html, "html.parser")

        # Remove script, style, nav, footer elements
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()

        text = soup.get_text(separator=" ", strip=True)
        # Collapse whitespace
        text = " ".join(text.split())
        return text[:max_chars]

    async def generate_website_summary(
        self,
        html_content: str,
        website_url: str,
        business_name: str | None = None,
    ) -> WebsiteSummary | None:
        """Generate AI summary of website content.

        Args:
            html_content: Raw HTML from website
            website_url: URL for context
            business_name: Optional business name for context

        Returns:
            WebsiteSummary or None if analysis fails
        """
        log = self.logger.bind(website_url=website_url)

        text_content = self._extract_text(html_content)
        if len(text_content) < 100:
            log.warning("insufficient_content", text_length=len(text_content))
            return None

        context = (
            f"Business: {business_name}\nWebsite: {website_url}\n\n"
            if business_name
            else f"Website: {website_url}\n\n"
        )

        max_retries = 3
        backoff = 1.0

        for attempt in range(max_retries):
            try:
                response = await asyncio.wait_for(
                    self._openai.chat.completions.create(
                        model="gpt-5.4-nano",
                        messages=[
                            {"role": "system", "content": WEBSITE_ANALYSIS_PROMPT},
                            {"role": "user", "content": context + text_content},
                        ],
                        response_format={
                            "type": "json_schema",
                            "json_schema": {
                                "name": "website_summary",
                                "strict": True,
                                "schema": _WEBSITE_SUMMARY_STRICT_SCHEMA,
                            },
                        },
                        temperature=0.3,
                        max_completion_tokens=800,
                    ),
                    timeout=30.0,
                )

                result = json.loads(response.choices[0].message.content or "{}")
                log.info(
                    "website_summary_generated",
                    has_description=bool(result.get("business_description")),
                )

                return WebsiteSummary(
                    business_description=result.get("business_description"),
                    services=result.get("services", [])[:5],
                    target_market=result.get("target_market"),
                    unique_selling_points=result.get("unique_selling_points", [])[:3],
                    industry=result.get("industry"),
                    team_size_estimate=result.get("team_size_estimate", "unknown"),
                    years_in_business=result.get("years_in_business"),
                    service_areas=result.get("service_areas", [])[:10],
                    revenue_signals=result.get("revenue_signals", [])[:5],
                    has_financing=result.get("has_financing", False),
                    certifications=result.get("certifications", [])[:10],
                    decision_maker_name=result.get("decision_maker_name"),
                    decision_maker_title=result.get("decision_maker_title"),
                )

            except RateLimitError as e:
                if attempt < max_retries - 1:
                    log.warning(
                        "openai_rate_limit",
                        attempt=attempt + 1,
                        backoff=backoff,
                        error=str(e),
                    )
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 30)
                    continue
                log.warning("openai_rate_limit_max_retries", error=str(e))
                return None

            except (APIConnectionError, APITimeoutError, TimeoutError) as e:
                if attempt < max_retries - 1:
                    log.warning(
                        "openai_transient_error",
                        attempt=attempt + 1,
                        backoff=backoff,
                        error_type=type(e).__name__,
                        error=str(e),
                    )
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 30)
                    continue
                log.warning(
                    "openai_transient_error_max_retries",
                    error_type=type(e).__name__,
                    error=str(e),
                )
                return None

            except Exception as e:
                log.warning("website_summary_failed", error=str(e))
                return None

        return None
