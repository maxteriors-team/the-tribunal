"""Which access tiers an operator notification is actually *for*.

:mod:`app.core.permissions` answers "what may this role do". This module answers
the adjacent question the notification fan-outs kept getting wrong: "what should
this role be *told about*".

Both operator channels used to answer it separately, and both answered badly.
Push (:meth:`~app.services.push_notifications.PushNotificationService.send_to_workspace_members`)
notified *every* membership row with no role filter at all, so a field
technician's phone buzzed for every deposit a customer paid — money news they
have no seat to act on and, per the capability matrix, no screen to open. Email
went the other way and hard-coded a single office allow-list, so the sales rep
who owns the deal learned nothing when its deposit landed.

One matrix now drives both, keyed on the same ``notification_type`` string the
channels already carry, so a type can never mean two different audiences
depending on which pipe it went down.

The audiences are deliberately coarse — three of them:

``_REVENUE``  money and customer-demand events (deposits, accepted quotes,
              leads, calls, messages, appointments). Anyone who sells or runs
              the day: admin, manager/dispatcher, **and sales**.
``_OFFICE``   back-office system noise (reviews, roleplay scores, automation
              failures). Admin and manager only; a sales rep cannot act on a
              failed automation.
``_ADMIN``    the fail-closed default for an unrecognised or absent type.

Field roles (``technician``, ``lead_technician``) appear in exactly one entry:
``job_assignment``, the work they are actually being dispatched to. That single
exception is why this is a per-type map rather than a rank threshold.

Unknown types and ``None`` resolve to ``_ADMIN`` rather than "everyone", so
adding a notification type without thinking about its audience under-notifies
the owner instead of spamming the whole crew. Adding the type here is the
deliberate step that widens it.
"""

from __future__ import annotations

from app.core.permissions import Tier, role_tier
from app.core.roles import ROLE_RANK

# Admin only. Also the fail-closed default for unmapped types.
_ADMIN = frozenset({Tier.ADMIN})
# Runs the business day-to-day. ``dispatcher`` collapses into MANAGER.
_OFFICE = _ADMIN | {Tier.MANAGER}
# Everyone with a commercial stake in the customer, sales included.
_REVENUE = _OFFICE | {Tier.SALES}
# Dispatch: the crew is the point.
_EVERYONE = frozenset(Tier)

# notification_type -> tiers that should hear about it, on any channel.
_TYPE_AUDIENCE: dict[str, frozenset[Tier]] = {
    # Money.
    "payment": _REVENUE,
    "quote_accepted": _REVENUE,
    # Customer demand.
    "new_lead": _REVENUE,
    "deal_alert": _REVENUE,
    "missed_call_textback": _REVENUE,
    "appointment": _REVENUE,
    "sla": _REVENUE,
    # Live customer comms.
    "call": _REVENUE,
    "message": _REVENUE,
    "voicemail": _REVENUE,
    # Back-office system noise.
    "review": _OFFICE,
    "roleplay": _OFFICE,
    "automation": _OFFICE,
    # The one thing the field tier is here for.
    "job_assignment": _EVERYONE,
}


def audience_for(notification_type: str | None) -> frozenset[Tier]:
    """Return the tiers that should receive ``notification_type``."""
    if notification_type is None:
        return _ADMIN
    return _TYPE_AUDIENCE.get(notification_type, _ADMIN)


def role_receives(role: str, notification_type: str | None) -> bool:
    """Return whether a membership ``role`` should be told about this event.

    Unknown role strings resolve to :data:`~app.core.permissions.Tier.FIELD` via
    :func:`role_tier`, so a corrupt value receives dispatch only.
    """
    return role_tier(role) in audience_for(notification_type)


def roles_for(notification_type: str | None) -> tuple[str, ...]:
    """Return the role strings to filter a recipient query on, for SQL ``IN``.

    Only *known* roles can be enumerated, so a corrupt role string is dropped by
    a query built from this even where :func:`role_receives` would keep it. That
    divergence is confined to ``job_assignment``, the sole audience containing
    the field tier — and that path always targets explicit user ids, never a
    role filter.
    """
    audience = audience_for(notification_type)
    return tuple(role for role in ROLE_RANK if role_tier(role) in audience)


__all__ = ("audience_for", "role_receives", "roles_for")
