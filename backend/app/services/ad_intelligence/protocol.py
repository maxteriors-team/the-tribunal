"""Protocol + abstract base for ad-library intelligence providers.

A provider, given an :class:`AdSearchRequest`, produces an
:class:`AdProviderResult` of normalized advertisers + ads. Concrete impls wrap
the Meta Ad Library official API, a config-gated third-party Meta fallback, and
the Google Ads Transparency Center.

This mirrors :class:`app.services.lead_discovery.protocol.LeadDiscoveryProvider`
so the two pipelines compose. Hard failures raise
``app.services.lead_discovery.errors.LeadDiscoveryProviderError`` (and
subclasses); soft failures are reported via ``AdProviderResult.warnings``.
"""

from __future__ import annotations

from typing import ClassVar, Protocol, runtime_checkable

from app.services.ad_intelligence.types import AdProviderResult, AdSearchRequest


@runtime_checkable
class AdIntelligenceProvider(Protocol):
    """Structural interface every ad-library provider must satisfy."""

    platform: ClassVar[str]
    """Identifier matching ``AdPlatform`` values (``"meta"`` / ``"google"``)."""

    async def search(self, request: AdSearchRequest) -> AdProviderResult:
        """Run one ad-library query and return normalized advertisers + ads.

        Implementations:
            * Map every native ad into :class:`NormalizedAd`, grouped under the
              owning :class:`NormalizedAdvertiser`.
            * Raise ``LeadDiscoveryProviderError`` (or a subclass) on hard
              failures (auth, rate-limit, upstream errors).
            * Capture soft failures via ``AdProviderResult.warnings``.
            * Never log token-bearing values (access tokens, snapshot URLs).
        """
        ...

    async def close(self) -> None:
        """Release any pooled resources (HTTP clients, sockets)."""
        ...


class BaseAdIntelligenceProvider:
    """Convenience base for in-process providers.

    Provides a typed ``platform`` class attribute and a no-op ``close()`` for
    providers that hold no resources.
    """

    platform: ClassVar[str]

    async def search(
        self, request: AdSearchRequest
    ) -> AdProviderResult:  # pragma: no cover - abstract
        raise NotImplementedError

    async def close(self) -> None:
        """Default to no-op; subclasses with HTTP clients should override."""
        return None
