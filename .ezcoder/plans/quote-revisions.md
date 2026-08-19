# Quote revision implementation

## Steps

1. Inspect the current wizard payload, quote snapshots, status guards, and tests to define a lossless hydration/update contract.
2. Add backend APIs that reopen draft/sent wizard quotes in place and copy approved/declined/expired/converted quotes into a new draft revision without mutating paid or customer-approved records.
3. Add explicit revision lineage and migration fields so the source quote remains auditable and protected.
4. Hydrate the full sales wizard from the saved proposal input/snapshot and save through the correct update-or-revise endpoint.
5. Replace the limited quote action with a clear full-wizard edit/revise action while preserving basic edits, manual deposits, customer links, and conversion behavior.
6. Add focused backend/frontend tests for status rules, deposit safety, lineage, hydration, pricing edits, loading/error states, keyboard semantics, and mobile reflow.
7. Regenerate OpenAPI clients, run targeted checks and runtime probes, and document changed-scope accessibility and compliance evidence.