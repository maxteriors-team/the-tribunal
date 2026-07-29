"""Attach-rule evaluation: does this quote need a cross-sell prompt?

The companion to :mod:`app.services.quotes.attach_metrics`. Metrics answer *what
rode along* after the fact; this answers *what should have* — at save time, while
the rep is still in front of the customer and the number can still change.

Deliberately pure and I/O-free: no session, no ORM classes, no workspace lookup.
It takes a config, the quote's primary service and the categories actually on the
quote, and returns a warning or nothing — which is what makes every rule mode
testable without a database.

Category matching is case- and whitespace-insensitive on purpose.
``service_category`` is free-form text an operator types into the price book, so
"Gutters" on a catalog item and "gutters" in a rule are the same trade, and a
rule that silently never fires because of a capital G is worse than no rule.
"""

from collections.abc import Iterable

from app.schemas.attach_rules import (
    DEFAULT_PROMPT_TEMPLATE,
    AttachRule,
    AttachRulesSettings,
    AttachWarning,
)


def _norm(raw: str | None) -> str | None:
    """Return a category folded for comparison, or None when there is none.

    Blank and whitespace-only strings fold to ``None`` exactly like NULL: an
    unclassified line must not match a rule keyed on the empty string.
    """
    if raw is None:
        return None
    cleaned = raw.strip().casefold()
    return cleaned or None


def render_prompt(template: str, primary: str) -> str:
    """Render the operator's prompt copy for a primary service.

    ``{primary}`` is the only supported placeholder. A hand-edited template that
    references an unknown one (``{gutters}``), leaves a brace unclosed, or uses a
    stray positional slot must not raise: the operator would have broken every
    quote save in the workspace from a text box. Those fall back to the shipped
    copy, which always renders.
    """
    try:
        return template.format(primary=primary)
    except (KeyError, IndexError, ValueError):
        return DEFAULT_PROMPT_TEMPLATE.format(primary=primary)


def find_rule(config: AttachRulesSettings, primary_service: str | None) -> AttachRule | None:
    """The first rule matching ``primary_service``, or None.

    First match wins rather than last or "most specific": the rules list is an
    ordered, operator-authored list, so duplicates are an editing mistake and the
    top one is the one they can see without scrolling.
    """
    primary = _norm(primary_service)
    if primary is None:
        return None
    for rule in config.rules:
        if _norm(rule.primary_category) == primary:
            return rule
    return None


def evaluate_attach_rules(
    config: AttachRulesSettings,
    *,
    primary_service: str | None,
    present_categories: Iterable[str | None],
) -> AttachWarning | None:
    """Return the attach warning this quote earns, or None when it is fine.

    ``None`` — meaning "say nothing" — for every one of these, because a prompt
    the rep cannot act on is noise that trains them to ignore the real ones:

    * the workspace switched attach prompts off;
    * the quote has no ``primary_service`` (nothing categorized, so there is no
      job type to reason about);
    * no rule covers this primary service;
    * the matching rule is muted (``mode="off"``);
    * the rule suggests nothing actionable (an empty list, or only the primary
      service itself);
    * at least one suggested category is already on the quote — the attach
      conversation demonstrably happened.

    Otherwise the returned :class:`AttachWarning` carries every suggested
    category (none are present, by definition) plus the rendered prompt and the
    dismissal vocabulary, so the builder can offer "Add gutters" directly rather
    than only reporting a policy violation.
    """
    if not config.enabled:
        return None

    primary = _norm(primary_service)
    rule = find_rule(config, primary_service)
    if primary is None or rule is None:
        return None
    mode = rule.mode
    if mode == "off":
        return None

    # A rule suggesting its own primary category can never be satisfied, so it
    # would prompt forever. Drop it rather than nag.
    suggested = [c for c in rule.suggested_categories if _norm(c) not in (None, primary)]
    present = {_norm(c) for c in present_categories}
    if not suggested or any(_norm(c) in present for c in suggested):
        return None

    # Display the primary service as the operator spelled it in the rule, not as
    # the price book happened to capitalize it on this quote's lines.
    label = rule.primary_category.strip() or primary
    return AttachWarning(
        primary_service=label,
        suggested_categories=suggested,
        mode=mode,
        message=render_prompt(config.prompt_template, label),
        dismissal_reasons=list(config.dismissal_reasons),
        require_dismissal_reason=config.require_dismissal_reason,
    )
