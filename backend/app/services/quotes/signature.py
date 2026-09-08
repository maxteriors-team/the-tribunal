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

    @property
    def is_complete(self) -> bool:
        """True when this is a signature rather than a partial submission.

        The terms text is not carried here: it is snapshotted inside the locked
        approval transaction from the quote itself, so a signer cannot post back
        an edited copy of what they claim to have agreed to.
        """
        return bool(self.signed_name and self.econsent_accepted and self.cancellation_acknowledged)
