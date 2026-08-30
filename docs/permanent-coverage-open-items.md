# Permanent lighting coverage — open items

Two deliberate gaps left after the coverage ladder shipped (2026-08-29). Both are
small, both are judgment calls, neither is a bug in what is live.

## 1. An untagged run prices as Front, so a forgotten tag undercharges

Each drawn permanent run carries an `elevation` tag (`front` / `side` / `back`)
that decides which coverage levels include it. When the tag is **absent**, the
run counts as **front**, which puts it in all three levels.

That was chosen for backward compatibility: every drawing saved before elevation
tagging existed has no tag, and front is the one face every coverage level
includes, so those drawings keep pricing exactly as they did.

The cost of that choice: a rep who draws a back run and forgets to tag it sells
it inside **Front only**, the cheapest package. The mistake **undercharges**.

The alternative is to default to `back`, which appears only in Whole home, so the
same mistake **overcharges** instead — recoverable in a conversation, unlike
money already quoted.

Where it lives:

- `frontend/src/lib/estimator/design.ts` — `shotsForCoverage()` and
  `permanentRunFeet()` both read `run.elevation ?? "front"`.
- `backend/app/schemas/lighting_project.py` — `RunSchema.elevation`, nullable.
- Tests pinning today's behaviour: `frontend/src/lib/estimator/design.test.ts`
  ("counts an untagged run as front so older drawings price unchanged", "keeps an
  untagged run at every level").

Flipping the default is a two-line change plus those tests. The real decision is
whether existing saved drawings should be backfilled to `front` first, so only
*new* untagged runs get the safer default — otherwise old drawings silently
reprice.

## 2. The seasonal side never got the footage-leak sweep

The permanent side had measured footage removed from everything the customer
reads: quote line names/descriptions and the patio/bistro section. A guard test
now asserts the **public proposal payload** carries no `\d\s*(ft|feet|linear)`
text (`backend/tests/services/quotes/test_quote_service.py`).

The seasonal (Christmas) path was **not** audited the same way. Per-ft decor
deliberately keeps its footage — "20 ft Garland" describes material the customer
receives, not a measurement of their house — but nobody has checked the seasonal
package cards, comparison page, or line descriptions for a measurement that leaks
the number our price is derived from.

Starting points:

- `backend/app/services/quotes/proposal_pricing.py` — seasonal display lines.
- `backend/app/schemas/estimate.py` — `christmas_packages`,
  `PublicComparisonPackage`.
- `frontend/src/components/proposal/client-proposal-view.tsx` — what the
  homeowner renders.

The cheapest first move is to extend the existing public-payload guard to a
seasonal fixture and see what fails.
