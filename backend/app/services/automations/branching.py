"""Branch conditions for workflows — "did this contact match?" as one query.

A ``branch`` step asks a yes/no question about the contact standing in front of
it, then :mod:`app.services.automations.runner` decides where that answer sends
the run.

Why this reuses ``contact_filters``
-----------------------------------
The obvious implementation is a fresh in-memory predicate evaluator over the
loaded ``Contact``. This module deliberately does not do that. The product
already has one rule language — the JSON ``filter_rules`` that power the
contacts list, saved segments and campaign targeting — and
:func:`app.services.contacts.contact_filters.apply_contact_filters` is its
single source of truth. Reusing it buys three things a second evaluator would
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
(``WHERE contacts.id = :id``), so Postgres answers from the PK index and the
rules only ever narrow that one row.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contact import Contact
from app.services.contacts.contact_filters import apply_contact_filters

__all__ = ["contact_matches_rules", "parse_branch_condition"]

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


async def contact_matches_rules(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    contact_id: int,
    rules: list[dict[str, Any]],
    logic: str = "and",
) -> bool:
    """Whether ``contact_id`` satisfies ``rules``.

    An **empty rule list matches**. A branch with no condition configured is a
    half-built step, and the readable behaviour is "carry on down the main path"
    rather than silently diverting every customer to the else-branch — which,
    in a workflow, usually means falling out of the sequence entirely.

    The contact is re-read through the filter query rather than inspected in
    memory on purpose: a workflow resumed after a three-day wait must branch on
    the customer's state *now*, not on the attributes loaded before the wait.
    """
    if not rules:
        return True

    query = select(Contact.id).where(
        Contact.id == contact_id,
        Contact.workspace_id == workspace_id,
    )
    query = apply_contact_filters(
        query,
        workspace_id,
        filter_rules=rules,
        filter_logic=logic,
    )

    result = await db.execute(query.limit(1))
    return result.scalar_one_or_none() is not None
