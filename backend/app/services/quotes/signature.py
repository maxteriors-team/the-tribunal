"""The e-signature ceremony carried from the public route into the service.

A small transport type rather than passing four loose arguments, so the
"all-or-nothing" rule that the database enforces
(``ck_quotes_signature_complete``) has one place to be expressed in Python too.

The IP is supplied by the route via :func:`app.core.utils.get_client_ip`, which
only honours ``X-Forwarded-For`` from a trusted proxy. It is deliberately not
read from headers here: a service that reaches into the request for a
client-controlled value is how forged evidence gets recorded.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["SignatureCeremony"]


@dataclass(frozen=True, slots=True)
class SignatureCeremony:
    """One customer's act of signing, as observed by the server."""

    signed_name: str | None
    econsent_accepted: bool
    cancellation_acknowledged: bool
    ip_address: str
    # The terms text exactly as the customer was shown it, resolved by the route
    # from the same expression the public proposal page renders.
    terms_snapshot: str | None

    @property
    def is_complete(self) -> bool:
        """True when this is a signature rather than a partial submission.

        The terms snapshot is intentionally *not* required: a workspace that has
        written no terms at all still produces a valid signature, and the
        document says so explicitly instead of implying terms existed.
        """
        return bool(self.signed_name and self.econsent_accepted and self.cancellation_acknowledged)
