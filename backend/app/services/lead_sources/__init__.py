"""Lead-source domain: attribution, capture policy, and referral partners.

Services here raise typed errors from :mod:`.exceptions` rather than
``HTTPException`` so workers and other services can reuse them; the API layer
maps those to responses via :class:`app.api.service_errors.ServiceErrorRoute`.
"""

from app.services.lead_sources.exceptions import (
    ReferralPartnerContactNotFoundError,
    ReferralPartnerNameConflictError,
    ReferralPartnerNotFoundError,
)
from app.services.lead_sources.referral_partner_service import (
    PartnerReferralAggregate,
    ReferralPartnerService,
    build_scoreboard,
    build_scoreboard_row,
    days_since,
)

__all__ = [
    "PartnerReferralAggregate",
    "ReferralPartnerContactNotFoundError",
    "ReferralPartnerNameConflictError",
    "ReferralPartnerNotFoundError",
    "ReferralPartnerService",
    "build_scoreboard",
    "build_scoreboard_row",
    "days_since",
]
