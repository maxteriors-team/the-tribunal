# Landscape Lighting Send to Quote Builder

## Objective

Fix the landscape-lighting project header’s **Send proposal** action so it always opens the existing landscape Quote Builder at the package choices, carries the live project context into pricing, and never attempts delivery before the operator reviews a package.

Work stays isolated in `/Users/maxsherrod/the-tribunal/.ezcoder/worktrees/landscape-quote-builder` on `fix/landscape-quote-builder`. No production deploy, backend change, migration, or generic `/sales-wizard` handoff is needed.

## Success criteria

- Clicking **Send proposal** switches the controlled landscape workflow to `proposal` and visibly positions/focuses the Quote Builder, including when the operator is already on that tab but has scrolled elsewhere.
- The first visible decision is the configured package selector (`Foundation`/`Premier`/`Signature`, `Good`/`Better`/`Best`, or the workspace’s current tier labels).
- The Quote Builder continues using the live drawing, fixture counts, wire runs, selected tier, care plan, manual proposal lines, preview images, project name/ID, contact ID, opportunity ID, and service-location ID.
- Creating a quote still calls the existing `salesWizardApi.save` path only after review; email/SMS delivery still requires a created draft quote and an explicit delivery action.
- Pricing loading, error, and empty-design states remain recoverable instead of looking like a silent no-op.
- Focus and viewport behavior work at desktop and mobile widths without remounting or losing unsaved design state.

## Existing flow to preserve

- `frontend/src/components/landscape-lighting/lighting-project-editor.tsx` owns `workflowTab` and passes it to `LightDesigner` through `landscapeProject.activeWorkflowTab` / `onActiveWorkflowTabChange`.
- The same adapter already carries `projectId`, `projectName`, `contactId`, `contactName`, `opportunityId`, `serviceLocationId`, `installationShotId`, `flushBeforeProposal`, and the autosaved draft.
- `frontend/src/components/estimator/light-designer.tsx` already renders `LandscapeProposalPanel`, package-tier controls, care-plan controls, additional lines, preview imagery, quote creation, and explicit delivery.
- `buildLandscapeProposalPayload()` already derives quantities from the current design and links the saved quote to the contact, opportunity, service location, and lighting project.
- The general `calculator-screen.tsx` Quote Builder is not the target: routing there would require a second hydration format and would drop landscape-specific proposal state that is already available in place.

## Implementation

### Send behavior

In `ActiveProjectEditor`, use one named `openQuoteBuilder` handler that:

1. sets the controlled workflow tab to `proposal` immediately;
2. waits one animation frame for the panel to render;
3. focuses and scrolls the stable `#landscape-quote-builder` target into view.

The button remains `type="button"`, retains the **Send proposal** label, and declares `aria-controls="landscape-quote-builder"`. This makes repeated clicks useful while avoiding a form submit, route change, forced remount, or pre-review delivery.

### Quote Builder surface

Give the existing proposal panel the stable focus target and an explicit **Landscape Lighting Quote Builder** heading. Keep `tabIndex={-1}` for programmatic focus, the existing semantic `Fixture package` fieldset, configured tier buttons, pricing retry alert, and empty-design guidance.

Do not duplicate quote logic. Continue using `landscapeProposalPayload`, `landscapeProposalQuery`, `landscapeQuoteMutation`, `landscapeDeliveryMutation`, and the current controlled tier/care/proposal state.

### Context proof

Strengthen focused tests so the handoff proves more than a tab change:

- current design quantities reach the preview payload;
- `contact_id`, `lighting_project_id`, project title, and selected package reach preview;
- `opportunity_id` and `service_location_id` reach quote creation;
- the package fieldset is in the viewport after the first click and after a repeated click from a scrolled/zoomed proposal document;
- Good/Better/Best package pricing and care-plan/additional-line behavior remain covered by the existing `LightDesigner` component test.

## Files

- `frontend/src/components/landscape-lighting/lighting-project-editor.tsx`
  - add/refine the explicit Send-to-Quote-Builder handler and button relationship.
- `frontend/src/components/estimator/light-designer.tsx`
  - mark and name the existing landscape Quote Builder surface without changing pricing or delivery architecture.
- `frontend/src/components/estimator/light-designer.test.tsx`
  - assert project/contact/opportunity/service-location linkage and design quantities in the quote payload.
- `frontend/e2e/landscape-lighting-studio.spec.ts`
  - add the focused Send flow, preview-payload capture, repeated-click viewport regression, and screenshot evidence.
- `frontend/src/components/landscape-lighting/lighting-project-editor.test.tsx`
  - add a small controlled-tab assertion only if the Playwright test does not fully cover the parent-to-designer handoff.

## Verification

Run bounded checks from the isolated worktree:

```bash
cd /Users/maxsherrod/the-tribunal/.ezcoder/worktrees/landscape-quote-builder/frontend
npm test -- --run src/components/landscape-lighting/lighting-project-editor.test.tsx src/components/estimator/light-designer.test.tsx
npx eslint src/components/landscape-lighting/lighting-project-editor.tsx src/components/estimator/light-designer.tsx src/components/estimator/light-designer.test.tsx e2e/landscape-lighting-studio.spec.ts
npm run typecheck
npm run e2e -- e2e/landscape-lighting-studio.spec.ts
npx prettier --check src/components/landscape-lighting/lighting-project-editor.tsx src/components/estimator/light-designer.tsx src/components/estimator/light-designer.test.tsx e2e/landscape-lighting-studio.spec.ts
```

Use the route-mocked Playwright landscape project to capture the opened Quote Builder at a desktop viewport and at 390px mobile width. Inspect both captures for the heading, package choices, current project context, viewport position, clipping, and horizontal overflow. Restore Next-generated `next-env.d.ts` drift after dev/E2E runs and finish with `git diff --check` plus a four-file diff audit.

## Risks and boundaries

- Package labels and availability come from workspace pricing; tests use representative configured tiers without hard-coding production names.
- A project with no drawable fixtures may show the existing empty guidance instead of priced packages; this is an honest state, not a silent send.
- No quote is created and nothing is emailed/texted merely by clicking the header action.
- No primary-worktree changes, production configuration, backend API, OpenAPI artifact, database data, commit, PR, or deployment are part of this fix.

## Steps

1. Refine `lighting-project-editor.tsx` so **Send proposal** switches to `proposal`, then focuses and scrolls the stable Quote Builder target without routing, remounting, or delivering.
2. Mark the existing `LandscapeProposalPanel` as the named Quote Builder surface while preserving its package, care-plan, proposal-preview, quote-create, and delivery paths.
3. Add focused component assertions that current design quantities plus project, contact, opportunity, service-location, selected-tier, care-plan, and additional-line context remain in the preview/save payloads.
4. Add a Playwright regression that clicks **Send proposal**, verifies the Quote Builder/package choices and captured preview payload, scrolls away, clicks again, and verifies the package selector returns to the viewport.
5. Run the bounded unit tests, focused ESLint, TypeScript, full landscape Playwright spec, Prettier check, and `git diff --check`; fix any failures and restore generated `next-env.d.ts` drift.
6. Capture and inspect desktop and 390px mobile screenshots of the route-mocked Send-to-Quote-Builder flow, revise any clipping/focus/overflow defect, and complete a final four-file diff audit without deploying.