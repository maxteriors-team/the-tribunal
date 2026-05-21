# Outbound Mission / Lead Miner Persistence

## Goal

Add the persistence layer (SQLAlchemy ORM models, one Alembic migration, Pydantic
schemas, focused unit tests) for the **Outbound Mission / Lead Miner** feature.
This task is **schema-only** — no API routes, services, or workers — but it must
produce a coherent set of tables that downstream code can drive.

The feature lets the platform:

1. Run **discovery jobs** that scan external sources (Google Places, web scrapes,
   CSV uploads, manual seeds) and emit **lead prospects** — pre-contact lead
   candidates that may have only a single identifier (phone, email, website, or
   owner name).
2. Enrich each prospect with one or more provider calls, persisting a full audit
   trail per provider in `lead_enrichment_results`.
3. Group everything under an **outbound mission** that defines the objective,
   ICP, defaults, and per-mission stats.
4. Drive prospects through a multi-channel **outbound sequence** with per-step
   attempt records, ready for handoff to existing campaign / messaging code.

The existing `Contact` model — which requires `phone_number` (NOT NULL) — is
**not modified**. Prospects are a separate table; a prospect that succeeds gets
promoted into a `Contact` via the `lead_prospects.contact_id` FK.

## Research / context

Read first:

- `CLAUDE.md` — backend layout, "Models → `app/models/`, one model per file" (but
  closely-coupled clusters are co-located, e.g. `campaign.py` holds Campaign +
  CampaignContact, `conversation.py` holds Conversation + Message,
  `drip_campaign.py` holds DripCampaign + DripEnrollment, `tag.py` holds Tag +
  ContactTag, `opportunity.py` holds Opportunity + LineItem + Activity).
- `backend/app/db/base.py` — `Base` uses the canonical
  `NAMING_CONVENTION` so all new indexes/constraints get stable names.
- `backend/app/core/encryption.py` — `EncryptedString` (Fernet, TEXT impl) and
  `LookupHash` (TEXT marker for deterministic BLAKE2b hashes via `hash_value` /
  `hash_phone`). PII columns on `Contact` follow the pattern: encrypted column
  with a sibling `*_hash` column carrying the index for equality lookups.
- `backend/app/models/contact.py` — gold-standard PII storage shape; phone is
  required, but Lead Prospects must allow it to be `nullable=True`.
- `backend/app/models/campaign.py` — Enum + StrEnum + JSONB +
  denormalized-stats + composite-index style.
- `backend/app/models/drip_campaign.py` — campaign + enrollment two-table
  layout with `next_step_at` composite index for worker polling.
- `backend/app/models/conversation.py` — partial-uniqueness, "active heads"
  composite index style.
- `backend/app/models/outbound_action_audit_log.py` — already-existing
  append-only audit log we want to mirror in `lead_enrichment_results`.
- `backend/alembic/versions/db01e2f3a4b5_add_drip_campaigns_and_enrollments.py`
  — closest analogue migration shape (two new tables, JSONB sequence_steps,
  composite next-step index).
- `backend/alembic/versions/20260519_outbound_compliance_controls.py` — recent
  multi-table migration with `op.create_table` + multiple `op.create_index`.
- `backend/alembic/versions/b5c6d7e8f9a0_add_assistant_conversations_updated_at.py`
  — **current head**; new migration's `down_revision`.

Pattern decisions taken from this read:

- Enums: `StrEnum` declared next to the model + `SAEnum(..., native_enum=False,
  create_constraint=False, length=50, values_callable=lambda e: [m.value for m
  in e])` — matches `Campaign`, `DripCampaign`, `EmailEvent`.
- JSONB defaults: `JSONB, default=dict, nullable=False` for "always object"
  fields, `JSONB, default=list, nullable=False` for arrays. Migration uses
  `server_default=sa.text("'{}'::jsonb")` / `sa.text("'[]'::jsonb")` for these
  so existing rows (none, but the discipline holds) survive `NOT NULL`.
- Timestamps: `created_at` + `updated_at` with
  `default=lambda: datetime.now(UTC)` and `onupdate=lambda: datetime.now(UTC)`.
- Workspace FK: `UUID(as_uuid=True), ForeignKey("workspaces.id",
  ondelete="CASCADE"), nullable=False, index=True`.
- One migration per feature, not one per table.

## New tables (7) and their files

```
backend/app/models/outbound_mission.py
    - MissionStatus (StrEnum)
    - OutboundMission

backend/app/models/lead_prospect.py
    - ProspectStatus, ProspectIdentityKind, EnrichmentProvider,
      EnrichmentResultStatus (StrEnum)
    - LeadProspect
    - LeadEnrichmentResult

backend/app/models/lead_discovery_job.py
    - DiscoverySourceType, DiscoveryJobStatus (StrEnum)
    - LeadDiscoveryJob

backend/app/models/outbound_sequence.py
    - OutboundSequenceStatus, SequenceStepChannel,
      SequenceEnrollmentStatus, SequenceStepAttemptStatus (StrEnum)
    - OutboundSequence
    - OutboundSequenceEnrollment
    - OutboundSequenceStepAttempt
```

The Mission ↔ Sequence relationship is mutual-optional: `OutboundMission` has
`default_sequence_id` pointing at `OutboundSequence`, and `OutboundSequence`
does NOT carry a `mission_id` (sequences are reusable workspace assets). This
avoids a circular FK; the migration creates `outbound_sequences` first, then
`outbound_missions`.

### `OutboundMission` fields

- `id: uuid.UUID` primary key
- `workspace_id: uuid.UUID` → workspaces.id CASCADE, indexed
- `created_by_id: int | None` → users.id SET NULL, indexed
- `offer_id: uuid.UUID | None` → offers.id SET NULL, indexed
- `default_agent_id: uuid.UUID | None` → agents.id SET NULL, indexed
- `default_sequence_id: uuid.UUID | None` → outbound_sequences.id SET NULL,
  indexed
- `name: str` (255, NOT NULL)
- `description: str | None` Text
- `objective: str` (50, default `"book_call"`) — book_call, qualify, nurture,
  demo, custom
- `status: MissionStatus` default DRAFT, indexed
- `target_audience: dict[str, Any]` JSONB default dict
- `discovery_config: dict[str, Any]` JSONB default dict
- `enrichment_config: dict[str, Any]` JSONB default dict
- `sequence_config: dict[str, Any]` JSONB default dict
- `default_from_phone_number: str | None` (50)
- `default_from_email: str | None` (320)
- `daily_prospect_cap: int` default 100
- `daily_outreach_cap: int` default 50
- `timezone: str` (50) default "America/New_York"
- Denormalized stats: `total_prospects_discovered`, `total_prospects_enriched`,
  `total_prospects_contacted`, `total_prospects_replied`,
  `total_prospects_qualified`, `total_contacts_created`,
  `total_appointments_booked` — all Integer NOT NULL default 0.
- Timestamps + lifecycle: `started_at`, `paused_at`, `completed_at`,
  `archived_at`, `last_run_at`, `next_run_at` — all DateTime(timezone=True)
  nullable; plus standard `created_at`/`updated_at`.

`MissionStatus`: `DRAFT`, `ACTIVE`, `PAUSED`, `COMPLETED`, `ARCHIVED`.

Indexes:
- `ix_outbound_missions_workspace_id` (workspace_id)
- `ix_outbound_missions_status` (status) — already covered by `index=True`
- `ix_outbound_missions_workspace_status` (workspace_id, status) composite
- `ix_outbound_missions_workspace_updated_at` (workspace_id, updated_at DESC)
  composite for "recent missions" listing.

### `LeadDiscoveryJob` fields

- `id: uuid.UUID` PK
- `workspace_id: uuid.UUID` CASCADE, indexed
- `mission_id: uuid.UUID | None` → outbound_missions.id SET NULL, indexed
- `requested_by_id: int | None` → users.id SET NULL, indexed
- `source_type: DiscoverySourceType` (NOT NULL)
- `source_label: str | None` (255)
- `query: str | None` Text
- `params: dict[str, Any]` JSONB default dict
- `status: DiscoveryJobStatus` default PENDING, indexed
- Counters: `requested_count`, `discovered_count`, `duplicate_count`,
  `invalid_count` — Integer NOT NULL default 0.
- `started_at`, `completed_at` nullable DateTime
- `last_error: str | None` Text
- `error_count: int` default 0
- standard `created_at` / `updated_at`

`DiscoverySourceType`: `GOOGLE_PLACES`, `WEB_SCRAPE`, `CSV_IMPORT`, `MANUAL`,
`API`, `LINKEDIN`, `OTHER`.

`DiscoveryJobStatus`: `PENDING`, `RUNNING`, `SUCCEEDED`, `FAILED`, `CANCELLED`.

Indexes:
- `ix_lead_discovery_jobs_workspace_id`, `ix_lead_discovery_jobs_status`
- `ix_lead_discovery_jobs_mission_status` (mission_id, status)
- `ix_lead_discovery_jobs_workspace_created_at` (workspace_id, created_at DESC)

### `LeadProspect` fields

Key design point: **all channel identifiers are nullable**. A prospect can be
phone-only, email-only, website-only, or owner-name-only. The PII columns mirror
`Contact`'s shape: encrypted at rest with a sibling `*_hash` column for lookup
indexes.

- `id: uuid.UUID` PK (UUID so prospects can be referenced from URLs/JSON before
  any sync hits the DB autoincrement — Contact uses BigInteger for legacy
  reasons but new tables in this repo lean UUID).
- `workspace_id: uuid.UUID` CASCADE, indexed
- `mission_id: uuid.UUID | None` → outbound_missions.id SET NULL, indexed
- `discovery_job_id: uuid.UUID | None` → lead_discovery_jobs.id SET NULL,
  indexed
- `contact_id: int | None` → contacts.id SET NULL, indexed (set when the
  prospect is promoted to a contact).
- `identity_kind: ProspectIdentityKind` (NOT NULL, default `MULTI`).

Personal identity (all nullable):

- `first_name: str | None` (100)
- `last_name: str | None` (100)
- `full_name: str | None` (255) — single-blob name when split is unclear (the
  "owner-name-only" case).
- `title: str | None` (255)

Channels (all nullable; encrypted where PII):

- `email: str | None` `EncryptedString()`
- `email_hash: str | None` `LookupHash()` indexed
- `phone_number: str | None` `EncryptedString()`
- `phone_hash: str | None` `LookupHash()` indexed

Business / web:

- `company_name: str | None` (255)
- `website_url: str | None` (1024)
- `website_host: str | None` (255) — extracted, normalized hostname
- `website_host_hash: str | None` `LookupHash()` indexed
- `linkedin_url: str | None` (500)
- `owner_name_hash: str | None` `LookupHash()` indexed (computed from
  normalized `full_name` or `first_name + last_name`).

Location:

- `country_code: str | None` (2)
- `region: str | None` (100)
- `city: str | None` (100)
- `location_label: str | None` (255)

Source provenance:

- `source_type: str | None` (50) indexed (mirrors `DiscoverySourceType` values
  but stored as plain text on the prospect for forward compatibility — the
  authoritative enum lives on the job).
- `source_external_id: str | None` (255) indexed
- `source_query: str | None` Text
- `provenance: dict[str, Any]` JSONB default dict — raw "where did this come
  from" record. Example: `{"google_places": {"place_id": "...", ...}, "captured_at": "..."}`.
- `evidence: list[dict[str, Any]]` JSONB default list — chronological list of
  `{kind, value, captured_at, source, confidence}` observations.

Dedupe + scoring:

- `dedupe_key: str | None` (64) — SHA-256 hex of normalized identifier set,
  computed by the application layer at insert. Unique per workspace.
- `lead_score: int` default 0
- `qualification_score: int` default 0

Status:

- `status: ProspectStatus` default `NEW`, indexed.
- `suppression_reason: str | None` (255)

Stats:

- `enrichment_attempts: int` default 0
- `last_enriched_at`, `last_contacted_at`, `last_replied_at`,
  `last_failed_at` — nullable DateTime
- `reply_count: int` default 0
- `bounce_count: int` default 0

Audit timestamps:

- `discovered_at: datetime` default `datetime.now(UTC)`
- `promoted_at: datetime | None`
- standard `created_at` / `updated_at`

`ProspectIdentityKind`: `PHONE`, `EMAIL`, `WEBSITE`, `OWNER_NAME`, `MULTI`.

`ProspectStatus`: `NEW`, `ENRICHING`, `ENRICHED`, `QUEUED`, `CONTACTED`,
`REPLIED`, `QUALIFIED`, `CONVERTED`, `SUPPRESSED`, `ARCHIVED`.

Indexes / constraints:

- `UniqueConstraint("workspace_id", "dedupe_key",
  name="uq_lead_prospects_workspace_dedupe_key")` — application-level upsert
  key (rows without a `dedupe_key` are skipped — Postgres treats `NULL` as
  distinct in unique constraints, so partial-uniqueness is automatic).
- `ix_lead_prospects_workspace_status` (workspace_id, status)
- `ix_lead_prospects_workspace_source` (workspace_id, source_type)
- `ix_lead_prospects_workspace_score` (workspace_id, lead_score DESC)
- `ix_lead_prospects_mission_status` (mission_id, status)
- `ix_lead_prospects_discovery_job_id`, `ix_lead_prospects_contact_id`,
  `ix_lead_prospects_phone_hash`, `ix_lead_prospects_email_hash`,
  `ix_lead_prospects_website_host_hash`, `ix_lead_prospects_owner_name_hash`,
  `ix_lead_prospects_source_external_id` (source_type, source_external_id).

Helper properties on the ORM class:

- `has_phone`, `has_email`, `has_website`, `has_owner_name`, `is_promoted` —
  small pure booleans driven off the columns; mirror `Contact.has_address`.

### `LeadEnrichmentResult` fields

Append-only audit row: one per provider call against a prospect.

- `id: uuid.UUID` PK
- `workspace_id: uuid.UUID` CASCADE, indexed
- `prospect_id: uuid.UUID` → lead_prospects.id CASCADE, indexed
- `mission_id: uuid.UUID | None` → outbound_missions.id SET NULL, indexed
- `provider: EnrichmentProvider` (NOT NULL)
- `status: EnrichmentResultStatus` (NOT NULL)
- `request_payload: dict[str, Any] | None` JSONB
- `response_payload: dict[str, Any] | None` JSONB
- `extracted: dict[str, Any]` JSONB default dict — canonical extracted fields
  (linkedin_url, decision_maker_name, etc.)
- `score_delta: int` default 0
- `cost_cents: int | None`
- `duration_ms: int | None`
- `error_message: str | None` Text
- `created_at: datetime` default `datetime.now(UTC)` — no `updated_at` because
  rows are immutable.

`EnrichmentProvider`: `GOOGLE_PLACES`, `WEBSITE_SCRAPER`, `AI_CONTENT_ANALYZER`,
`LINKEDIN_LOOKUP`, `EMAIL_LOOKUP`, `PHONE_LOOKUP`, `MANUAL`, `OTHER`.

`EnrichmentResultStatus`: `SUCCESS`, `PARTIAL`, `FAILED`, `SKIPPED`.

Indexes:

- `ix_lead_enrichment_results_workspace_id`,
  `ix_lead_enrichment_results_prospect_id`,
  `ix_lead_enrichment_results_mission_id`,
  `ix_lead_enrichment_results_provider_status` (provider, status),
  `ix_lead_enrichment_results_created_at` (workspace_id, created_at DESC).

### `OutboundSequence` fields

- `id, workspace_id (CASCADE, indexed)`
- `name: str` (255 NOT NULL)
- `description: str | None` Text
- `status: OutboundSequenceStatus` default DRAFT, indexed
- `is_default: bool` default False (workspace default sequence)
- `steps: list[dict[str, Any]]` JSONB default list — same shape as
  `DripCampaign.sequence_steps`, extended with `channel` and
  `stop_on_reply`.
- `channel_priority: list[str] | None` `ARRAY(Text)` — fallback channel order
  for steps that allow promotion (e.g. SMS → email).
- `max_attempts_per_step: int` default 1
- `sending_hours_start: time | None` `Time`, `sending_hours_end: time | None`
- `sending_days: list[int] | None` `ARRAY(Integer)`
- `timezone: str` (50) default "America/New_York"
- Denormalized stats: `total_enrollments`, `total_completed`, `total_replied`,
  `total_converted` — Integer NOT NULL default 0.
- Standard `created_at`/`updated_at`.

`OutboundSequenceStatus`: `DRAFT`, `ACTIVE`, `PAUSED`, `ARCHIVED`.

`SequenceStepChannel`: `SMS`, `EMAIL`, `VOICE`, `MANUAL`.

Indexes:

- `ix_outbound_sequences_workspace_id`,
  `ix_outbound_sequences_workspace_status` (workspace_id, status).

### `OutboundSequenceEnrollment` fields

- `id: uuid.UUID` PK
- `workspace_id` CASCADE, indexed
- `mission_id: uuid.UUID | None` → outbound_missions.id SET NULL, indexed
- `sequence_id: uuid.UUID` → outbound_sequences.id CASCADE, indexed
- `prospect_id: uuid.UUID` → lead_prospects.id CASCADE, indexed
- `status: SequenceEnrollmentStatus` default ACTIVE, indexed
- `current_step: int` default 0
- `next_step_at: datetime | None` indexed
- `last_attempt_at: datetime | None`
- `last_outcome: str | None` (50)
- `cancel_reason: str | None` (255)
- `attempts_made: int` default 0
- `successful_attempts: int` default 0
- `failed_attempts: int` default 0
- `enrolled_at: datetime` default `datetime.now(UTC)`
- `completed_at: datetime | None`
- `paused_until: datetime | None`
- standard `created_at`/`updated_at`

`SequenceEnrollmentStatus`: `ACTIVE`, `PAUSED`, `COMPLETED`, `REPLIED`,
`OPTED_OUT`, `CONVERTED`, `FAILED`, `CANCELLED`.

Constraints / indexes:

- `UniqueConstraint("sequence_id", "prospect_id",
  name="uq_outbound_sequence_enrollments_sequence_prospect")` — a prospect
  can enroll in the same sequence only once.
- `ix_outbound_sequence_enrollments_status_next_step` (status, next_step_at)
  — worker polling.
- `ix_outbound_sequence_enrollments_mission_status` (mission_id, status).

### `OutboundSequenceStepAttempt` fields

- `id: uuid.UUID` PK
- `workspace_id` CASCADE, indexed
- `enrollment_id: uuid.UUID` → outbound_sequence_enrollments.id CASCADE,
  indexed
- `prospect_id: uuid.UUID` → lead_prospects.id CASCADE, indexed
- `step_index: int`
- `attempt_number: int` default 1
- `channel: SequenceStepChannel`
- `status: SequenceStepAttemptStatus` default PENDING, indexed
- `scheduled_at: datetime`
- `sent_at: datetime | None`
- `completed_at: datetime | None`
- `message_id: uuid.UUID | None` → messages.id SET NULL, indexed
- `conversation_id: uuid.UUID | None` → conversations.id SET NULL, indexed
- `pending_action_id: uuid.UUID | None` → pending_actions.id SET NULL, indexed
- `outcome: str | None` (50)
- `outcome_detail: dict[str, Any] | None` JSONB
- `error_message: str | None` Text
- `template_snapshot: str | None` Text
- `rendered_body: str | None` Text
- `rendered_subject: str | None` (255)
- standard `created_at`/`updated_at`

`SequenceStepAttemptStatus`: `PENDING`, `SCHEDULED`, `IN_FLIGHT`,
`SUCCEEDED`, `SKIPPED`, `FAILED`, `CANCELLED`.

Constraints / indexes:

- `UniqueConstraint("enrollment_id", "step_index", "attempt_number",
  name="uq_outbound_step_attempts_enrollment_step_attempt")`
- `ix_outbound_step_attempts_enrollment_step` (enrollment_id, step_index)
- `ix_outbound_step_attempts_status_scheduled_at` (status, scheduled_at)

## Migration

One file:

```
backend/alembic/versions/20260521_add_outbound_missions_and_lead_miner.py
```

- `revision: str = "20260521_add_outbound_missions_and_lead_miner"`
- `down_revision: str | Sequence[str] | None = "b5c6d7e8f9a0"` (current head).
- Pure additive — only `op.create_table` + `op.create_index`. No alterations
  to `contacts` or any other existing table.

Creation order (so FKs resolve):

1. `outbound_sequences`
2. `outbound_missions` (FK `default_sequence_id` → outbound_sequences)
3. `lead_discovery_jobs` (FK `mission_id` → outbound_missions)
4. `lead_prospects` (FK `mission_id`, `discovery_job_id`, `contact_id`)
5. `lead_enrichment_results` (FK `prospect_id`, `mission_id`)
6. `outbound_sequence_enrollments` (FK `mission_id`, `sequence_id`,
   `prospect_id`)
7. `outbound_sequence_step_attempts` (FK `enrollment_id`, `prospect_id`,
   `message_id`, `conversation_id`, `pending_action_id`)

Each `create_table` uses:

- `postgresql.UUID(as_uuid=True)` for UUID columns,
- `server_default=sa.text("gen_random_uuid()")` on `id` columns (the project
  already relies on `pgcrypto` per `outbound_action_audit_logs`),
- `server_default=sa.func.now()` on `created_at` and `updated_at`,
- `server_default=sa.text("'{}'::jsonb")` / `"'[]'::jsonb"` for JSONB
  containers,
- `nullable=False, server_default='0'` for Integer stat counters.

Downgrade drops indexes (reverse order) then tables (reverse creation order).

## Pydantic schemas

One schema file per table cluster, mirroring how `campaign.py` / `drip_campaign.py`
schemas are organized. Each schema file exposes Create, Update, Response (and a
paginated list variant where useful).

- `backend/app/schemas/outbound_mission.py`
  - `OutboundMissionCreate`, `OutboundMissionUpdate`, `OutboundMissionResponse`,
    `OutboundMissionStatsResponse`, `PaginatedOutboundMissions`.
- `backend/app/schemas/lead_discovery_job.py`
  - `LeadDiscoveryJobCreate`, `LeadDiscoveryJobUpdate`,
    `LeadDiscoveryJobResponse`, `PaginatedLeadDiscoveryJobs`.
- `backend/app/schemas/lead_prospect.py`
  - `LeadProspectCreate`, `LeadProspectUpdate`, `LeadProspectResponse`,
    `LeadEnrichmentResultCreate`, `LeadEnrichmentResultResponse`,
    `PaginatedLeadProspects`.
  - `LeadProspectCreate` MUST allow any one of `phone_number`, `email`,
    `website_url`, `full_name`/(`first_name`+`last_name`) to be present and
    the rest to be missing — enforced with a Pydantic `model_validator(mode="after")`
    that raises `ValueError("at least one identifier required")` if all four are
    `None`.
- `backend/app/schemas/outbound_sequence.py`
  - `OutboundSequenceStep` (sub-model: `order: int`, `channel:
    SequenceStepChannel`, `delay_hours: int`, `template: str | None`,
    `subject: str | None`, `agent_id: uuid.UUID | None`, `stop_on_reply: bool`),
  - `OutboundSequenceCreate`, `OutboundSequenceUpdate`,
    `OutboundSequenceResponse`,
  - `OutboundSequenceEnrollmentResponse`,
  - `OutboundSequenceStepAttemptResponse`.

All response schemas use `model_config = ConfigDict(from_attributes=True)`.

## Exports

- `backend/app/models/__init__.py` — append new model classes + their StrEnums to
  the import block and to `__all__`. Order: keep alphabetical by class name
  within their existing groups.
- `backend/app/schemas/__init__.py` — append the new schemas to the import block
  and `__all__`.

No changes to `app/api/v1/router.py`, no new routes, no service / worker code.

## Tests

Two new files, following the project's schema/model unit-test patterns:

1. `backend/tests/models/test_outbound_mission_models.py`
   - Replaces the existing placeholder behaviour for this feature (the
     placeholder file itself remains untouched).
   - Pure in-memory ORM construction — no DB. Each test instantiates a model
     with the minimum required kwargs (using `uuid.uuid4()` for FK columns) and
     asserts:
     - Default column values match the field declarations
       (status enum default, JSONB default `{}` / `[]`, Integer counters = 0,
       `timezone == "America/New_York"`, etc.).
     - Enums are `StrEnum` subclasses and `.value` is what we expect.
     - `__repr__` returns a non-empty string containing the table name.
     - `LeadProspect` is happy with each of: phone-only, email-only,
       website-only, owner-name-only inputs (asserts `has_phone`/`has_email`/
       `has_website`/`has_owner_name` flags flip correctly).
     - `__table__.columns` exposes the encrypted columns + lookup hashes for
       `phone`, `email`, `website_host`, and `owner_name_hash`.
     - `LeadProspect.__table_args__` includes the workspace+dedupe unique
       constraint and the workspace-status composite index by name.
     - `OutboundSequenceEnrollment.__table_args__` includes the
       sequence+prospect unique constraint.
     - `OutboundSequenceStepAttempt.__table_args__` includes the
       enrollment+step+attempt unique constraint.

2. `backend/tests/schemas/test_outbound_mission_schemas.py`
   - Pure Pydantic validation tests — no DB.
   - `OutboundMissionCreate`: minimal required fields pass; missing name
     raises `ValidationError`; defaults are correctly populated.
   - `LeadProspectCreate`: phone-only, email-only, website-only,
     owner-name-only each pass; all-`None` identifiers raise `ValidationError`
     with the "at least one identifier required" message; invalid email raises.
   - `LeadDiscoveryJobCreate`: defaults pass; unknown `source_type` raises.
   - `OutboundSequenceCreate`: empty steps list passes; step entries validate
     against the `OutboundSequenceStep` sub-model.
   - All response schemas: `model_config.get("from_attributes") is True`.
   - Each Response schema: round-trip from a dict mimicking a SQLAlchemy row
     using `model_validate(...)` succeeds.

The existing `backend/tests/models/test_placeholder.py` stays in place (it
skips the whole module); the new test file is what actually runs.

## Order of work (Steps)

The Steps section below drives the progress widget. Each step is a discrete
file write / edit + a quick verification run.

## Verification

After every model/schema/migration edit:

```
cd backend && uv run ruff check app && uv run mypy app
```

After the test files exist:

```
cd backend && uv run pytest backend/tests/models/test_outbound_mission_models.py \
                           backend/tests/schemas/test_outbound_mission_schemas.py -q
```

(Use the project-relative path, i.e. `tests/...` from `backend/`.)

If those pass, ruff + mypy both clean, run the full feature once:

```
cd backend && uv run pytest tests/models tests/schemas -q
```

This catches any model/schema export changes that might have broken sibling
tests.

## Risks / non-goals

- **Not** changing `contacts.phone_number` nullability. Contact still requires
  phone. Prospects are the partial-identity surface.
- **Not** adding API routes, services, workers, or worker fixtures. Downstream
  feature work attaches to these tables in later PRs.
- The mutual-optional Mission/Sequence FK requires the create-order discipline
  documented in the Migration section — getting the order wrong makes Alembic
  fail with a missing-table error.
- `lead_prospects.dedupe_key` is uniqueness-by-app-layer; rows where the
  computed key is `NULL` are permitted (Postgres treats NULL as distinct in a
  unique constraint, so multiple `NULL`s coexist). This matches Contact's email
  uniqueness story.

## Out-of-scope follow-ups (notes only — do NOT do them here)

- Service layer (`backend/app/services/outbound/lead_miner.py`) that computes
  `dedupe_key`, performs upserts, kicks off discovery jobs, and promotes
  prospects to contacts.
- API routes in `backend/app/api/v1/lead_miner.py` and inclusion in
  `router.py`.
- Background worker that drains `outbound_sequence_enrollments` where
  `status='active' AND next_step_at <= now()`.
- Frontend wiring (Mission/Prospect pages, lead-miner UI).
- OpenAPI regeneration (`backend/openapi.json`) — that only happens once the
  API layer lands.

## Steps

1. Add `backend/app/models/outbound_mission.py` with `OutboundMission`, `MissionStatus`, all column declarations, indexes, and `__repr__`.
2. Add `backend/app/models/outbound_sequence.py` with `OutboundSequence`, `OutboundSequenceEnrollment`, `OutboundSequenceStepAttempt`, their StrEnums, indexes, constraints, and `__repr__`.
3. Add `backend/app/models/lead_discovery_job.py` with `LeadDiscoveryJob`, `DiscoverySourceType`, `DiscoveryJobStatus`, and indexes.
4. Add `backend/app/models/lead_prospect.py` with `LeadProspect`, `LeadEnrichmentResult`, all StrEnums (`ProspectStatus`, `ProspectIdentityKind`, `EnrichmentProvider`, `EnrichmentResultStatus`), helper properties, and indexes/constraints.
5. Register every new model + enum in `backend/app/models/__init__.py` (imports and `__all__`).
6. Add the Alembic migration `backend/alembic/versions/20260521_add_outbound_missions_and_lead_miner.py` with `down_revision = "b5c6d7e8f9a0"` and table creation in dependency order.
7. Add `backend/app/schemas/outbound_mission.py` (Create, Update, Response, Paginated).
8. Add `backend/app/schemas/outbound_sequence.py` (step sub-model + Create/Update/Response + enrollment + step-attempt responses).
9. Add `backend/app/schemas/lead_discovery_job.py` (Create, Update, Response, Paginated).
10. Add `backend/app/schemas/lead_prospect.py` (Create, Update, Response, Paginated, plus the LeadEnrichmentResult schemas; include the "at least one identifier" model_validator).
11. Register new schemas in `backend/app/schemas/__init__.py` (imports and `__all__`).
12. Add `backend/tests/models/test_outbound_mission_models.py` covering defaults, enums, partial-identity prospects, encrypted columns presence, and `__table_args__` constraint/index names.
13. Add `backend/tests/schemas/test_outbound_mission_schemas.py` covering Create/Update/Response validation for every new schema, including the "at least one identifier" rule.
14. Run `cd backend && uv run ruff check app && uv run mypy app` and fix any reported issues.
15. Run `cd backend && uv run pytest tests/models/test_outbound_mission_models.py tests/schemas/test_outbound_mission_schemas.py -q` and fix any failures.
16. Run `cd backend && uv run pytest tests/models tests/schemas -q` to confirm no regressions in sibling tests.
17. Invoke the `commit-work` skill to stage and commit the new files in logical commits (models + migration; schemas; tests).
