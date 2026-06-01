"""Compatibility exports for outbound telephony idempotency.

New code should import from :mod:`app.services.idempotency`; this module keeps
older worker imports stable while sharing the same namespace and derivation.
"""

from __future__ import annotations

import uuid

from app.services.idempotency import OUTBOUND_IDEMPOTENCY_NAMESPACE, derive_outbound_key

# Kept for tests and older imports that pin the namespace contract.
_OUTBOUND_NAMESPACE = OUTBOUND_IDEMPOTENCY_NAMESPACE


def derive(scope: str, *parts: object) -> uuid.UUID:
    """Return the shared deterministic outbound UUID5 key."""
    return derive_outbound_key(scope, *parts)
