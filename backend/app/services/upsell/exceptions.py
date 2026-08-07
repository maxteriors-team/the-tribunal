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

from app.services.exceptions import NotFoundError, ValidationError


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


class UpsellQuoteNotForJobError(NotFoundError):
    """The quote does not belong to the customer on this job. [404]

    The check that stops a technician from pairing a job they *are* assigned to
    with an unrelated quote id and delivering someone else's proposal. 404 rather
    than 403 for the same reason as the job scoping: no existence oracle.
    """

    def __init__(self, message: str = "Quote not found for this job") -> None:
        super().__init__(message)
