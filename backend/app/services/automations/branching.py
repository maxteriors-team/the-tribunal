"""Branch conditions for workflows — "did this record match?" as one query.

A ``branch`` step asks a yes/no question about the record standing in front of
it, then :mod:`app.services.automations.runner` decides where that answer sends
the run.

Why the subject is not always a contact
---------------------------------------
The original implementation could only ask about contacts. That is the right
subject for a welcome drip and the wrong one for most sequences that matter: a
quote revival ladder parked in a 30-day wait has to ask *"is **this** quote
still unsold?"*, and a contact-shaped branch physically cannot — a customer with
three open quotes has one contact row and three different answers.

So a branch resolves against a **subject**: the entity the run is about, carried
on the execution as ``(subject_type, subject_id)``. ``contact`` remains the
default and the overwhelmingly common case, which is why every existing
automation keeps working untouched.

Why this reuses the resource filter engines
-----------------------------------
The obvious implementation is a fresh in-memory predicate evaluator over the
loaded record. This module deliberately does not do that. The product already
has one rule language — the JSON ``filter_rules`` that power the contacts list,
saved segments and campaign targeting — and the per-resource filter modules
(``contact_filters``, ``quote_filters``, ``opportunity_filters``, …) are its
single source of truth. Reusing them buys three things a second evaluator would
each have to re-earn:

- **One semantics.** "Lead score over 50" means precisely the same thing in a
  workflow branch as in the list the operator built it from. Two evaluators
  would drift, and would drift silently.
- **Fields for free**, including relationship-backed ones like tags and the
  JSONB qualification signals that an attribute-walking predicate cannot see.
  ``sms_consent_status`` comes along too, which is what makes a consent-aware
  branch expressible at all.
- **The frontend's existing filter builder** can author branch conditions with
  no second UI.

The cost is one query per branch step. It is scoped to a single primary key
(``WHERE <table>.id = :id``), so Postgres answers from the PK index and the
rules only ever narrow that one row.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contact import Contact
from app.models.field_service import Job
from app.models.invoice import Invoice
from app.models.opportunity import Opportunity
from app.models.quote import Quote
from app.services.contacts.contact_filters import apply_contact_filters
from app.services.invoices.invoice_filters import apply_invoice_filters
from app.services.jobs.job_filters import apply_job_filters
from app.services.opportunities.opportunity_filters import apply_opportunity_filters
from app.services.quotes.quote_filters import apply_quote_filters

__all__ = [
    "SUBJECT_CONTACT",
    "SUBJECT_TYPES",
    "contact_matches_rules",
    "parse_branch_condition",
    "subject_matches_rules",
]

SUBJECT_CONTACT = "contact"

# Subject type -> (model, filter applier). Every applier already has the same
# shape: ``(query, workspace_id, filter_rules=..., filter_logic=...)`` returning
# the narrowed query, which is why adding a subject is a dict entry rather than
# a new evaluator.
_SUBJECT_FILTERS: dict[str, tuple[Any, Any]] = {
    SUBJECT_CONTACT: (Contact, apply_contact_filters),
    "quote": (Quote, apply_quote_filters),
    "opportunity": (Opportunity, apply_opportunity_filters),
    "job": (Job, apply_job_filters),
    "invoice": (Invoice, apply_invoice_filters),
}

SUBJECT_TYPES: tuple[str, ...] = tuple(_SUBJECT_FILTERS)

# Accepted top-level combinators, normalized to what apply_contact_filters wants.
_LOGIC_ALIASES: dict[str, str] = {
    "and": "and",
    "all": "and",
    "or": "or",
    "any": "or",
}


def parse_branch_condition(config: Any) -> tuple[list[dict[str, Any]], str]:
    """Extract ``(filter_rules, filter_logic)`` from a branch step's config.

    Tolerates the shapes a JSONB column actually arrives in — missing keys, a
    single rule written as a bare object instead of a list, ``"all"``/``"any"``
    spellings of the combinator. Returns an empty rule list when nothing usable
    is present; the caller decides what an empty condition means (see
    :func:`contact_matches_rules`).
    """
    if not isinstance(config, dict):
        return [], "and"

    raw_rules = config.get("conditions", config.get("filter_rules"))
    if isinstance(raw_rules, dict):
        raw_rules = [raw_rules]
    if not isinstance(raw_rules, list):
        return [], "and"

    rules = [rule for rule in raw_rules if isinstance(rule, dict) and rule]

    raw_logic = config.get("logic", config.get("filter_logic", "and"))
    logic = _LOGIC_ALIASES.get(str(raw_logic).strip().lower(), "and")
    return rules, logic


async def subject_matches_rules(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    subject_id: Any,
    rules: list[dict[str, Any]],
    logic: str = "and",
    subject_type: str = SUBJECT_CONTACT,
) -> bool:
    """Whether the record identified by ``(subject_type, subject_id)`` matches.

    An **empty rule list matches**. A branch with no condition configured is a
    half-built step, and the readable behaviour is "carry on down the main path"
    rather than silently diverting every customer to the else-branch — which,
    in a workflow, usually means falling out of the sequence entirely.

    An **unknown subject type also matches**, for the same reason: a workflow
    naming a subject this build does not know about is a configuration error,
    and stalling the run mid-sequence is a worse answer than carrying on down
    the path the author drew.

    A **missing subject does not match**. Unlike the two cases above this is not
    ambiguity but an answered question: the quote was deleted, so it is not
    still unsold.

    The record is re-read through the filter query rather than inspected in
    memory on purpose: a workflow resumed after a three-day wait must branch on
    the record's state *now*, not on the attributes loaded before the wait.
    """
    if not rules:
        return True

    if subject_id is None:
        return False

    entry = _SUBJECT_FILTERS.get((subject_type or SUBJECT_CONTACT).strip().lower())
    if entry is None:
        return True

    model, apply_filters = entry

    query = select(model.id).where(
        model.id == subject_id,
        model.workspace_id == workspace_id,
    )
    query = apply_filters(
        query,
        workspace_id,
        filter_rules=rules,
        filter_logic=logic,
    )

    result = await db.execute(query.limit(1))
    return result.scalar_one_or_none() is not None


async def contact_matches_rules(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    contact_id: int,
    rules: list[dict[str, Any]],
    logic: str = "and",
) -> bool:
    """Contact-subject shorthand for :func:`subject_matches_rules`.

    Retained because contacts are the default subject, and most call sites and
    tests read better naming the entity they actually mean.
    """
    return await subject_matches_rules(
        db,
        workspace_id=workspace_id,
        subject_id=contact_id,
        rules=rules,
        logic=logic,
        subject_type=SUBJECT_CONTACT,
    )
