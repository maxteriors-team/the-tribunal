# Sell Christmas lighting in packages (Good/Better/Best for seasonal decor)

## Goal
Offer seasonal Christmas lighting as **packages** (service tiers), the same way
landscape lighting sells Good/Better/Best. Each package includes a different set
of seasonal decor categories + roofline:

| Package | Roofline | Trees | Bushes | Wreaths | Garland |
|---|:---:|:---:|:---:|:---:|:---:|
| **Essential** | — | ✅ | ✅ | — | — |
| **Middle** | ✅ | ✅ | ✅ | — | — |
| **Premier** | ✅ | ✅ | ✅ | ✅ | ✅ |

"Minimal bushes and trees" (Essential) → "roofline + trees + bushes" (Middle) →
"wreaths, garland, trees, bushes, and roofline" (Premier).

## The structure decision

**Packages are coverage presets over the existing seasonal decor engine** — NOT
a new pricing path, NOT flat-price bundles.

- Today `ChristmasConfig` is à la carte: `items: list[SeasonalItem]`
  (trees/bushes/wreaths = `each`, garland/mini = `per_ft`) + `roofline_per_ft` +
  takedown/storage, priced by `price_christmas(...) -> ChristmasPricing`.
- Landscape tiers (`TierConfig` + `tier_order`) are named groups of included
  items + presentation copy; **one fixture entry prices all three tiers** and
  they render as Good/Better/Best cards.

Apply that exact pattern to Christmas: a **`ChristmasPackage`** names the
seasonal category keys it includes + whether roofline is included + the same copy
fields as `TierConfig` (label/name/marker/experience/points/value_tag/popular).
**One measurement** (roofline feet + decor quantities) prices **every package**
by running the existing engine restricted to that package's included categories.

### Why this is best
- **Zero math duplication** — reuses `_price_seasonal_item` + gross-up + takedown
  + job-minimum; each package is a standalone priceable subset.
- **Monotonic G/B/B** — each higher package is a superset of categories, so
  totals naturally increase; matches the "service tier" framing.
- **Config-only per workspace** ("fork the data, not the code") — a workspace
  defines `christmas.packages`; changing what a package covers is a Settings edit.
- **One entry → three cards** — same UX as landscape `renderPackages`; the
  wizard/estimator reuse the card presentation.
- **Backward compatible** — `packages_enabled` defaults **false**, so the current
  à la carte christmas flow is unchanged until a workspace opts in.

### Include model (v1)
Gate/scope only: a package lists allowed category keys + `includes_roofline`. The
shared decor selection drives all packages (e.g. "3 trees" prices under every
package that includes trees; Premier adds wreaths + garland + roofline on top).
This is the faithful analog of `TierConfig.sections[].item_ids` (id lists, no
per-tier quantities). **Per-package default quantities are an explicit follow-up,
not v1.**

Roofline is not a `SeasonalItem` (it is `roofline_per_ft`, priced specially), so
`ChristmasPackage` carries an explicit `includes_roofline: bool`; Essential =
false → the engine is called with `roofline_feet=0` for that package.

## Schema shape (`backend/app/schemas/pricing.py`)
```python
class ChristmasPackage(BaseModel):
    key: str                      # "essential" | "middle" | "premier"
    label: str
    name: str | None = None
    marker: str | None = None
    card_tier: str | None = None
    experience: str | None = None
    warranty: str | None = None
    points: list[str] = []
    value_tag: str | None = None
    popular: bool = False
    includes_roofline: bool = False
    item_keys: list[str] = []     # SeasonalItem keys this package covers

# on ChristmasConfig:
    packages_enabled: bool = False
    package_order: list[str] = Field(default_factory=list)
    packages: list[ChristmasPackage] = Field(default_factory=_default_christmas_packages)

# computed result:
class ChristmasPackagePricing(BaseModel):
    key: str; label: str; name: str | None; marker: str | None
    experience: str | None; points: list[str]; value_tag: str | None
    popular: bool; includes_roofline: bool
    pricing: ChristmasPricing      # reuse the existing computed breakdown
```

## Surfaces (verified real files)
**Backend**
1. `schemas/pricing.py` — `ChristmasPackage`, `ChristmasConfig.{packages_enabled,
   package_order,packages}` + `_default_christmas_packages()`,
   `ChristmasPackagePricing`. (`PricingSettingsUpdate.christmas` already replaces
   the whole block, so no extra field there.)
2. `services/quotes/proposal_pricing.py` — `price_christmas_package(config,
   package, *, roofline_feet, items, takedown, storage)` (filters `items` to
   `package.item_keys`, forces `roofline_feet=0` when not `includes_roofline`,
   delegates to `price_christmas`) + `price_christmas_packages(...)` returning the
   list in `package_order`.
3. `scripts/demo/seed_lighting_workspace.py` — add the three default packages to
   the `christmas` block (`packages_enabled: True`).
4. `schemas/proposal_wizard.py` — `WizardChristmasSelection.selected_package:
   str | None`.
5. `services/quotes/proposal_builder.py` — when `christmas` active and
   `packages_enabled`, price the selected package (default = most inclusive with
   total > 0) and render its section; à la carte path unchanged when disabled.
6. `schemas/estimate.py` — `LinearFeetEstimateResult.christmas_packages:
   list[ChristmasPackagePricing]`; public payload stays totals-only (no per-ft,
   no feet). SECONDARY surface.
7. `services/quotes/quote_service.py` — `_compute_comparison`/estimate compute
   packages; persist/read the selected package. SECONDARY.
8. `models/roofline_comparison.py` + additive nullable `christmas_package` column
   + migration (mirrors the `christmas_items` precedent). SECONDARY.

**Frontend**
9. Regenerate client (`make codegen`) → commit `backend/openapi.json` +
   `frontend/src/lib/api/_generated.ts` together.
10. `sales-wizard/use-sales-wizard.ts` + `sales-wizard/builder-sections.tsx` —
    render Christmas **package cards** when `packages_enabled`; `selected_package`
    state; the shared decor controls feed all cards. PRIMARY selling surface.
11. `components/settings/seasonal-pricing-settings-tab.tsx` — package editor
    (order, per-package included categories + roofline toggle + copy). Save keeps
    spreading `...serverChristmas`, so packages round-trip.
12. `estimator/roofline-estimator.tsx` + `estimator/estimate-panel.tsx` +
    `estimator/comparison-card.tsx` + `app/p/compare/[token]/page.tsx` — seasonal
    package cards (public = totals only). SECONDARY.

## Risks & mitigations
- **Public leak** — packages must never expose per-ft/feet on the public compare
  payload; keep the totals-only discipline; extend the no-leak test.
- **Takedown / job-minimum per package** — each package prices as a standalone
  subset, so `minimum` and `takedown_rate` apply to that package's subtotal
  (correct); add tests asserting Essential < Middle < Premier and minimum applies.
- **Backward compat** — `packages_enabled=False` default keeps à la carte flow;
  a stored `christmas` blob with no `packages` gets the defaults but stays
  disabled. Add a test that an old blob prices identically.
- **Contract drift** — `make codegen`; commit both artifacts in one commit.

## Verification
- `make ci.all` green (ruff/mypy/pytest, frontend lint/type/test/build,
  migration up→check→down→up).
- Live probes: seed a workspace, `http.sh` the estimate/pricing endpoints, and
  confirm three seasonal package totals with Essential < Middle < Premier; assert
  the public compare payload carries no per-ft/feet for a package selection.
- Screenshot the wizard Christmas package cards + the settings package editor.
