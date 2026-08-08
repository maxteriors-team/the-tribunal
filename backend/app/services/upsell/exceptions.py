"""On-site upsell domain exceptions.

Raised by :mod:`app.services.upsell.upsell_service` instead of coupling to
web-framework types. The API boundary maps these to HTTP responses via
:class:`app.api.service_errors.ServiceErrorRoute`. The HTTP status each maps to
is shown in brackets.

Note there is no "not your job" error: an unassigned job raises the field-service
``JobNotFoundError`` (404) so a caller cannot use the response to discover which
job ids exist in the workspace.
"""

from __future__ import annotations

from app.services.exceptions import NotFoundError, PermissionDeniedError, ValidationError


class UpsellNotASellerError(PermissionDeniedError):
    """The caller's role may not sell on site. [403]

    Belt to the router's ``CanUpsell`` braces. The service takes ``role`` as a
    plain string, so this keeps "a plain technician does not quote" true of the
    service itself rather than only of the one router that currently mounts it —
    a second caller (a job-completion hook, a script, a future route) cannot sell
    as a technician by forgetting a dependency.

    403 rather than the 404 used for job scoping: this leaks nothing about which
    jobs or items exist, only that the caller's own role cannot sell, which they
    can already see in their own nav.
    """

    def __init__(
        self,
        message: str = "Your role cannot send proposals. Ask a lead tech to send it.",
    ) -> None:
        super().__init__(message)


class UpsellNoLineItemsError(ValidationError):
    """A proposal was submitted with no line items. [400]"""

    def __init__(self, message: str = "Add at least one add-on to send a proposal") -> None:
        super().__init__(message)


class UpsellItemNotAttachableError(ValidationError):
    """A requested item is not sellable as an on-site add-on. [400]

    Covers every disqualifying case at once — unknown id, archived item, item in
    another workspace, or an item that is simply not flagged ``is_attachable`` —
    because distinguishing them would leak the shape of the workspace's price
    book to the narrowest tier in the product.
    """

    def __init__(self, message: str = "That item is not available as an add-on") -> None:
        super().__init__(message)


class UpsellCarePlanUnavailableError(ValidationError):
    """The requested Care Plan tier is not offered by this workspace. [400]

    Covers an unknown tier key and a workspace with no tiers configured at all.
    Tier keys come from the workspace's pricing config, which an operator can
    edit at any time, so a technician's phone can hold a key that stopped
    existing mid-shift — that must read as "pick again", not a 500.
    """

    def __init__(self, message: str = "That care plan is no longer offered") -> None:
        super().__init__(message)


class UpsellProposalLimitError(ValidationError):
    """The proposal exceeds what this technician may sell on their own. [400]

    Raised only for the ``field`` tier, and only when the workspace configured
    ``PricingSettings.upsell.field_proposal_limit``. A ``lead_technician`` holds
    ``upsell:sell_uncapped`` and never sees this.

    The message names both numbers and the way forward: a technician standing in
    a customer's yard needs to know what to do next, not merely that they were
    refused.
    """

    def __init__(self, total: float, limit: float) -> None:
        super().__init__(
            f"This proposal comes to ${total:,.2f}, over your ${limit:,.2f} "
            "on-site limit. Ask the office to send it."
        )


class UpsellQuoteNotForJobError(NotFoundError):
    """The quote does not belong to the customer on this job. [404]

    The check that stops a technician from pairing a job they *are* assigned to
    with an unrelated quote id and delivering someone else's proposal. 404 rather
    than 403 for the same reason as the job scoping: no existence oracle.
    """

    def __init__(self, message: str = "Quote not found for this job") -> None:
        super().__init__(message)
