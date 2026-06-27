"""Pure mapping from a Jobber ``user`` node to technician upsert data.

Kept side-effect-free (no DB, no network) so it is exhaustively unit-testable
and so the sync layer can stay focused on persistence. Jobber's ``User`` nests
name/email/phone as objects; this module flattens them defensively because the
exact sub-fields available depend on the OAuth scopes granted to the app.
"""

from __future__ import annotations

from typing import Any

# Value written to ``Technician.external_source`` for every Jobber-imported row.
# Also the discriminator the sync uses to scope its idempotency lookups.
EXTERNAL_SOURCE = "jobber"


class JobberMappingError(ValueError):
    """Raised when a Jobber user node lacks the fields needed to map it."""


def _nested(node: dict[str, Any], key: str, sub: str) -> str | None:
    """Return ``node[key][sub]`` as a non-empty string, else ``None``."""
    value = node.get(key)
    if not isinstance(value, dict):
        return None
    raw = value.get(sub)
    if raw is None:
        return None
    text = str(raw).strip()
    return text or None


def _full_name(node: dict[str, Any]) -> str | None:
    """Best-effort display name: ``name.full`` then ``first + last``."""
    full = _nested(node, "name", "full")
    if full:
        return full
    first = _nested(node, "name", "first")
    last = _nested(node, "name", "last")
    joined = " ".join(part for part in (first, last) if part)
    return joined or None


def jobber_user_to_technician_data(node: dict[str, Any]) -> dict[str, Any]:
    """Map a Jobber ``user`` node to ``Technician`` create/update fields.

    Returns a dict with ``external_source``, ``external_id``, ``name``,
    ``email`` and ``phone``. ``crew_id``/``is_active`` are intentionally not set
    here — crew assignment is locally managed and activation is owned by the
    sync layer (which knows the full picture across pages).

    Raises:
        JobberMappingError: if the node has no id or no derivable name. Both are
            required — the id is the idempotency key and the name is NOT NULL on
            the technician table.
    """
    external_id = node.get("id")
    if not external_id:
        raise JobberMappingError("Jobber user node is missing an 'id'")

    name = _full_name(node)
    if not name:
        raise JobberMappingError(f"Jobber user {external_id!r} has no usable name")

    return {
        "external_source": EXTERNAL_SOURCE,
        "external_id": str(external_id),
        "name": name[:200],  # Technician.name is String(200)
        "email": (_nested(node, "email", "raw") or None),
        "phone": (_nested(node, "phone", "friendly") or None),
    }
