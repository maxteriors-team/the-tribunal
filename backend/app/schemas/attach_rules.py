"""Per-workspace attach-rule (cross-sell prompt) schemas.

The highest-dollar lever on a quote is the *second* service: gutters on a roof,
trim on siding. This config turns "remember to ask" into a rule the platform
enforces at save time, per workspace, with no code change — the operator owns
which primary service prompts for which attach, and how hard the prompt pushes.

Stored as a JSONB blob under ``workspace.settings["attach_rules"]`` and read
through :mod:`app.services.quotes.attach_rules_config`, exactly like the pricing
config and the proposal template. Categories are matched against the free-form
:attr:`app.models.catalog.CatalogItem.service_category` taxonomy, so a workspace
uses its own trade names rather than a fixed enum.

Read leniently (a hand-edited blob never 500s a settings read); write validated
(blank categories and duplicates are cleaned at the edge).
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# How hard a rule pushes when its attach is missing:
#   off       - rule is retained but not evaluated (an operator "mute" that keeps
#               the configured categories around for when they switch it back on)
#   advisory  - the save succeeds and returns a dismissible warning
#   blocking  - the save is rejected until an attach is added or a dismissal
#               reason is supplied
AttachRuleMode = Literal["off", "advisory", "blocking"]

# Placeholder the operator's prompt copy may reference (the quote's primary
# service). Kept as a named constant so the renderer, the schema docstring and
# the settings UI cannot drift on the spelling.
PROMPT_PRIMARY_PLACEHOLDER = "primary"

DEFAULT_PROMPT_TEMPLATE = (
    "This is a {primary} job with no add-on attached. "
    "Ask about the services below before sending it."
)


def _default_dismissal_reasons() -> list[str]:
    """Why a rep skipped the attach — the vocabulary attach reporting groups on."""
    return [
        "Customer declined",
        "Not applicable",
        "Already has",
        "Bundled elsewhere",
    ]


def _clean_categories(values: list[str]) -> list[str]:
    """Trim, drop blanks, and de-duplicate a category list, preserving order.

    Case-insensitive de-duplication with the first spelling winning, because
    ``service_category`` is free-form text an operator types: ``["Gutters", "",
    "gutters"]`` is one suggestion, not three. Cleaning (rather than rejecting)
    keeps a sloppy edit usable instead of failing the whole settings write.
    """
    cleaned: list[str] = []
    seen: set[str] = set()
    for value in values:
        trimmed = value.strip()
        if not trimmed:
            continue
        key = trimmed.casefold()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(trimmed)
    return cleaned


class AttachRule(BaseModel):
    """One rule: when a quote is *this* job, prompt for *these* add-ons.

    ``suggested_categories`` is an any-of test, not an all-of one: a roof quote
    that already carries gutters satisfies a ``roof -> [gutters, trim]`` rule.
    The rep is being reminded to have the conversation, not forced to sell every
    line on the list.
    """

    model_config = ConfigDict(extra="ignore")

    # The quote's ``primary_service`` this rule fires on (a catalog
    # ``service_category`` value, e.g. "roof").
    primary_category: str = Field(min_length=1, max_length=60)
    # Categories worth attaching to that job, e.g. ``["gutters", "trim"]``.
    suggested_categories: list[str] = Field(default_factory=list)
    mode: AttachRuleMode = "advisory"

    @field_validator("primary_category")
    @classmethod
    def _trim_primary(cls, value: str) -> str:
        return value.strip()

    @field_validator("suggested_categories")
    @classmethod
    def _clean_suggested(cls, values: list[str]) -> list[str]:
        return _clean_categories(values)


def _default_rules() -> list[AttachRule]:
    """Starter rules for the exterior trades, shipped **advisory**.

    Deliberately soft: the operator should watch their attach rate for a few
    weeks before switching a rule to ``blocking``. A prompt nobody can dismiss
    on day one trains reps to resent the tool, and a resented prompt gets
    clicked through without the conversation ever happening.

    Categories mirror :data:`app.models.catalog.DEFAULT_SERVICE_CATEGORIES`; a
    workspace on its own taxonomy edits these in Settings → Attach Rules.
    """
    return [
        AttachRule(primary_category="roof", suggested_categories=["gutters", "trim"]),
        AttachRule(primary_category="siding", suggested_categories=["trim", "windows"]),
        AttachRule(primary_category="gutters", suggested_categories=["roof"]),
        AttachRule(primary_category="windows", suggested_categories=["siding", "trim"]),
    ]


class AttachRulesSettings(BaseModel):
    """The full attach-rule config for a workspace (read view, lenient)."""

    model_config = ConfigDict(extra="ignore")

    # Master switch. On by default with advisory rules: an advisory prompt can
    # never fail a save, so a workspace that has not configured anything still
    # gets the reminder that moves average job value.
    enabled: bool = True
    rules: list[AttachRule] = Field(default_factory=_default_rules)
    # Operator-editable prompt copy. ``{primary}`` interpolates the quote's
    # primary service; a template that omits or misspells it still renders (see
    # ``app.services.quotes.attach_rules.render_prompt``).
    prompt_template: str = Field(default=DEFAULT_PROMPT_TEMPLATE, max_length=500)
    dismissal_reasons: list[str] = Field(default_factory=_default_dismissal_reasons)
    # When true a dismissal must carry a reason, which is what keeps "why don't
    # we attach?" answerable later. A reason-less dismissal is not reportable.
    require_dismissal_reason: bool = True

    @field_validator("dismissal_reasons")
    @classmethod
    def _clean_reasons(cls, values: list[str]) -> list[str]:
        return _clean_categories(values)


class AttachRulesSettingsUpdate(BaseModel):
    """Partial update of the attach-rule config (shallow top-level merge).

    Every block is optional; only provided keys are written, so editing the
    prompt copy never clobbers the rules. Mirrors
    :class:`app.schemas.pricing.PricingSettingsUpdate`.
    """

    enabled: bool | None = None
    rules: list[AttachRule] | None = None
    prompt_template: str | None = Field(default=None, max_length=500)
    dismissal_reasons: list[str] | None = None
    require_dismissal_reason: bool | None = None

    @field_validator("dismissal_reasons")
    @classmethod
    def _clean_reasons(cls, values: list[str] | None) -> list[str] | None:
        return None if values is None else _clean_categories(values)


class AttachWarning(BaseModel):
    """A missing attach, returned on the quote that triggered it.

    Structured rather than a rendered string so the builder can offer the exact
    next action ("Add gutters") instead of only telling the rep off. ``mode`` is
    never ``off`` here — an off rule produces no warning at all.
    """

    primary_service: str
    suggested_categories: list[str]
    mode: Literal["advisory", "blocking"]
    # ``prompt_template`` rendered for this quote's primary service.
    message: str
    # Echoed from the config so the builder's dismissal UI needs no second fetch.
    dismissal_reasons: list[str] = Field(default_factory=list)
    require_dismissal_reason: bool = True


class AttachDismissal(BaseModel):
    """A recorded "we asked and they said no", stored on the quote.

    This is the half of attach reporting that a bare attach *rate* cannot give
    you: a workspace at 20% attach looks identical whether the other 80% were
    never asked or were asked and declined, and those two problems have opposite
    fixes (coaching vs pricing). Persisted as JSONB on
    :attr:`app.models.quote.Quote.attach_dismissals`.
    """

    # The job this quote was for, i.e. the rule's ``primary_category``.
    primary_service: str
    # The suggested categories that were skipped when the rep dismissed.
    categories: list[str] = Field(default_factory=list)
    reason: str | None = None
    dismissed_at: datetime


class AttachDismissalRequest(BaseModel):
    """A rep dismissing the attach prompt for the quote being saved.

    Only the reason crosses the wire. The categories are resolved server-side
    from the rule that actually fired, so a client cannot record a dismissal for
    an attach that was never suggested (which would corrupt attach reporting the
    same way a client-set ``service_category`` would corrupt attach rate).
    """

    reason: str | None = Field(default=None, max_length=200)
