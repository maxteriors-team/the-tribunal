# Referral Partner Intake Project

**Owner:** Max / Maxteriors
**System:** The Tribunal CRM
**Status:** Implemented
**Last updated:** September 2, 2026

## Objective

Give each approved Maxteriors referral partner a secure, standardized intake link. The partner completes a public form, and the information automatically updates the correct existing referral-partner record in The Tribunal without creating a duplicate.

## Recommended workflow

1. Add or open the partner under **Referral Partners**.
2. Move the relationship to the verbal-yes/onboarding point.
3. Open the partner detail page and generate an intake link.
4. Copy the link and send it to the partner by email or text.
5. The partner reviews prefilled information and submits the completed form.
6. The same Tribunal partner record is updated and marked submitted.
7. Maxteriors reviews the profile, offer, website, and logo before using them on a client-benefit page.

Suggested lifecycle:

```text
Interested
→ Verbal Yes
→ Intake Form Sent
→ Intake Received
→ Page Under Review
→ Client Link Issued
→ Active
```

The current implementation handles intake-link generation, intake status, form submission, and CRM display. Automatic pipeline-stage sending is a future enhancement.

## Information collected

- Contact name
- Company name
- Email address
- Phone number
- Website URL
- Business description
- Services offered
- Service area
- Client-offer headline
- Offer description
- Offer type
- Offer value
- Offer terms, limitations, and expiration information
- Company logo

## Tribunal behavior

### Authenticated CRM experience

On the referral-partner detail page, users with CRM write permission can:

- Generate or retrieve the partner's intake link
- Copy the link
- Rotate the link
- Revoke the link
- See intake status and submission date
- View the submitted company profile
- Open the partner's website
- Review the offer and terms
- View the submitted logo

### Public partner experience

The public route is:

```text
/p/referral-partners/intake#token=<secure-capability>
```

The form does not require a Tribunal account. It prefills existing partner information, validates the standardized fields, submits the profile, and uploads the logo.

### Record behavior

- Submission updates the existing `ReferralPartner` record.
- It does not create a duplicate contact or partner.
- Repeat submissions update the same record.
- Intake status and timestamps are persisted.
- Offer and profile information are visible in Tribunal after submission.

## Security design

- Intake links are high-entropy, workspace-scoped capabilities.
- Tokens are encrypted at rest and looked up by SHA-256 digest.
- Tokens expire after 30 days and can be rotated or revoked.
- The raw token is kept out of HTTP URLs and normal access logs by placing it in the browser fragment and sending it to fixed API routes through an Authorization bearer header.
- The browser removes the fragment immediately and retains it only in session storage for refresh support.
- Sentry scrubs literal and encoded intake-token fragments.
- Public writes are rate-limited.
- Public PII and generated-link responses use `Cache-Control: no-store`.
- Public payloads cannot supply workspace, partner, contact, or active-status identifiers.
- Website values permit only HTTP/HTTPS URLs.
- Logos are limited to PNG, JPEG, or WebP, with a 2 MiB maximum and actual byte-signature validation.
- Logos are stored separately so scoreboard queries do not load image blobs.
- A post-fix defensive security audit reported no remaining blocker.

## Main implementation files

### Backend

- `backend/app/models/referral_partner.py`
- `backend/app/models/referral_partner_intake.py`
- `backend/app/models/referral_partner_logo.py`
- `backend/app/schemas/referral_partner.py`
- `backend/app/services/lead_sources/referral_partner_intake_service.py`
- `backend/app/services/lead_sources/referral_partner_service.py`
- `backend/app/api/v1/referral_partners.py`
- `backend/app/api/v1/router.py`
- `backend/app/main.py`
- `backend/alembic/versions/20260902_referral_partner_intake.py`

### Frontend

- `frontend/src/app/p/referral-partners/intake/page.tsx`
- `frontend/src/app/p/referral-partners/intake/layout.tsx`
- `frontend/src/components/referral-partners/public-referral-partner-intake.tsx`
- `frontend/src/components/referral-partners/referral-partner-intake-panel.tsx`
- `frontend/src/components/referral-partners/referral-partner-detail.tsx`
- `frontend/src/lib/api/referral-partners.ts`
- `frontend/sentry.client.config.ts`

### Tests

- `backend/tests/services/lead_sources/test_referral_partner_intake.py`
- `frontend/src/app/p/referral-partners/intake/page.test.tsx`
- `frontend/src/components/referral-partners/public-referral-partner-intake.test.tsx`
- `frontend/src/components/referral-partners/referral-partner-intake-panel.test.tsx`

## Verification completed

- 58 focused backend tests passed
- 21 focused frontend tests passed
- Backend Ruff checks passed
- Backend mypy checks passed
- Frontend ESLint checks passed
- Full frontend TypeScript check passed
- Alembic migration SQL generation passed
- OpenAPI export and frontend client generation passed
- Local public form route returned HTTP 200
- Post-fix security audit confirmed both identified issues fixed

Verifier evidence is stored outside the repository at:

```text
~/.ezcoder/goals/projects/b2c3b13d5bbd3084/artifacts/referral-partner-intake-verifier.log
```

## Before production use

1. Review the working-tree diff and separate it from unrelated estimator/proposal work already present on the branch.
2. Commit the referral-partner intake files.
3. Apply the Alembic migration in the deployment process.
4. Deploy the backend and frontend together.
5. Confirm the public frontend base URL generates the correct partner link.
6. Create one test partner and submit a real PNG/JPEG/WebP logo.
7. Confirm the same partner record shows the submitted profile, offer, logo, and status.
8. Confirm rotate and revoke invalidate old links.
9. Select the final Maxteriors client offer and legal terms before publishing client-benefit pages.

## Future enhancements

- Automatically send the intake link when a partner enters **Verbal Yes** or **Onboarding**.
- Add a general public partner-program explainer page.
- Generate the separate co-branded client-benefit/referral page after intake approval.
- Add downloadable QR codes and copy-ready SMS/email language.
- Add inactive/dormant partner reminders.
- Add approval status before a submitted offer can be used publicly.

## Resume prompt

Use this prompt when returning to the project:

> Continue the Referral Partner Intake Project documented in `docs/referral-partner-intake-project.md`. Review the current uncommitted referral-partner intake changes, separate them from unrelated working-tree changes, rerun the recorded verifier, and help me prepare the migration/deployment or build the automatic onboarding-stage send and co-branded client-benefit page.
