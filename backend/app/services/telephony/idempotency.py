"""Stable idempotency-key derivation for outbound Telnyx sends.

Workers that may crash between writing the outbound ``Message`` row and the
Telnyx HTTP call use these helpers to compute a deterministic UUID5 from
domain identifiers. On retry the worker hands the same key back to
``TelnyxSMSService.send_message`` / ``TelnyxVoiceService.initiate_call``,
which short-circuits if a row with that key already exists and forwards
the key to Telnyx as ``X-Idempotency-Key`` (or ``client_state`` for Call
Control) so the provider also dedupes.

The namespace is a fixed UUID5(DNS, "thetribunal.outbound") so keys are
stable across process restarts and machines, and a separate ``scope``
string per worker prevents collisions between, say, a reminder send and a
campaign send that happen to share an entity id.
"""

from __future__ import annotations

import uuid

# A fixed namespace UUID under which every outbound idempotency key is
# derived. Chosen once, never rotated \u2014 changing it would invalidate
# every in-flight retry's key and break the dedupe guarantee.
_OUTBOUND_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_DNS, "thetribunal.outbound.v1")


def derive(scope: str, *parts: object) -> uuid.UUID:
    """Return a deterministic UUID5 for ``(scope, *parts)``.

    ``scope`` is a short worker-owned string (e.g. ``'reminder'``,
    ``'campaign_sms'``) that namespaces the key so two different
    workers can use the same entity id without colliding. ``parts`` are
    stringified and joined with ``':'`` to form the unique key body.

    Examples:
        >>> derive("reminder", appointment_id, offset_minutes)
        UUID('...')

        >>> derive("campaign_sms", campaign_contact_id, follow_up_number)
        UUID('...')
    """
    body = scope + ":" + ":".join(str(p) for p in parts)
    return uuid.uuid5(_OUTBOUND_NAMESPACE, body)
