"""Lead-source domain exceptions.

Raised by the lead-source services instead of coupling to web-framework types
like ``HTTPException``. The API boundary maps these to HTTP responses via
:class:`app.api.service_errors.ServiceErrorRoute`, while non-HTTP callers
(workers, automations, other services) catch them directly. The HTTP status each
maps to is shown in brackets.
"""

from __future__ import annotations

from app.services.exceptions import ConflictError, NotFoundError


class ReferralPartnerNotFoundError(NotFoundError):
    """A referral partner does not exist in the workspace. [404]"""

    def __init__(self, message: str = "Referral partner not found") -> None:
        super().__init__(message)


class ReferralPartnerNameConflictError(ConflictError):
    """A partner with the same name already exists in the workspace. [409]

    Duplicate rows would split one partner's referral history across two
    scoreboard lines, which is exactly the blindness this feature removes.
    """

    def __init__(self, message: str = "A referral partner with this name already exists") -> None:
        super().__init__(message)


class ReferralPartnerContactNotFoundError(NotFoundError):
    """The contact linked to a partner does not belong to the workspace. [404]"""

    def __init__(self, message: str = "Contact not found") -> None:
        super().__init__(message)
