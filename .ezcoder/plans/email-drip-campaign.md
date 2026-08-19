# In-App Email Drip Campaign

## Objective

Add a workspace-scoped email drip builder for CRM contacts/leads. Operators with outreach write access can create a draft, choose a lifecycle trigger, compose 1–10 branded emails separated by relative waits, preview each message, activate the sequence after a safety review, and pause it later.

This intentionally targets CRM contacts, not Tribunal login accounts. It reuses the existing `Automation` engine, `EmailTemplate` model/API, Resend integration, suppression records, unsubscribe endpoint, and proposal branding. It does not add a second scheduler, a paid dependency, or a database migration.

## Success criteria

- `/campaigns/email/drips` lists draft and active email drips, run counts, next-step status, and failures; operators can create, edit, activate, pause, duplicate, and delete a draft.
- The builder supports a curated lifecycle trigger (`lead_created`, `quote_sent`, `job_completed`, and similar contact-backed events), trigger-specific filters, 1–10 email steps, and hour/day waits. It states that only future matching events enroll contacts; an existing audience can be enrolled by activating a tag-based/event workflow where supported rather than silently blasting every contact.
- Every email uses a safe structured document: subject, preheader, heading, paragraph, divider, and button blocks with supported variables such as `{first_name}` and `{business_name}`. No arbitrary HTML is accepted.
- A reusable template library is available from the drip hub. Selecting a template copies a validated snapshot into the sequence, so later template edits cannot alter already-reviewed campaigns.
- Preview HTML and delivered HTML use the same renderer and inherit the workspace’s client proposal business name, logo, primary/accent colors, and business address. The layout uses the client-facing dark/ivory/gold visual language while retaining email-client-safe tables and inline styles.
- Activation is impossible when the sequence has incomplete placeholder content, malformed/unsafe links, no recipient-permission attestation, no workspace postal address, no sendable email, or invalid waits.
- Marketing delivery always rechecks contact/suppression opt-out state, includes a visible unsubscribe link and physical address, sends `List-Unsubscribe` plus one-click headers, and cannot be relabeled transactional by the browser.
- Two email steps in one automation receive distinct Resend idempotency keys; retrying the same step retains the same key. Pausing stops future enrollments and cancels pending waits visibly.
- Workspace authorization and scoping hold for templates, campaigns, activation, pause, previews, and stats.

## Existing platform fit

### Reuse

- `backend/app/models/automation.py`, `backend/app/models/automation_execution.py`, and `backend/app/workers/automation_worker.py` already execute ordered actions and durable `wait` steps inside the single backend worker process.
- `backend/app/models/email_template.py`, `backend/app/schemas/email_template.py`, `backend/app/services/email_templates.py`, and `backend/app/api/v1/email_templates.py` already provide workspace-owned structured templates and escaped variable rendering.
- `backend/app/services/email_layout.py` already renders safe email HTML/text and adds unsubscribe headers; `backend/app/services/email_unsubscribe.py` plus `backend/app/api/v1/email_unsubscribe.py` provide immediate suppression.
- `backend/app/services/quotes/proposal_template.py` is the canonical source for client-facing business name, logo, colors, and postal address.
- `frontend/src/app/campaigns/email/new/page.tsx` establishes the dark/gold campaign-composer language; `frontend/src/components/proposal/client-proposal-view.tsx` is the client-facing visual source of truth.
- `frontend/src/lib/query-keys.ts`, `frontend/src/components/ui/page-state.tsx`, and existing API client factories remain the shared data/state primitives.

### Required hardening

- Current automation email idempotency omits action identity, so multiple email steps can collapse into one provider send.
- Current automation email rendering supplies only a business name, not proposal branding or postal address.
- The template APIs have no frontend client/tests and their schemas need explicit size/count limits.
- Generic automation toggling has no email-drip activation gate or recorded permission attestation.
- Current campaign rendering tolerates missing postal addresses even for marketing content; the new drip path must fail closed.

## Design read

- **Surface:** a data-dense dashboard workflow editor with a client-facing email preview.
- **Audience:** home-service owners/operators composing nurture and follow-up sequences, primarily on desktop; tablet/mobile supports review and small edits.
- **Single job:** safely define what sends, when it sends, and what the customer sees.
- **Risk:** activation can contact real people repeatedly, so draft/active state, audience trigger, delays, and compliance readiness must remain visible near the primary action.
- **Content:** long subjects, variable customer/business names, 1–10 steps, missing logos/addresses, API errors, and empty templates are normal states.

### Evidence and thesis

Local client proposals lead: dark charcoal canvas, ivory reading surface, restrained gold action color, serif display headings, and real workspace branding. Novu is an aligned reference for separating workflow sequence, message editor, variables, and preview. Activepieces is aligned for explicit draft/publish state and incomplete-step blocking. n8n’s freeform graph is the contrast: this CRM task is linear, so a graph canvas would add keyboard, mobile, and cognitive cost without product value.

The desktop composition uses one shared rail with three aligned regions: ordered sequence at left, selected message editor in the center, rendered client preview at right. Mobile changes to explicit `Sequence`, `Write`, and `Preview` tabs while preserving the selected step. Reordering uses visible up/down controls, not drag-only interaction. Save Draft is secondary; Activate is the only primary action and opens a factual review dialog. There are no gradients, glass cards, hover lifts, emoji icons, arbitrary metric tiles, or `transition: all`.

## Backend design

### Email document and brand

- Tighten `EmailTemplateBlock` and create/update schemas with bounded strings, safe `http`/`https` links, a maximum block count, and a supported variable list including `business_name`.
- Add a workspace email-brand resolver that calls `ProposalTemplateService.get_template_settings()` and returns business name, logo, brand/accent colors, and business address plus readiness warnings.
- Extend `Brand`/`render_email()` so marketing sends require both `unsubscribe_url` and `postal_address`; preview mode may render an explicit address placeholder but returns warnings and can never activate from that state.
- Keep text and attributes escaped, compute readable CTA text against the configured accent, include `lang`, logo alt text, presentation-table semantics, and a plain-text equivalent.
- Update the public unsubscribe result page to the same restrained client-facing brand without emoji/glyph decoration, while keeping it cache-safe and token-minimal.

### Drip contract on the automation engine

Store drip campaigns in existing `Automation` rows using `trigger_config.builder = "email_drip"`. Each email action contains `category = "marketing"` and an immutable validated `template_snapshot`; reusable `template_id` is provenance only. Wait actions retain stable UUID step IDs and bounded hour/day values.

Add a small `backend/app/services/automations/email_drip.py` boundary with:

- `is_email_drip()` and serialization/validation helpers;
- activation readiness checks for trigger, step IDs, sequence size, delays, placeholders, links, business address, and permission basis;
- a fixed set of plain-language permission bases (`recent_inquiry`, `explicit_subscription`, `existing_customer_related`) stored with server-generated actor/timestamp evidence;
- pause behavior that deactivates the automation and marks scheduled executions `cancelled` immediately;
- workspace-scoped run statistics derived from `AutomationExecution` (`completed`, `scheduled`, `failed`, `cancelled`) without pretending they are provider opens or clicks.

Add explicit activate/pause/stats endpoints under the existing workspace automation router. Generic create/update always stores email drips inactive; generic toggle delegates to the same activation/pause gate so another UI cannot bypass it. Active drip content is read-only until paused.

### Delivery correctness

- Pass stable action identity into `_action_send_email()` and derive idempotency from automation, execution/event, contact, and action ID.
- Render each inline snapshot through the shared email document renderer and workspace brand resolver.
- Recheck `is_contact_opted_out()` immediately before every send; skip and log suppressed/missing-email contacts without retrying them.
- Keep `List-Unsubscribe`, `List-Unsubscribe-Post`, workspace/automation tags, and provider idempotency options in the Resend call. Resend Python 2.36.0 supports custom headers and `idempotency_key`; implementation will use the installed SDK contract.
- Preserve the current wait/resume engine, but make pause/cancel outcomes explicit in execution records and logs.

## Frontend design

### Routes and components

Add thin routes:

- `frontend/src/app/campaigns/email/drips/page.tsx`
- `frontend/src/app/campaigns/email/drips/new/page.tsx`
- `frontend/src/app/campaigns/email/drips/[id]/page.tsx`

Build focused components under `frontend/src/components/campaigns/email-drip/`:

- `email-drips-page.tsx`: list, stats, loading/error/empty states, status filters, and `Drips`/`Templates` tabs;
- `email-drip-builder.tsx`: campaign details, trigger and permission basis, sequence, editor, preview, draft save, activation, pause, and recovery states;
- `email-sequence-editor.tsx`: semantic ordered list, delay labels, add/remove, keyboard-operable up/down controls, and selected-step continuity;
- `email-template-editor.tsx`: subject/preheader/heading, structured blocks, token insertion, safe button URL controls, and validation;
- `email-template-preview.tsx`: sandboxed server-rendered `srcDoc`, desktop/mobile width switch, loading/error warnings, and no script permission;
- `email-template-library.tsx`: create/edit/duplicate/deactivate/delete reusable presets using the existing backend resource;
- `email-drip-utils.ts`: typed action serialization/deserialization, duration summaries, draft defaults, and malformed legacy recovery.

Add `frontend/src/lib/api/email-templates.ts`, extend `frontend/src/lib/api/automations.ts` for activate/pause/stats, add query keys, and keep generated OpenAPI types as the contract. Add Email Drip links to the campaigns create menu/list and a contextual link from the existing one-time email composer.

### States and accessibility

- Use real headings, labels, descriptions, fieldsets, ordered lists, buttons, and status announcements; keyboard focus moves to the first invalid field after a failed activation.
- Destructive pause/delete actions use a confirmation dialog and state exactly what pending recipients lose.
- Preview is never the only representation of content; every editable value remains available in labelled controls.
- Provide pending, saved, failed, offline/retry, empty sequence, missing brand/address, invalid URL, active read-only, paused, and success states.
- Maintain visible `focus-visible`, measured AA contrast, 200% zoom/reflow, long-text wrapping, no horizontal page overflow at 320px, reduced-motion behavior, and no pointer-sticky focus treatment.

## Compliance controls

This is engineering guidance, not legal advice and does not certify the product. The implementation will update `COMPLIANCE.md` with a dated email-drip section and stable findings/statuses.

Implemented controls will include recipient-permission attestation, sender identification, a real postal address, visible unsubscribe, one-click headers, immediate suppression, workspace authorization, bounded frequency/sequence length, and tests proving every drip send path goes through those gates. The activation dialog will say that the operator is responsible for choosing an audience they are allowed to email.

Residual legal risk remains: campaign-level attestation cannot prove each imported contact’s consent or determine every recipient’s jurisdiction. `COMPLIANCE.md` will keep that as an open `LAWYER`/product-policy item rather than claiming compliance. The first release will not add tracking pixels, open tracking, click tracking, purchased-list import, or silent enrollment of Tribunal login users.

## Verification

- **Backend tests:** schema limits/escaping, workspace isolation, branded preview, marketing-address/unsubscribe hard gates, activation attestation, pause cancellation, stats, suppression, two-step idempotency, same-step retry dedupe, and Resend headers/tags.
- **Frontend tests:** serialization round trips, malformed action recovery, template block editing, sequence reorder, responsive mode preservation, save/activate/pause payloads, readiness errors, API failures, and accessible names/focus.
- **Boundary runtime:** use `.ezcoder/eyes/http.sh` on template preview and drip activate/pause/stats endpoints, including unauthorized/cross-workspace and missing-address failures.
- **Email runtime:** clear the local mail sink, trigger a representative lead event through the local backend, inspect worker logs, then verify one branded message with correct recipient, subject, body variables, business identity, postal address, and unsubscribe URL via `.ezcoder/eyes/mail.sh`.
- **Rendered UI:** capture desktop and 390px mobile screenshots of list, builder, activation review, and branded preview; run one evidence-led critique/revision cycle and record the score/checks in `frontend/DESIGN.md`.
- **Contracts/checks:** regenerate `backend/openapi.json` and `frontend/src/lib/api/_generated.ts`; run focused backend/frontend tests, `make ci.backend`, `make ci.frontend`, relevant Playwright E2E, and `git diff --check`. No migration check is needed unless implementation discovers an unavoidable schema change.

## Risks and non-goals

- Generic automation rows are intentionally reused; no duplicate scheduler or campaign table is introduced.
- This release reports sequence run state, not email opens/clicks. Current Resend event storage is not correlated strongly enough to claim recipient engagement.
- Active campaigns are paused before editing; pausing cancels waiting runs so customers never receive an unreviewed hybrid sequence.
- Templates are snapshots inside campaigns; template-library edits affect only future copies.
- Bulk enrollment of an arbitrary existing list and Tribunal-account-user lifecycle emails are out of scope. A future manual-enrollment endpoint can be added after frequency, consent provenance, and operational limits are designed.

## Steps

1. Add bounded email-template schemas, workspace proposal-brand resolution, marketing readiness data, safe block rendering, and branded HTML/plain-text output in the backend email template/layout services.
2. Harden the email-template API for workspace-branded draft/saved previews and CRUD, then add backend tests for isolation, validation, escaping, unsafe links, variables, and readiness warnings.
3. Add `backend/app/services/automations/email_drip.py` with drip identification, action parsing, activation validation, server-stamped permission evidence, pause cancellation, and execution statistics.
4. Extend automation create/update/toggle behavior and add explicit activate, pause, and stats endpoints that enforce `CanWriteOutreach`, workspace scoping, inactive-draft editing, and fail-closed marketing readiness.
5. Update `AutomationWorker` and email sending helpers to render immutable template snapshots with workspace branding, enforce suppression immediately before send, and include action identity in Resend idempotency plus unsubscribe headers/tags.
6. Add worker/API tests proving distinct multi-step sends, same-step retry dedupe, waits/resume, pause cancellation, suppression, missing-address blocking, attestation enforcement, and honest run stats.
7. Regenerate `backend/openapi.json` and `frontend/src/lib/api/_generated.ts`, then add the email-template client, drip activation/pause/stats methods, query keys, and typed serialization utilities.
8. Build the email drip/template hub, list states, reusable template library, campaign navigation links, and thin `/campaigns/email/drips` routes using existing page-state and permission patterns.
9. Build the responsive sequence editor, structured message editor, sandboxed branded preview, draft persistence, activation review, pause/delete recovery, and desktop/mobile interaction states.
10. Add frontend unit/component tests and Playwright coverage for create/edit/preview/activate/pause, validation and API failures, keyboard operation, 320px reflow, long content, and workspace data preservation.
11. Update `frontend/DESIGN.md` with the design read, local/external evidence, responsive behavior, accessibility checks, and critique score; update `COMPLIANCE.md` with implemented email controls, evidence labels, residual recipient-consent risk, and non-legal-advice status.
12. Exercise the new API with `.ezcoder/eyes/http.sh`, trigger a local drip and inspect it with `.ezcoder/eyes/logs.sh` plus `.ezcoder/eyes/mail.sh`, capture desktop/mobile screenshots, revise any failed evidence, and run backend/frontend/codegen checks before reporting completion.