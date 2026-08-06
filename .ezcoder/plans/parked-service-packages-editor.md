# Parked: the service-packages / inclusions editor on `assistant`

**Status:** parked, not lost. Decided 2026-08-04.

## Where it lives

Branch `assistant`, tip `c9c4fb31`, pushed to GitHub (`origin/assistant`). Also
checked out locally at `../the-tribunal-assistant-preserved`. Nothing is dirty or
unpushed — deleting that worktree loses nothing, the branch is the source of truth.

## What is actually unshipped

`assistant` has 9 commits not on `main`. Verified by content, not SHA (rebase-merge
rewrites SHAs, so `git cherry` and ancestry checks lie here):

- all 9 commit subjects appear in main's history
- 137 of 147 touched files exist in main
- 6 of the 10 "missing" files were **renamed**, not dropped
  (`unsold_quotes` → `quote_revival`, e.g. `backend/app/schemas/unsold_quotes.py`
  → `backend/app/schemas/quote_revival.py`)
- `slugify` / `uniqueKey` from `editor-keys.ts` were absorbed into main's
  `frontend/src/components/settings/seasonal-pricing-settings-tab.tsx`

**Genuinely stranded — exists only on `assistant`:**

| File | Lines |
|---|---|
| `frontend/src/components/settings/service-packages-editor.tsx` | 813 |
| `frontend/src/components/settings/package-copy-fields.tsx` | 92 |

Distinctive symbols absent from main: `ServiceBasis`, `EditInclusion`, `EditTier`,
`EditServiceCategory`, `PackageCopyFields`.

## Why it is not a trivial cherry-pick

Main **reimplemented the same settings tab inline** rather than importing the
editor. Both versions of `seasonal-pricing-settings-tab.tsx` are live-ish:

- main: 1192 lines, packages handled inline
- assistant: 929 lines, delegates to `service-packages-editor.tsx`

They conflict directly. Shipping the editor means choosing which implementation
wins — a product/taste call, not a mechanical rebase. `assistant` is also **67
commits behind main**.

## The capability gap this leaves open

Backend `backend/app/schemas/pricing.py` on main fully models a shared inclusion
catalog:

- `inclusions: list[ServiceInclusion]` (~line 730) — "Shared scope catalog every
  tier draws its `inclusion_keys` from"
- `inclusion_keys: list[str]` on tiers (~lines 655, 1044)

**No shipped UI edits any of it.** Main's settings tab can only toggle the
`includes_roofline` boolean. So the data model supports per-tier scope catalogs
that an operator currently has no way to configure.

## To pick this up later

1. Decide which `seasonal-pricing-settings-tab.tsx` is the base (main's is newer
   and larger; assistant's is the one wired to the editor).
2. Branch off current `main`, port `service-packages-editor.tsx` +
   `package-copy-fields.tsx`, wire to `inclusions` / `inclusion_keys`.
3. Do **not** rebase `assistant` itself — 67 commits behind, and its other 8
   commits already shipped under rewritten SHAs.
