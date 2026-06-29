"""Pure mapping from Jobber GraphQL nodes to CRM upsert data.

Kept side-effect-free (no DB, no network) so it is exhaustively unit-testable
and so the sync/import layers can stay focused on persistence. Jobber nests
name/email/phone/address as objects or connections; this module flattens them
defensively because the exact sub-fields available depend on the OAuth scopes
granted to the app.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.models.field_service import JobStatus

# Value written to ``external_source`` for every Jobber-imported row. Also the
# discriminator the sync/import use to scope their idempotency lookups.
EXTERNAL_SOURCE = "jobber"


class JobberMappingError(ValueError):
    """Raised when a Jobber node lacks the fields needed to map it."""


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


# --------------------------------------------------------------------------- #
# Shared helpers for the one-time import (clients / properties / jobs / invoices)
# --------------------------------------------------------------------------- #
def _clean(value: Any) -> str | None:
    """Coerce ``value`` to a trimmed non-empty string, else ``None``."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _primary_value(entries: Any, value_key: str) -> str | None:
    """Pull the primary entry's ``value_key`` from a Jobber email/phone field.

    Jobber returns these as a list of ``{primary, <value_key>, ...}`` (and, in
    some schema versions, a connection with a ``nodes`` list). Accept either,
    preferring the entry flagged ``primary`` and falling back to the first.
    """
    if isinstance(entries, dict):
        entries = entries.get("nodes")
    if not isinstance(entries, list) or not entries:
        return None
    chosen = next(
        (e for e in entries if isinstance(e, dict) and e.get("primary")),
        entries[0] if isinstance(entries[0], dict) else None,
    )
    if not isinstance(chosen, dict):
        return None
    return _clean(chosen.get(value_key))


def _address_fields(address: Any) -> dict[str, Any]:
    """Flatten a Jobber address object to our contact/location column names.

    Jobber addresses use ``street1``/``street2``/``city``/``province``/
    ``postalCode``/``country`` (+ optional ``latitude``/``longitude``).
    """
    if not isinstance(address, dict):
        return {}
    return {
        "address_line1": _clean(address.get("street1")),
        "address_line2": _clean(address.get("street2")),
        "city": _clean(address.get("city")),
        "state": _clean(address.get("province")),
        "postal_code": _clean(address.get("postalCode")),
        "country": _clean(address.get("country")),
        "latitude": _coerce_float(address.get("latitude")),
        "longitude": _coerce_float(address.get("longitude")),
    }


def _coerce_float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _parse_dt(value: Any) -> datetime | None:
    """Parse a Jobber ISO8601 timestamp/date, tolerating a trailing ``Z``."""
    text = _clean(value)
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _parse_date(value: Any) -> Any:
    """Parse a Jobber date (``YYYY-MM-DD`` or ISO timestamp) to a ``date``."""
    dt = _parse_dt(value)
    return dt.date() if dt else None


# --------------------------------------------------------------------------- #
# Clients -> contacts
# --------------------------------------------------------------------------- #
def jobber_client_to_contact_data(node: dict[str, Any]) -> dict[str, Any]:
    """Map a Jobber ``client`` node to ``Contact`` create/update fields.

    Returns the contact columns plus the raw primary ``email``/``phone`` (the
    importer normalizes + hashes those and enforces the NOT-NULL phone). The
    client's billing address is flattened into ``address_*`` columns.

    Raises:
        JobberMappingError: if the node has no id or no derivable name/company —
            ``first_name`` is NOT NULL on contacts.
    """
    external_id = node.get("id")
    if not external_id:
        raise JobberMappingError("Jobber client node is missing an 'id'")

    company = _clean(node.get("companyName"))
    first = _clean(node.get("firstName"))
    last = _clean(node.get("lastName"))
    display = _clean(node.get("name"))

    # ``first_name`` is NOT NULL on contacts. Prefer an explicit person name;
    # then a company name (kept whole, never split); then split a bare display
    # name. Jobber sets ``name`` to the company for company clients, so the
    # company branch must come *before* splitting ``name`` or "Paddy's Pub"
    # would wrongly become first="Paddy's".
    is_company = bool(node.get("isCompany")) or (company is not None and display == company)
    first_name: str
    last_name: str | None
    if first:
        first_name, last_name = first, last
    elif company and (is_company or not display):
        first_name, last_name = company, None
    elif display:
        parts = display.split(None, 1)
        first_name = parts[0]
        last_name = parts[1] if len(parts) > 1 else last
    else:
        raise JobberMappingError(f"Jobber client {external_id!r} has no usable name")

    address = _address_fields(node.get("billingAddress"))
    return {
        "external_source": EXTERNAL_SOURCE,
        "external_id": str(external_id),
        "first_name": first_name[:100],
        "last_name": last_name[:100] if last_name else None,
        "company_name": company[:255] if company else None,
        "email": _primary_value(node.get("emails"), "address"),
        "phone": _primary_value(node.get("phones"), "number"),
        "address_line1": address.get("address_line1"),
        "address_line2": address.get("address_line2"),
        "address_city": address.get("city"),
        "address_state": address.get("state"),
        "address_zip": address.get("postal_code"),
    }


def jobber_client_properties(node: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the raw property nodes nested under a Jobber client.

    Jobber nests them as ``clientProperties.nodes``; an absent/empty connection
    yields ``[]`` so the importer can simply iterate.
    """
    connection = node.get("clientProperties")
    if not isinstance(connection, dict):
        return []
    nodes = connection.get("nodes")
    return [n for n in nodes if isinstance(n, dict)] if isinstance(nodes, list) else []


def jobber_property_to_location_data(node: dict[str, Any]) -> dict[str, Any]:
    """Map a Jobber ``property`` node to ``ServiceLocation`` create/update fields.

    Raises:
        JobberMappingError: if the node has no id (the idempotency key).
    """
    external_id = node.get("id")
    if not external_id:
        raise JobberMappingError("Jobber property node is missing an 'id'")

    address = _address_fields(node.get("address"))
    # A human label for the site: first address line, else the city.
    name = address.get("address_line1") or address.get("city")
    data: dict[str, Any] = {
        "external_source": EXTERNAL_SOURCE,
        "external_id": str(external_id),
        "name": name[:200] if name else None,
        "address_line1": address.get("address_line1"),
        "address_line2": address.get("address_line2"),
        "city": address.get("city"),
        "state": address.get("state"),
        "postal_code": address.get("postal_code"),
        "latitude": address.get("latitude"),
        "longitude": address.get("longitude"),
    }
    country = address.get("country")
    if country:
        # ServiceLocation.country is a 2-char NOT NULL column (defaults to US).
        data["country"] = country[:2].upper()
    return data


# --------------------------------------------------------------------------- #
# Jobs -> field_service_jobs
# --------------------------------------------------------------------------- #
# Explicit terminal/unscheduled Jobber statuses; everything else is derived from
# whether the job has a scheduled start (see ``map_jobber_job_status``).
_JOBBER_JOB_STATUS_MAP = {
    "complete": JobStatus.COMPLETED,
    "completed": JobStatus.COMPLETED,
    "archived": JobStatus.COMPLETED,
    "cancelled": JobStatus.CANCELLED,
    "canceled": JobStatus.CANCELLED,
    "unscheduled": JobStatus.UNSCHEDULED,
}


def map_jobber_job_status(raw: Any, *, has_start: bool) -> JobStatus:
    """Map a Jobber ``jobStatus`` to our :class:`JobStatus`.

    Known terminal/unscheduled states map explicitly; any other state (Jobber
    has many scheduling pseudo-statuses like ``active``/``late``/``today``)
    becomes ``scheduled`` when the job has a time window, else ``unscheduled``.
    """
    key = _clean(raw)
    if key and key.lower() in _JOBBER_JOB_STATUS_MAP:
        return _JOBBER_JOB_STATUS_MAP[key.lower()]
    return JobStatus.SCHEDULED if has_start else JobStatus.UNSCHEDULED


def jobber_job_to_job_data(node: dict[str, Any]) -> dict[str, Any]:
    """Map a Jobber ``job`` node to ``Job`` fields + the ids to resolve.

    The returned dict carries the persistable ``Job`` columns plus three
    resolution keys the importer turns into FKs: ``client_external_id`` (the
    customer — required), ``property_external_id`` (the site — optional), and
    ``assigned_user_external_ids`` (technicians to tag).

    Raises:
        JobberMappingError: if the node has no id or no client reference (a job
            must belong to a customer — ``contact_id`` is NOT NULL).
    """
    external_id = node.get("id")
    if not external_id:
        raise JobberMappingError("Jobber job node is missing an 'id'")

    client = node.get("client")
    client_external_id = _clean(client.get("id")) if isinstance(client, dict) else None
    if not client_external_id:
        raise JobberMappingError(f"Jobber job {external_id!r} has no client reference")

    prop = node.get("property")
    property_external_id = _clean(prop.get("id")) if isinstance(prop, dict) else None

    assigned = node.get("assignedUsers")
    if isinstance(assigned, dict):
        assigned = assigned.get("nodes")
    assigned_ids = (
        [_clean(u.get("id")) for u in assigned if isinstance(u, dict) and _clean(u.get("id"))]
        if isinstance(assigned, list)
        else []
    )

    start = _parse_dt(node.get("startAt"))
    end = _parse_dt(node.get("endAt"))

    number = _clean(node.get("jobNumber"))
    title = _clean(node.get("title")) or (f"Job #{number}" if number else "Imported job")

    return {
        "external_source": EXTERNAL_SOURCE,
        "external_id": str(external_id),
        "title": title[:200],
        "description": _clean(node.get("instructions")),
        "status": map_jobber_job_status(node.get("jobStatus"), has_start=start is not None),
        "scheduled_start": start,
        "scheduled_end": end,
        "client_external_id": client_external_id,
        "property_external_id": property_external_id,
        "assigned_user_external_ids": assigned_ids,
    }


# --------------------------------------------------------------------------- #
# Invoices -> invoices (historical / AR only)
# --------------------------------------------------------------------------- #
# Jobber InvoiceStatusTypeEnum -> our invoice status set. Imported invoices are
# never re-billed, so an unknown/issued state maps to ``sent`` (an open AR item).
_JOBBER_INVOICE_STATUS_MAP = {
    "draft": "draft",
    "paid": "paid",
    "partial": "partial",
    "awaiting_payment": "sent",
    "past_due": "overdue",
    "bad_debt": "void",
}


def map_jobber_invoice_status(raw: Any) -> str:
    """Map a Jobber ``invoiceStatus`` to our invoice status string."""
    key = _clean(raw)
    if key and key.lower() in _JOBBER_INVOICE_STATUS_MAP:
        return _JOBBER_INVOICE_STATUS_MAP[key.lower()]
    return "sent"


def jobber_invoice_to_invoice_data(node: dict[str, Any]) -> dict[str, Any]:
    """Map a Jobber ``invoice`` node to ``Invoice`` fields + the client id.

    Imports money as-is for historical/AR visibility; the importer never sends
    or re-bills these. ``client_external_id`` is resolved to a contact FK.

    Raises:
        JobberMappingError: if the node has no id (the idempotency key).
    """
    external_id = node.get("id")
    if not external_id:
        raise JobberMappingError("Jobber invoice node is missing an 'id'")

    raw_amounts = node.get("amounts")
    amounts: dict[str, Any] = raw_amounts if isinstance(raw_amounts, dict) else {}
    subtotal = _coerce_float(amounts.get("subtotal")) or 0.0
    total = _coerce_float(amounts.get("total")) or 0.0
    tax = _coerce_float(amounts.get("taxAmount")) or 0.0
    discount = _coerce_float(amounts.get("discountAmount")) or 0.0
    paid = _coerce_float(amounts.get("paymentsTotal")) or 0.0

    client = node.get("client")
    client_external_id = _clean(client.get("id")) if isinstance(client, dict) else None

    number = _clean(node.get("invoiceNumber")) or f"JOBBER-{external_id}"
    return {
        "external_source": EXTERNAL_SOURCE,
        "external_id": str(external_id),
        "number": number[:50],
        "status": map_jobber_invoice_status(node.get("invoiceStatus")),
        "subtotal": subtotal,
        "tax_amount": tax,
        "discount_amount": discount,
        "total": total,
        "amount_paid": paid,
        "issue_date": _parse_date(node.get("issuedDate")),
        "due_date": _parse_date(node.get("dueDate")),
        "notes": _clean(node.get("message")),
        "client_external_id": client_external_id,
    }
