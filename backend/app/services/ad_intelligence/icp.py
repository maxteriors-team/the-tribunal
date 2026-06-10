"""ICP threshold + filter layer for ad-library advertisers.

The product targets advertisers who spend **consistently** but **don't iterate**
their creatives — the people we can help start proper creative testing. This
layer applies workspace-configurable thresholds that:

1. **Require** the "consistent, long-running spender" signal (inclusion floors).
2. **Exclude prolific testers** — advertisers already running many distinct
   creatives / refreshing often (the 20-100 UGC-variation crowd). They already
   test at scale and are not our buyer (exclusion ceilings).

It is pure + DB-agnostic: :func:`qualifies` evaluates one advertiser's signals,
:func:`ranked_advertiser_query` builds the SQLAlchemy filter for ranked lists.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from sqlalchemy import Select, select

from app.models.ad_advertiser import AdAdvertiser

if TYPE_CHECKING:
    import uuid


@dataclass(slots=True, frozen=True)
class IcpProfile:
    """Resolved ICP thresholds used to qualify advertisers.

    Inclusion floors and exclusion ceilings together carve out "consistent but
    not testing". Defaults mirror
    :class:`app.schemas.ad_library.IcpThresholds`.
    """

    # Inclusion floors.
    min_continuity_score: float = 0.5
    min_longest_running_days: int = 60
    min_active_ads: int = 1
    min_opportunity_score: int = 50
    # Exclusion ceilings (disqualify prolific testers).
    max_distinct_creatives: int = 8
    max_active_creatives: int = 12
    max_creative_refresh_rate: float = 4.0

    @classmethod
    def from_overrides(cls, overrides: dict[str, Any] | None) -> IcpProfile:
        """Build a profile from a partial override dict (None-safe)."""
        if not overrides:
            return cls()
        defaults = cls()
        return cls(
            min_continuity_score=_pick(
                overrides, "min_continuity_score", defaults.min_continuity_score
            ),
            min_longest_running_days=_pick(
                overrides, "min_longest_running_days", defaults.min_longest_running_days
            ),
            min_active_ads=_pick(overrides, "min_active_ads", defaults.min_active_ads),
            min_opportunity_score=_pick(
                overrides, "min_opportunity_score", defaults.min_opportunity_score
            ),
            max_distinct_creatives=_pick(
                overrides, "max_distinct_creatives", defaults.max_distinct_creatives
            ),
            max_active_creatives=_pick(
                overrides, "max_active_creatives", defaults.max_active_creatives
            ),
            max_creative_refresh_rate=_pick(
                overrides, "max_creative_refresh_rate", defaults.max_creative_refresh_rate
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "min_continuity_score": self.min_continuity_score,
            "min_longest_running_days": self.min_longest_running_days,
            "min_active_ads": self.min_active_ads,
            "min_opportunity_score": self.min_opportunity_score,
            "max_distinct_creatives": self.max_distinct_creatives,
            "max_active_creatives": self.max_active_creatives,
            "max_creative_refresh_rate": self.max_creative_refresh_rate,
        }


def _pick(overrides: dict[str, Any], key: str, default: Any) -> Any:
    """Return ``overrides[key]`` when present and not None, else ``default``."""
    value = overrides.get(key)
    return value if value is not None else default


@dataclass(slots=True)
class IcpVerdict:
    """Outcome of evaluating one advertiser against an ICP profile."""

    qualified: bool
    disqualifiers: list[str] = field(default_factory=list)


def qualifies(advertiser: AdAdvertiser, profile: IcpProfile) -> IcpVerdict:
    """Evaluate whether ``advertiser`` matches the ICP, with reasons if not."""
    disqualifiers: list[str] = []

    # Inclusion floors.
    if advertiser.active_ad_count < profile.min_active_ads:
        disqualifiers.append(
            f"only {advertiser.active_ad_count} active ads (< {profile.min_active_ads})"
        )
    if advertiser.continuity_score < profile.min_continuity_score:
        disqualifiers.append(
            f"continuity {advertiser.continuity_score:.2f} (< {profile.min_continuity_score:.2f})"
        )
    if advertiser.longest_running_active_days < profile.min_longest_running_days:
        disqualifiers.append(
            f"longest-run {advertiser.longest_running_active_days}d "
            f"(< {profile.min_longest_running_days}d)"
        )
    if advertiser.opportunity_score < profile.min_opportunity_score:
        disqualifiers.append(
            f"score {advertiser.opportunity_score} (< {profile.min_opportunity_score})"
        )

    # Exclusion ceilings — prolific testers are explicitly filtered out.
    if advertiser.distinct_creative_count > profile.max_distinct_creatives:
        disqualifiers.append(
            f"{advertiser.distinct_creative_count} distinct creatives "
            f"(> {profile.max_distinct_creatives}) — already testing at scale"
        )
    if advertiser.active_creative_count > profile.max_active_creatives:
        disqualifiers.append(
            f"{advertiser.active_creative_count} active creatives "
            f"(> {profile.max_active_creatives}) — already testing at scale"
        )
    if advertiser.creative_refresh_rate > profile.max_creative_refresh_rate:
        disqualifiers.append(
            f"refresh {advertiser.creative_refresh_rate:.1f}/30d "
            f"(> {profile.max_creative_refresh_rate:.1f}) — iterating too actively"
        )

    return IcpVerdict(qualified=not disqualifiers, disqualifiers=disqualifiers)


def ranked_advertiser_query(
    workspace_id: uuid.UUID,
    profile: IcpProfile,
    *,
    only_qualified: bool = True,
) -> Select[tuple[AdAdvertiser]]:
    """Build a workspace-scoped, score-ranked advertiser query.

    When ``only_qualified`` is True, applies the same inclusion floors +
    exclusion ceilings as :func:`qualifies` directly in SQL so paginated lists
    stay consistent with single-advertiser evaluation.
    """
    stmt = select(AdAdvertiser).where(AdAdvertiser.workspace_id == workspace_id)
    if only_qualified:
        stmt = stmt.where(
            AdAdvertiser.active_ad_count >= profile.min_active_ads,
            AdAdvertiser.continuity_score >= profile.min_continuity_score,
            AdAdvertiser.longest_running_active_days >= profile.min_longest_running_days,
            AdAdvertiser.opportunity_score >= profile.min_opportunity_score,
            AdAdvertiser.distinct_creative_count <= profile.max_distinct_creatives,
            AdAdvertiser.active_creative_count <= profile.max_active_creatives,
            AdAdvertiser.creative_refresh_rate <= profile.max_creative_refresh_rate,
        )
    return stmt.order_by(AdAdvertiser.opportunity_score.desc(), AdAdvertiser.last_seen_at.desc())
