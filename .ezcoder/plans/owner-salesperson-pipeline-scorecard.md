# Verify and establish Max as the sole workspace owner

## Outcome

Verify the production workspace membership for `max@maxteriors.com`. If it is not already `owner`, promote it through a narrow, dry-run-first operational script that atomically demotes the previous owner to `admin` and promotes Max, leaving exactly one committed owner membership.

This change is limited to workspace ownership and authorization proof:

- `owner` remains rank `100`, above `admin` rank `80`.
- The target owner has every capability in `backend/app/core/permissions.py`.
- No email-specific authorization bypass is added; the email is only an operator lookup input.
- No scorecard, pipeline, capability, frontend, or unrelated API behavior changes.
- No schema migration or dependency is added.

## Existing controls and gap

- `backend/app/core/roles.py` already makes `owner` the highest rank and excludes it from `AssignableRole`, so invitation and ordinary role-update payloads cannot grant ownership.
- `backend/app/core/permissions.py` already maps owner to the all-capability admin tier.
- `backend/app/api/v1/workspaces.py` already refuses to demote or remove an existing owner membership.
- Workspace creation establishes one owner, but `workspace_memberships` has no database uniqueness constraint on `role = 'owner'` and there is no ownership-transfer endpoint.
- Therefore a direct one-row promotion would be unsafe: it could leave two owners. The operational path must lock, compare, transfer, and verify the complete workspace membership set in one transaction.
- Railway CLI access to the production project is available. The live database role has not been queried during planning; implementation starts with a read-only dry run and never prints database credentials or the raw target email.

## Narrow ownership mechanism

Add `backend/app/services/workspaces/ownership.py` with one transaction-safe ownership operation used only by the operational script:

1. Resolve an active target user and their existing membership in the selected workspace. Missing, inactive, or cross-workspace targets fail closed without creating accounts or memberships.
2. Lock every membership row for that workspace with `SELECT ... FOR UPDATE` before evaluating roles.
3. Require zero or one current owner. More than one owner is an existing integrity incident, so the operation aborts rather than guessing which accounts to demote.
4. If Max is already the sole owner, return an idempotent no-op result.
5. If another sole owner exists, require its exact user ID through `--expected-current-owner-id`; a stale/mistyped expectation aborts before any mutation.
6. In one database transaction, demote that previous owner to `admin`, promote the target membership to `owner`, flush, and assert the workspace has exactly one owner and that it is the target before commit.
7. If no owner exists, permit repair only with the explicit sentinel `--expected-current-owner-id none`, then promote the target and assert the same postcondition.

Add `scripts/ops/set_workspace_owner.py` as the auditable operator entry point:

- Accept `--email` and an optional `--workspace-id` for discovery; require the exact workspace ID for `--apply`.
- Look up the encrypted email through `User.email_hash == hash_value(normalized_email)` rather than decrypting/scanning every user.
- Default to read-only and print the target’s user ID, workspace ID/slug, current role, owner count, owner user ID, `ROLE_RANK`, and missing capability names. Do not echo the raw email; emit only a short one-way fingerprint.
- Require `--apply`, `--expected-current-owner-id`, and a non-empty `--reason` before writing.
- Emit one structured JSON result containing timestamp, mode, workspace ID, target/previous-owner IDs, before/after roles, reason, rank, and missing capability list. Capture that output under `.ezcoder/eyes/out/` for the operational record; secrets and decrypted PII are excluded.
- Refuse an internal-only Railway database hostname when run locally, matching existing operational-script safeguards.

## Authorization tests

Add focused backend tests only:

- `backend/tests/core/test_permissions.py`: assert owner rank exceeds every other role and owner has every declared `Capability`.
- `backend/tests/api/test_workspace_member_roles.py`: prove ordinary role updates reject `owner`, and existing owners cannot be demoted or removed by owner or admin callers.
- `backend/tests/services/workspaces/test_ownership.py`: prove owner no-op behavior, atomic one-owner transfer, explicit repair from zero owners, stale expected-owner rejection, inactive/cross-workspace target rejection, multiple-owner rejection, and unchanged rows after every failure.
- `backend/tests/scripts/test_set_workspace_owner.py`: prove dry-run never writes, apply requires workspace/expected-owner/reason guards, output omits the raw email, and the result reports rank `100` with no missing capabilities.

## Production execution and proof

1. Run the focused tests and `make ci.backend`; do not touch frontend/codegen because no API contract changes.
2. Run the script without `--apply` against Railway production, capturing its redacted JSON output in `.ezcoder/eyes/out/`.
3. If the target is already the sole owner, make no production write and retain the dry-run result as proof.
4. If there is exactly one different owner (or no owner), rerun with `--apply`, the dry-run’s exact expected-owner value, the exact workspace ID, and reason `Requested by Max to retain highest CRM authority`; capture the result.
5. Immediately rerun the read-only command. Completion requires owner count `1`, target role `owner`, rank `100`, and an empty missing-capabilities list.
6. If the dry run finds multiple owners, a missing target membership, or ambiguous workspaces, stop without mutation and report the exact non-secret blocker; resolving those states would require a separate human decision.

## Steps

1. Add the transaction-safe workspace ownership service with row locking, compare-and-swap protection, idempotency, and a one-owner postcondition.
2. Add the dry-run-first operational script with hashed email lookup, explicit apply guards, and redacted structured audit output.
3. Add authorization, service, and script regression tests for owner rank/full capabilities and every safe-transfer failure mode.
4. Run the focused pytest suites and full backend CI.
5. Run the production dry-run for `max@maxteriors.com` and capture the redacted result.
6. Apply an atomic transfer only if the dry run proves it is needed and unambiguous.
7. Rerun the production audit and require one owner, target rank `100`, and all capabilities before completion.