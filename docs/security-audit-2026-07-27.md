# Security Audit — The Tribunal (CRM + website)

**Date:** 2026-07-27 · **HEAD:** `5a6dfd7` · **Mode:** read-only static audit + live header probes against production.

**Scope:** client-data confidentiality, exfiltration paths, encryption in transit/at rest, access control, exposed credentials/endpoints, deployment hardening, search-engine discoverability.

**Method:** six parallel domain audits over `backend/app/**`, `frontend/src/**`, `.github/**`, deploy config and git history, followed by an adversarial false-positive review. Every finding below was traced to specific code; the ones marked **[verified by lead]** were independently re-confirmed by hand. Dismissed claims are listed in §8 so they don't get re-litigated.

---

## 0. Posture summary

The security *foundations* here are genuinely above average — Argon2id, httpOnly cookies, fail-closed webhook signature verification on all five providers, a startup entropy check on secrets, exact-match CORS, non-root containers, disabled prod API docs, clean git history, and field-level encryption on the `contacts` table. That work is real and §7 lists it.

The problem is **coverage, not capability**. The same controls that are implemented correctly in one place are simply absent in the neighbouring module. The three worst issues all have that shape:

- Two WebSocket endpoints authenticate the handshake properly; the third — the one carrying **live call audio** — has no authentication at all.
- `contacts.phone_number` is encrypted; the identical phone number is stored **plaintext and indexed** on `conversations`, along with every SMS body and call transcript.
- Every other endpoint in `phone_numbers.py` filters by `workspace_id`; the two read endpoints don't, and return **every tenant's** phone numbers.

Net: a determined attacker does not need to break your crypto or your auth. They can join a live customer call unauthenticated, or read plaintext transcripts out of a production database dump sitting world-readable in your working tree.

**Counts:** 3 Critical · 8 High · 11 Medium · 4 Low.

---

## Remediation status — updated 2026-07-28

**Fixed in code and verified** (backend `2895 passed`, `ruff` clean, `mypy` clean over 658 files; frontend `tsc` clean, `next build` green, headers confirmed against a running production server):

| ID | Issue | What changed |
|---|---|---|
| **C-1** | Unauthenticated voice-bridge WebSocket | New `backend/app/services/telephony/stream_auth.py` mints a short-lived HMAC ticket bound to `call_control_id`; `build_stream_url` embeds it; `voice_stream_bridge` verifies it **before** `accept()`. 19 tests. |
| **C-2** | Cross-workspace phone-number enumeration | Both handlers now use `apply_workspace_scope` / `assert_workspace_owned`. |
| **H-3** | `--forwarded-allow-ips=*` IP spoofing | Replaced with explicit private CIDRs in `railway.toml` + `Dockerfile`; `_extract_forwarded_ip` now walks XFF in reverse and returns the rightmost untrusted hop. Stale docs in `CLAUDE.md` / `backend/README.md` corrected. |
| **H-5** | SSRF via user-controlled `website` URL | New `backend/app/services/scraping/url_guard.py`; `follow_redirects=False` with every hop re-validated; upstream error text no longer echoed to callers. |
| **H-6** | Cross-tenant FK grafting on quotes/invoices | `_validate_refs` on create **and** update in both services, covering `contact_id`, `service_location_id`, `opportunity_id`. |
| **H-1** | Transcripts / message bodies / conversation phones in plaintext | `conversations` + `messages` PII columns converted to `EncryptedString`; `contact_phone`/`workspace_phone` gained `*_hash` siblings and `uq_conversation_phones` moved onto the hashes. Migration `1dce03676e16`. |
| **H-2** | Plaintext TCPA suppression list + lead PII; rotation script silently no-oped | `global_opt_outs`, `lead_magnet_leads`, `demo_requests`, `human_profiles`, `phone_messages`, `caller_memories`, `link_clicks` encrypted; `uq_workspace_opt_out` and `ix_demo_requests_phone_created_at` re-pointed at hashes. `scripts/ops/reencrypt_with_old_key.py` now validates every declared target is genuinely an `EncryptedString` and exits non-zero on a misdeclared target or a wholly-skipped table — that new guard immediately caught `LeadMagnetLead.name`, still plaintext, now encrypted. |
| **§5** | Search-engine discoverability | `frontend/src/app/robots.ts`, default `robots` metadata in `layout.tsx`, and a `headers()` block adding `X-Robots-Tag` + the full security header set. Verified live: `/login` returns `X-Frame-Options: DENY` + `frame-ancestors 'none'`; `/embed/*` deliberately keeps `frame-ancestors https:` so customer iframes still work. |

**Also fixed since:** **C-3** — all 9 database dumps (5 prod + 4 local, every one containing plaintext customer phone numbers) are now AES-256-CBC + PBKDF2 encrypted at mode 600, with the plaintext originals removed only after a byte-for-byte `sha256` round-trip check passed on all 9. `make db.backup.local` / `db.backup.prod` now encrypt at creation and `db.restore.local` transparently decrypts `.enc`; the key lives outside the repo at `~/.the-tribunal-backup-keys/backups.key` (mode 600). The two credential notes were `chmod 600`'d as interim mitigation pending rotation.

**Still open — needs a human (see §9):** H-7 (rotate Telnyx/ngrok keys — dashboard-only), the DB credential rotation half of C-3, Google Search Console removals, and the M/L series.

### Correction to §5 Fix 5 — Vercel Deployment Protection was already enabled

The original recommendation ("turn on Standard Protection, highest-value single toggle") was **wrong, and following it literally would have taken the lead-capture funnel offline.** Recorded here so it isn't re-tried.

Queried live via the Vercel API: the project already has `ssoProtection: {"deploymentType": "all_except_custom_domains"}` — i.e. Standard Protection, already on. Verified empirically:

- Deployment-specific URLs (`the-tribunal-<hash>-maxteriors.vercel.app`) → **302 to `vercel.com/sso-api`**. These are the URLs enumerable through certificate-transparency logs, and they are protected.
- The production alias (`the-tribunal-two.vercel.app`) → **200, real app**. Standard Protection deliberately exempts the production domain.

The original audit probed only the production alias, saw `200`, and concluded protection was off. It was measuring the one surface the setting is designed to exclude.

**Protection must NOT be extended to the production domain.** The same Vercel project serves the public lead-capture surfaces — `/offers` and `/lead-magnets` both return 200 today, plus `/p/<slug>` forms and the `/embed/<publicId>` widget that customer sites iframe. Putting Vercel SSO in front of the production domain would require a Vercel account login to reach any of them, breaking inbound lead capture and every embedded widget.

The dashboard's actual protection is application auth, and that was verified: an unauthenticated `GET /contacts` returns only the Next.js shell — grepping the response for emails, phone numbers, and `@domain` patterns yields no customer data. Combined with the `noindex` header now shipping, the residual exposure is "an unauthenticated visitor can see a login page," which is standard SaaS posture rather than a finding.

### Incident note — uncommitted work lost to a concurrent `git reset`

During the H-4/H-8 work a concurrent branch-protection experiment ran `git reset` back to `origin/main` (visible in `git reflog` as `reset: moving to origin/main`, alongside two discarded probe commits). That discarded **every uncommitted edit to tracked files** — the H-4/H-8 route wiring, the model column, the worker/model registrations, the test updates, and the Makefile/CLAUDE.md/audit-doc edits. Untracked new files survived, so the substantive new modules (`mac_relay_auth.py`, `webhook_replay.py`, `webhook_signature.py`, the cleanup worker, both migrations) were unaffected, as were the already-encrypted dumps on disk.

The work was rebuilt against those surviving modules. Two lessons worth keeping: commit security fixes as soon as they verify rather than batching them, and note that both migrations had already been applied to the local database, so after the reset the schema was *ahead* of the models — `alembic check` is the fastest way to detect that split.

### Encryption migration — verification record (`1dce03676e16`)

29 columns across 9 tables. Verified locally against real dev data (25 conversations, 21 messages, 8 demo requests, 1 opt-out):

- **up → down → up** cycle run twice: zero row loss, plaintext fully restored on downgrade (including original `varchar` widths), re-encrypted on re-upgrade.
- **`alembic check`**: no model/migration drift.
- **Post-migration scan**: `plaintext_rows=0` across conversations, messages, and opt-outs; zero NULL lookup hashes.
- **End-to-end**: ORM decrypts on read; the rewritten TCPA suppression check returns `True` for an opted-out number and `False` for a clean one; a newly constructed `Conversation` auto-populates its hashes and is found by a formatting-insensitive lookup (`+1 (555) 000-2299` → `+15550002299`).
- **Runtime**: backend booted clean, `/readyz` 200, zero `InvalidToken`/`UndefinedColumn`/decrypt errors in the log.
- Backend suite **2924 passed**, ruff + format clean, mypy clean over 659 files.

**Deliberate design notes**

- Fernet is non-deterministic, so uniqueness and indexes had to move to deterministic `*_hash` columns — an index or `UNIQUE` on ciphertext is silently useless. Two constraints moved; `ix_demo_requests_phone_created_at` was re-pointed because it backs the demo rate-limit scan and would otherwise have gone dead.
- The migration **pre-flights normalization collisions before mutating any data**. `hash_phone` strips formatting, so rows that differ only in formatting (`+15551234567` vs `(555) 123-4567`) merge under the new constraints. Local data is clean, but production may not be — the migration aborts with the offending row IDs rather than failing halfway through an encrypted table.
- Encryption is idempotent (values already starting with `gAAAAA` are skipped), so a partially-applied prior attempt cannot double-encrypt.
- Content columns (bodies, transcripts, summaries, previews) got no hash sibling: nothing filters or full-text-searches them. The one `to_tsvector` index in the schema is on `knowledge_chunks.content`, a different table, and is untouched.
- `__repr__` on the affected models no longer interpolates now-encrypted PII (reprs land in logs and SQLAlchemy error messages), and each is guarded against the pre-flush state where the hash is still `None`.

**Before deploying this migration to production:** take a fresh dump (`make db.backup.prod`) — it rewrites contact/lead-adjacent tables. Run the pre-flight once against a prod restore to surface any phone-format collisions before the real run.

---

## 1. CRITICAL — fix before the next deploy

### C-1. `/voice/stream/{call_id}` WebSocket has no authentication — live cross-tenant call hijack **[verified by lead]**

**Evidence:** `backend/app/websockets/voice_bridge.py:319-362`. The route is declared `@router.websocket("/voice/stream/{call_id}")` and reaches `await websocket.accept()` (`:361`) after **only** a capacity semaphore. Grepping the file for `_authenticate_websocket`, `ticket`, or `token` returns **zero matches**. Compare `voice_test.py:400` and `call_supervisor.py:248`, which both authenticate *before* accept. Mounted with no dependency at `backend/app/main.py:599`.

Tenancy is resolved *after* accept, purely from the path parameter: `voice_bridge.py:367` → `lookup_call_context(call_id)` → `app/services/ai/call_context.py:191-204` selects on `Message.provider_message_id == call_id`. The caller's identity never participates in the lookup.

**Why `call_id` is not a secret:** it is the Telnyx `call_control_id`, logged on every voice webhook (`backend/app/api/webhooks/telnyx.py:122-128`) and embedded in the stream URL path (`backend/app/services/telephony/telnyx_voice.py:1142`) rather than in a header or signed token.

**Attack:** connect `wss://<api-host>/voice/stream/<call_control_id>` from anywhere — no cookie, no JWT, no Telnyx signature, no `Origin` check. The server loads the victim tenant's agent, system prompt, and contact PII (name/phone/email/company/notes), then opens a provider voice session **billed to that workspace** (`voice_bridge.py:566-573`). The attacker's frames drive the receive loop (`:940`), injecting synthetic caller audio into the tenant's AI agent, while agent audio streams back to the attacker (`:1131-1150`). Transcripts persist into the victim workspace.

**Impact:** unauthenticated read of live call audio + PII, unauthenticated *write* into another tenant's AI agent, and theft of their paid AI/voice credits. Highest blast radius in the report.

**Fix:**
1. In `TelnyxVoiceService.build_stream_url` (`telnyx_voice.py:1124-1145`), append a short-lived single-use HMAC token bound to `call_control_id` + expiry.
2. Verify it in `voice_stream_bridge` **before** `websocket.accept()`; reject with `WS_1008_POLICY_VIOLATION`.
3. Mark the token consumed on first bridge so a leaked URL can't be reused.
4. Reject requests carrying an `Origin` header on this endpoint (Telnyx sends none) and, if feasible, allow-list Telnyx media egress IPs.

---

### C-2. Cross-workspace phone-number enumeration **[verified by lead]**

**Evidence:** `backend/app/api/v1/phone_numbers.py:36-38` — `query = select(PhoneNumber)` under the comment *"Phone numbers are shared across workspaces - don't filter by workspace_id"*. Same at `:61-65` for `GET /{phone_number_id}`.

The premise is false: `backend/app/models/phone_number.py:60` declares `workspace_id` as non-nullable and indexed, and every *other* handler in the same file (`:88`, `:195`, PUT, DELETE) filters on it correctly. `PhoneNumberResponse` (`backend/app/schemas/phone_number.py:8-25`) returns `workspace_id`, `phone_number`, `friendly_name`, `assigned_agent_id`, `mac_relay_sender_id`.

**Attack:** register a free account (auto-provisioned as `owner` of a personal workspace via `app/services/workspaces/provisioning.py:85-96`), then `GET /api/v1/workspaces/{your_own_id}/phone-numbers?page_size=100&active_only=false`. Both the membership check and `CanReadCRM` pass legitimately — and the query returns **every phone-number row in the database**: every tenant's E.164 numbers, their business names via `friendly_name`, and a harvest of valid `workspace_id` UUIDs to use as the seed for probing every other workspace-scoped route.

**Fix:** use the helpers that already exist in this codebase.
```python
from app.db.scope import apply_workspace_scope, assert_workspace_owned

# :37
query = apply_workspace_scope(select(PhoneNumber), PhoneNumber, workspace_id)
# :61
phone_number = await assert_workspace_owned(
    db, PhoneNumber, phone_number_id, workspace_id, detail="Phone number not found"
)
```
Delete the two misleading comments. Add a regression test asserting workspace B's number 404s for a workspace A member.

---

### C-3. Unencrypted production database dumps in the working tree, mode 0644 **[verified by lead]**

**Evidence:** `ls -la backend/backups/` shows six `pg_dump -Fc` archives, all `-rw-r--r--`:

| file | size |
|---|---|
| `prod-20260702-124707.dump` | 445 KB |
| `prod-20260710-181415.dump` | 2.0 MB |
| `prod-20260727-214816.dump` | 2.4 MB |
| plus 3 × `aicrm-*.dump` | |

Created by `Makefile:292-302` (`db.backup.prod`), which writes cleartext into `BACKUP_DIR := backend/backups` (`Makefile:17`).

The crypto auditor inflated the compressed blocks of the newest prod dump and counted **72 plaintext E.164 phone numbers vs 4 Fernet ciphertext tokens** — a direct measurement of the C-4 encryption gap. (Contents were counted, not printed.)

`.gitignore:168` correctly keeps these out of git — which is exactly why the on-disk exposure is easy to miss. Nothing protects the files at rest, and `backend/.env` holding `ENCRYPTION_KEY` sits in the same tree, so an attacker who reads the directory gets both the data and the key.

**Attack:** laptop theft, a Time Machine/Dropbox/iCloud sync, a malicious npm/pip postinstall with fs access, or any local process running as another user reads a complete production PII snapshot. No credential required.

**Fix:**
1. Treat the three existing `prod-*.dump` files as disclosed: shred them (`rm -P`) and rotate the production DB credential.
2. Encrypt at creation and never write cleartext — `pg_dump … | age -r <recipient> > "$out.age"`.
3. Write to `$TMPDIR` or an encrypted volume, not the repo; `chmod 600`.
4. Add a `db.backup.purge` target and a documented retention limit.

---

## 2. HIGH

### H-1. Call transcripts, message bodies and conversation phone numbers stored in plaintext **[verified by lead]**

**Evidence:** `backend/app/models/conversation.py`:
```python
:149-151  contact_phone: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
:183      last_message_preview: Mapped[str | None] = mapped_column(String(255), ...)
:318      body: Mapped[str] = mapped_column(Text, nullable=False)          # SMS/email body
:386      recording_url: Mapped[str | None] = mapped_column(Text, ...)
:387      transcript: Mapped[str | None] = mapped_column(Text, ...)
:321-323  subject / recipient_email / sender_email → String, plaintext
```
Meanwhile `backend/app/models/contact.py:71-82` correctly uses `EncryptedString()` + `LookupHash()` for `email`, `phone_number`, `address_line1/2`.

**This is encryption defeated by denormalization.** The same phone number that is encrypted on `contacts` is written plaintext *and indexed* on `conversations`.

**Attack:** anyone with a DB read primitive — stolen backup (C-3), compromised replica, leaked `DATABASE_URL`, or prod psql access — runs `SELECT contact_phone, body, transcript FROM conversations JOIN messages …` and gets every customer phone number, every SMS/email body, and every AI call transcript in cleartext. `ENCRYPTION_KEY` is irrelevant to this path. Voice transcripts routinely contain names, addresses, gate codes, and card read-back.

**Fix:** convert `body`, `transcript`, `subject`, `recipient_email`, `sender_email`, `last_message_preview` to `EncryptedString()`. Replace `contact_phone`/`workspace_phone` with `EncryptedString()` + a `contact_phone_hash` `LookupHash()` sibling and repoint equality filters/indexes at the hash — the pattern already proven in `contact.py:71-85`. Add the tables to `scripts/ops/reencrypt_with_old_key.py`.

---

### H-2. More plaintext PII the rotation script *believes* is encrypted **[verified by lead]**

**Evidence:**
```python
backend/app/models/opt_out.py:32           phone_number → String(50), indexed   # TCPA suppression list
backend/app/models/lead_magnet_lead.py:47  email → String(255), indexed
backend/app/models/lead_magnet_lead.py:48  phone_number → String(50)
backend/app/models/human_profile.py:46-47  phone_number / email → String        # staff PII
backend/app/models/phone_message.py:81-83,98  caller_name, callback_number, reason, message_body
backend/app/models/caller_memory.py:73     summary: Text                        # AI caller history
backend/app/models/demo_request.py:31      phone_number → String(50)
backend/app/models/link_click.py:28        ip_address → String(64)
```

**This is unintended drift, and the codebase proves it.** `scripts/ops/reencrypt_with_old_key.py:258-268` lists `HumanProfile`, `LeadMagnetLead`, and `LinkClick` as rotation targets with `*_hash` sibling mappings — but those models declare no `*_hash` columns and their fields are plain `String`. At `:149-165` the script hits `InvalidToken`, increments a `skipped_invalid` counter, and continues. **A key rotation reports success while silently leaving this data untouched.**

**Attack:** dump `global_opt_outs` + `lead_magnet_leads` → a clean, deduplicated list of every phone number that explicitly asked not to be contacted, plus every inbound lead's email. The two highest-resale-value tables in the schema, with zero key material needed.

**Fix:** migrate each to `EncryptedString()` + `LookupHash()`. Then make the rotation script **fail loudly**: exit non-zero if a declared target column isn't an `EncryptedString`, or if `skipped_invalid == scanned` for a table.

---

### H-3. `--forwarded-allow-ips=*` makes the client IP attacker-controlled, defeating every IP rate limit **[verified by lead]**

**Evidence:** `backend/railway.toml:9` and `backend/Dockerfile:70-74` both run uvicorn with `--proxy-headers --forwarded-allow-ips=*`.

I read the installed uvicorn to confirm the mechanism — `.venv/lib/python3.12/site-packages/uvicorn/middleware/proxy_headers.py`:
```
:102  self.always_trust: bool = trusted_hosts in ("*", ["*"])
:163  if self.always_trust:
:164      return _parse_host_port(x_forwarded_for_hosts[0])   # leftmost = attacker-supplied
:54   scope["client"] = (host, port)
```
So `request.client.host` is **already rewritten from the attacker's header** before any application code runs. The app-level guard in `backend/app/core/utils.py:28-40` then compares that spoofed value against `trusted_proxies = ["127.0.0.1", "::1"]` (`config.py:297`), the comparison fails, and it returns the spoofed IP verbatim at `:36-37`. The guard is well-written but bypassed one layer upstream.

**Sinks:** `app/api/v1/auth.py:116,165,218` (register/login/refresh), `demo.py:144,222,345`, `lead_form.py:526`, `embed.py:33`, and the `AuthRateLimit.client_ip` / `demo_request.client_ip` audit columns.

**Attack:** send `X-Forwarded-For: 10.<rand>.<rand>.<rand>`, unique per request. Every request lands in a fresh rate-limit bucket, so the 10-per-15-min cap never trips. This enables password spraying, uncapped `/register` and `/refresh` abuse, and uncapped telephony spend via `/demo` — and it poisons forensics, since abuse is attributed to attacker-chosen IPs.

*Partial mitigation:* `UsernameLockoutService` (`username_lockout_service.py:16-54`) caps failures per hashed username independent of IP, so single-account brute force is still throttled. It does not cover register/refresh/demo/lead-form.

**Fix:** set `--forwarded-allow-ips` to Railway's actual edge CIDR instead of `*`. Then delete the now-redundant second XFF parse in `get_client_ip` and trust `request.client.host` only, so proxy trust is configured in exactly one place. Add a global per-endpoint login ceiling as a spray backstop.

---

### H-4. Mac-relay webhook: one global token grants writes into **any** tenant

**Evidence:** `backend/app/api/webhooks/mac_relay.py:41-54` compares a single global `settings.mac_relay_webhook_token` with `secrets.compare_digest` (fail-closed on missing secret at `:44-47` — that part is correct). But tenancy comes entirely from the request body: `mac_relay_handlers.py:29-31` reads `to`/`recipient`, then `:47` calls `_find_workspace_phone`, which at `:119-137` queries `PhoneNumber` with **no workspace filter** and `.limit(1)`.

**Attack:** the token lives on customer-operated Mac daemons, so one compromised relay host yields it for the whole platform. With it, POST `/webhooks/mac-relay/messages` with `{"to": "<victim tenant's number>", "from": "<victim operator's phone>", ...}`. The message is ingested into the victim's workspace. Because `from` is attacker-chosen and `_check_operator` matches on `User.phone_hash` (`telnyx_message_handlers.py:211-224`), `inbound_text.py:141-155` then routes the attacker's text into `process_assistant_message` **as that operator** — or satisfies an approval command via `try_process_command` (`:132-139`).

**Fix:** make the token per-workspace (hashed, stored on the workspace or `PhoneNumber` row); resolve the workspace *from the token*, and scope `_find_workspace_phone` to it. Reject payloads whose `to` doesn't belong to the token's workspace. Don't trust `from` for operator identification on this transport.

---

### H-5. SSRF via user-controlled `website` URL, with response reflected back **[confirmed by adversarial review]**

**Evidence:** sink at `backend/app/services/scraping/website_scraper.py:271` — `await client.get(url)` with `follow_redirects=True` (`:82`), no scheme allowlist and no private-IP block. The normalizer at `:262` only prepends `https://` to bare strings. A repo-wide grep shows `ipaddress`/`is_private` is used only in `app/core/utils.py`, never in the scraper.

Source: `backend/app/api/v1/find_leads_ai.py:189-192` → `enrich_contact_data(website_url=lead.website)`. `lead.website` is a free-form `str | None` (`app/schemas/scraping.py:29`) inside a client-supplied array, **never re-validated** against the Google Places response. Auth is any workspace **member** — `get_workspace` (`deps.py:200-230`) checks membership only, and the scraping rate limit is on `/search` (`find_leads_ai.py:48`) but **not** on `/import`.

Three exfil channels: `<title>`/meta land in `business_intel["website_meta"]` (`enrichment_service.py:65-67`), persisted at `find_leads_ai.py:269` and re-served by `ContactResponse.business_intel` (`app/schemas/contact.py:109`); an LLM summary of the full body lands in `business_intel["website_summary"]`; and raw exception text is echoed in the response `errors[]` (`find_leads_ai.py:209`, `enrichment_service.py:104-106`).

**Attack:** POST `/api/v1/workspaces/{ws}/find-leads-ai/import` with `{"leads":[{…,"website":"http://169.254.169.254/latest/meta-data/iam/security-credentials/"}],"enable_enrichment":true}`, then `GET` the created contact to read the fetched body back.

**Fix:** one egress guard shared by all scraper entry points — reject non-`http(s)`; resolve the host and reject `is_private/is_loopback/is_link_local/is_reserved/is_multicast` plus `metadata.google.internal`; set `follow_redirects=False` or re-validate the resolved IP on every hop (a public host can 302 to `169.254.169.254`, defeating a naive pre-flight check); pin the validated IP in the transport to close DNS rebinding. Stop echoing raw upstream exception strings — log them, return an opaque code.

---

### H-6. Cross-tenant FK grafting on quotes/invoices exfiltrates decrypted customer PII **[confirmed by adversarial review]**

**Evidence:** `backend/app/services/quotes/quote_service.py:466` assigns `contact_id=quote_in.contact_id` straight from the client body (`app/schemas/quote.py:63`) with **no ownership check**; `contact_id` is also in the mass-assign tuple on update (`:547`). Identical defect in `backend/app/services/invoices/invoice_service.py:157` and `:230` — that service never loads a `Contact` at all. `app/models/quote.py:76-77` uses a bare `ForeignKey("contacts.id")` with no composite `(workspace_id, contact_id)` constraint, so Postgres accepts a foreign-tenant ID.

The correct check exists a few lines away: `_resolve_or_create_contact` (`quote_service.py:339-341`) constrains `Contact.workspace_id == workspace_id`.

**Attack:** a member of workspace A with `CanWriteBilling` (`app/api/v1/quotes.py:92`) POSTs a quote with `contact_id` belonging to workspace B — contact IDs are sequential `BigInteger` (`app/models/contact.py:55`), so they're trivially guessable. Then `POST /quotes/{id}/deliver` with `channel="email"` and **no** `to` override: `_load_for_send` (`:606-617`) eager-loads `Quote.contact` scoped only on the Quote, and delivery falls back to `quote.contact.email` (`:670`) / `quote.contact.phone_number` (`:685-687`) — **decrypted** victim PII. The response `QuoteDeliverResult(..., to=email_to)` (`:674`) echoes the resolved destination back, turning a write primitive into a **read** primitive that defeats `EncryptedString` at rest. It also sends workspace A's proposal to workspace B's customer from A's number.

**Fix:** validate every tenant-owned FK on create *and* update, using the pattern `app/services/jobs/job_service.py:62-65` already uses:
```python
if quote_in.contact_id is not None:
    await assert_workspace_owned(
        self.db, Contact, quote_in.contact_id, workspace_id, detail="Contact not found"
    )
```
Repeat for `service_location_id`, `opportunity_id`, and both invoice paths. Add a composite FK/constraint so the database enforces it too.

---

### H-7. Live Telnyx and ngrok credentials in cleartext at the repo root **[verified by lead]**

**Evidence:** `Telnyx API.rtf` and `nGrok AUth.rtf` in the project root.

| file | credential | shape |
|---|---|---|
| `Telnyx API.rtf` | `KEY019ECD4BEA…` (58 ch) | exact Telnyx v2 API key format |
| `nGrok AUth.rtf` | `3FBw2nLz9jID…` (49 ch) | ngrok authtoken |
| `nGrok AUth.rtf` | `3FBw7Li6acw1…` labelled "API Key" | ngrok API key |

All three are full-entropy and live-format — not placeholders. **Good news:** both files are untracked and gitignored (`.gitignore:98 *.rtf`), and `git log --all -- '*.rtf'` is empty, so **no history rewrite is needed**. The Telnyx key is not in `backend/.env` either, meaning this unmanaged note is its *only* home — no rotation schedule, no audit trail.

**Impact if read:** the Telnyx key grants full account API access — send SMS/place calls (direct toll fraud), purchase/release numbers, repoint messaging profiles, and **read historical message and call detail records** (customer PII). The ngrok credentials allow hijacking reserved domains/edges — and combined, an attacker can repoint Telnyx webhooks at an ngrok endpoint they control and intercept live SMS/voice callbacks end-to-end.

**Fix:** rotate all three now (Telnyx portal → API Keys; ngrok → Authtokens and API Keys) — rotate *before* deleting, since deletion doesn't invalidate. Store replacements in Railway service variables and local `.env` only. Then `rm` both files. Review Telnyx usage/billing and message/call detail records from `Jun 15 18:00` forward. Note the current protection is a single `.gitignore` line — a rename or `git add -f` defeats it; add a content-based pre-commit gate.

---

### H-8. Cal.com webhook: unbounded replay window + fail-open dedupe

**Evidence:** `backend/app/core/webhook_security.py:207-216` applies the timestamp window **only if the caller sends** `x-cal-timestamp` — `timestamp = request.headers.get("x-cal-timestamp", ""); if timestamp:`. An attacker replaying a captured body simply omits the header. The signature at `:222` covers the body only (`:157-161`), so a captured `(body, x-cal-signature-256)` pair is **valid forever**.

Compounding it: `backend/app/api/webhooks/calcom.py:80-99` — `_claim_webhook_delivery` is documented *"Fails open on Redis errors"*. And at `:154-164`, if `_build_idempotency_key` returns `None`, the code logs and **proceeds to dispatch**.

**Attack:** replay a captured `BOOKING_RESCHEDULED` body repeatedly. A byte-identical replay is largely contained by the per-row guard (`calcom_handlers.py:362-375`), but the SMS key at `:430-431` varies with the replayed `startTime`, and during any Redis degradation the only cross-delivery barrier disappears — yielding duplicate customer-facing SMS billed to the tenant.

**Fix:** persist the `x-cal-signature-256` value in Postgres (unique index, TTL) and reject any signature seen before — don't depend on an attacker-controlled optional header for staleness. Change `_claim_webhook_delivery` to **fail closed** (503 → Cal.com retries). Reject with 400 when `_build_idempotency_key` returns `None`.

---

## 3. MEDIUM

| # | Issue | Evidence | Fix |
|---|---|---|---|
| M-1 | **`PublicLeadFormCORSMiddleware` prefix gate is a raw `startswith`** on `scope["path"]`, and the OPTIONS preflight is answered with a reflected origin *before* any route gate runs. Credential-stripping at `:250` is good defensive design, but the boundary is order-dependent. | `backend/app/main.py:215`, `:226-234`, `:237-251` | Normalize the path (reject `..`, `%2e`, `//`, `;`) before the prefix test, or better: set these headers inside the `lead_form` handlers that already know the validated origin. *Preflight reflection is confirmed; the traversal reach is reasoned, not executed.* |
| M-2 | **Cal.com attendee→contact resolution is global** — `select(Contact).where(Contact.email == email)` with no workspace scope, plus a `LIKE '%<10 digits>'` suffix match. A forged/replayed booking writes into an arbitrary tenant. | `backend/app/api/webhooks/calcom_parser.py:40-52` | Resolve workspace from `eventTypeId` first (already done at `calcom_handlers.py:104-114`), pass it into both WHERE clauses, and replace the suffix `LIKE` with an exact `hash_phone` match. |
| M-3 | **Toll-fraud amplification on public lead-form/demo.** Unauthenticated POST triggers outbound AI voice calls and SMS; `_notify_new_lead` fans out **one SMS per workspace member**. Only gates are a per-IP DB counter (defeated by H-3) and an `Origin` header (trivially set by curl). | `backend/app/api/v1/lead_form.py:493-527`, `:258-276`; `demo.py:121-177` | Add a per-`public_key` Redis budget and a daily per-workspace outbound spend cap; require CAPTCHA/proof-of-work for `auto_call`/`auto_text`; bound the notify fan-out. |
| M-4 | **`EncryptedString` fails open to plaintext** — on `InvalidToken`, returns the raw column value if it doesn't start with `gAAAAA`. Also no AAD binding, so ciphertext is portable between rows. | `backend/app/core/encryption.py:79-87`, `:117-144` | Remove both plaintext fallbacks; log a `decrypt_failure` metric and raise. Gate legacy rows behind a time-boxed `ALLOW_PLAINTEXT_READ` flag defaulting off. Move to AES-256-GCM with `aad = f"{table}:{column}:{pk}"` and a `v2:` version prefix. |
| M-5 | **Refresh tokens not bound to a session/device.** Lookup is by `token_hash` alone, so an attacker who rotates *first* keeps a valid chain while the victim's reuse triggers `revoke_all` — inverting theft detection into a victim-only DoS. | `backend/app/core/security.py:71-81`, `:126-147` | Add a `session_id` family column; revoke the *family* on reuse. Store `user_agent_hash` + IP prefix and treat mismatch as theft. Add `RefreshToken.user_id` to the lookup predicate at `:136`. |
| M-6 | **Single key serves two primitives; lookup hash is unsalted and cross-tenant.** `ENCRYPTION_KEY` is used raw as the blake2b MAC key *and* as PBKDF2 input; the PBKDF2 salt is `sha256(secret)`, contributing no entropy. Identical phone → identical hash in every workspace, so a DB reader can join tenants. NANP keyspace (~10¹⁰) is invertible in CPU-minutes if the key leaks. | `backend/app/core/encryption.py:29`, `:41`, `:45-52` | Derive two subkeys via HKDF-SHA256 with distinct `info` labels and a real random salt. Include `workspace_id` in the hash input. Store a key-version prefix. |
| M-7 | **No Sentry `before_send` scrubber.** `send_default_pii` is correctly left False, but the Python SDK ships **stack-frame locals** by default — an exception in a serializer or transcript worker sends plaintext phones/bodies/transcripts off-platform. The excellent structlog redactor (`core/logging.py:22-88`) is not wired into Sentry. | `backend/app/main.py:490-498`, `:723`; `frontend/sentry.client.config.ts:7-11` | Add `include_local_variables=False` and a `before_send` reusing `app.core.logging._redact`. Mirror with `beforeSend` in the three frontend configs. |
| M-8 | **DB and Redis connections don't enforce TLS.** No `ssl` param on `create_async_engine`; repo-wide there are zero occurrences of `sslmode`, `ssl=`, or `rediss://`. Aggravated by `Makefile:296`, which instructs operators to back up over the **public internet** via `*.proxy.rlwy.net`. | `backend/app/db/session.py:14-52`; `config.py:20`, `:39` | Append `?ssl=verify-full` to `DATABASE_URL` (or pass a pinned-CA `ssl_context`); add `PGSSLMODE=verify-full` to both backup targets; switch Redis to `rediss://` with `requirepass`. Assert non-TLS URLs are rejected when `environment == "production"`. |
| M-9 | **Invitation lookup is unauthenticated, unthrottled, and returns PII pre-auth** — invitee email, granted role, workspace name/slug, inviter name. Token entropy is strong (`secrets.token_urlsafe(32)`), so this is not brute-forceable; the issue is the missing throttle and the pre-auth disclosure. | `backend/app/api/v1/invitations.py:241-272` | Apply the existing IP limiter; return only `workspace_name` + `is_valid` pre-auth; add `status == "pending"` and `expires_at > now()` to the query so accepted/expired tokens are indistinguishable from bad ones. |
| M-10 | **WebSocket tickets are byte-identical to full API access tokens** (`type: "access"`, differing only by a 1-minute expiry) but travel in a URL query string — exposed to referers, proxy logs, and history. JWTs also lack `aud`/`iss`/`require` constraints. *Algorithm confusion is **not** possible — `algorithms=` is pinned and `secret_key` has no default.* | `backend/app/core/security.py:87-102`; `app/services/auth/websocket_ticket_service.py:36-42` | Mint tickets with `{"type":"ws_ticket","aud":"ws"}`; reject `ws_ticket` at HTTP deps and `access` at the WS handshake. Add `audience`/`issuer` and `options={"require":["exp","sub","type"]}`. |
| M-11 | **Third-party GitHub Actions pinned to mutable tags** — `gitleaks/gitleaks-action@v2`, `peter-evans/create-issue-from-file@v6`, `dorny/paths-filter@v3`, `astral-sh/setup-uv@v7`. The gitleaks job holds `GITHUB_TOKEN` + `pull-requests: write`, so a moved tag could suppress real secret detections while reporting success. *Mitigated:* least-privilege `permissions` everywhere and **no** `pull_request_target`/`workflow_run`, so fork PRs get no secrets. | `.github/workflows/gitleaks.yml:26`, `audit.yml`, `frontend-ci.yml`, `visual-preview.yml` | Pin to full 40-char SHAs with a version comment; enable Dependabot for `github-actions`. |

---

## 4. LOW

- **L-1 · gitleaks path allowlist blind spot.** `.gitleaks.toml:27-32` suppresses **all** detections under `backend/tests/contract/**` and `backend/tests/fixtures/webhooks/**` by *path*. A real webhook signing secret pasted there during debugging commits silently. The same file already does this correctly elsewhere (value-scoped `regexes` at `:36-38`, `:42-44`, with the rationale spelled out at `:41`) — apply that standard consistently.
- **L-2 · Public offer opt-in is unauthenticated and unthrottled.** `backend/app/api/v1/offers.py:418-491` creates contacts with no rate limit, inflating `offer.opt_ins` and auto-creating pipeline cards. *Downgraded from High:* the adversarial review proved the dedup lookups at `:456-466` compare against **Fernet ciphertext**, which is non-deterministic, so they can never match — there is no existence oracle. The residual bugs are CRM spam/pollution, duplicate-contact corruption, and attacker-asserted `sms_consent` on their own new row. Fix by using `email_hash`/`phone_hash` (as `lead_form.py:540` does) and adding the standard limiter.
- **L-3 · Short-link redirector has no destination allowlist.** `backend/app/api/redirects.py:72` redirects to `target_url` unvalidated. *Downgraded from Medium:* `target_url` is authored by authenticated operators in outbound SMS copy (`link_shortener.py:40`, `:58` ← `telnyx.py:268`), not attacker-supplied — so this is domain-reputation laundering, not a classic open redirect. Validate the host at mint time and consider an interstitial for off-domain targets. The 7-char brute-force concern is **dropped** (62⁷ ≈ 3.5×10¹², one marketing URL per guess).
- **L-4 · `get_or_404` defaults to an unscoped primary-key fetch.** `backend/app/api/crud.py:21,49` defaults `workspace_id=None` and then queries by PK with no tenant predicate. *Latent only:* all **69** call sites were enumerated and every one passes `workspace_id`; the 7 exceptions fetch the `Workspace` root itself, which has no `workspace_id` column. Still worth inverting the default — make the kwarg required with an explicit `allow_global=True` opt-out — so a future omission is a `TypeError` instead of a silent leak.

---

## 5. Search-engine discoverability — the site is fully indexable today

### Live evidence (probed against production)

```
GET https://the-tribunal-two.vercel.app/robots.txt   → HTTP 404   (no robots.txt exists)
GET https://the-tribunal-two.vercel.app/login        → HTTP 200   (publicly reachable)
Response headers: strict-transport-security only — no x-robots-tag, no CSP,
                  no x-frame-options, no x-content-type-options, no referrer-policy
```

### Root causes

| Gap | Evidence |
|---|---|
| No `robots.txt` and no `robots.ts` | neither `frontend/public/robots.txt` nor `frontend/src/app/robots.ts` exists — Vercel does **not** generate one |
| No default `robots` directive | `frontend/src/app/layout.tsx:21-31` — root `metadata` sets `title`/`description`/`appleWebApp` but no `robots`, so every route inherits "indexable" |
| Only 3 of ~40 routes opt out | `dev/components/page.tsx:27`, `payment-cancelled/page.tsx:6`, `payment-complete/page.tsx:6`. The entire dashboard plus public surfaces (`offers`, `lead-magnets`, `embed`, `p/*`, `invite`, `sales-wizard`, `christmas-lights`, `login`) are indexable |
| No edge gating | `frontend/src/middleware.ts` does not exist |
| No security headers at all | `frontend/next.config.ts` has **no** `headers()` function; `frontend/vercel.json` sets only framework/build/region |

Backend is fine here: `backend/app/main.py:505-507` disables `/docs`, `/redoc`, `/openapi.json` outside debug — confirmed live (both return 404) — and it already serves a full header set.

### Fix 1 — `frontend/src/app/robots.ts` (new file)

```ts
import type { MetadataRoute } from "next";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: [{ userAgent: "*", disallow: "/" }],
  };
}
```

### Fix 2 — default `noindex` in the root layout

```ts
// frontend/src/app/layout.tsx — add to the existing `metadata` export
export const metadata: Metadata = {
  title: "AI CRM - Unified Customer Communications",
  description: "…",
  robots: { index: false, follow: false, nocache: true },
  appleWebApp: { /* unchanged */ },
};
```

### Fix 3 — `X-Robots-Tag` + the missing security headers in `frontend/next.config.ts`

Add to `nextConfig` (alongside the existing `rewrites`):

```ts
async headers() {
  const security = [
    { key: "X-Robots-Tag", value: "noindex, nofollow, noarchive, nosnippet, noimageindex" },
    { key: "X-Content-Type-Options", value: "nosniff" },
    { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
    { key: "Permissions-Policy", value: "geolocation=(), microphone=(), camera=()" },
    { key: "Strict-Transport-Security", value: "max-age=63072000; includeSubDomains; preload" },
  ];
  return [
    {
      // Dashboard + all app routes: must never be framed.
      source: "/((?!embed).*)",
      headers: [
        ...security,
        { key: "X-Frame-Options", value: "DENY" },
        { key: "Content-Security-Policy", value: "frame-ancestors 'none'" },
      ],
    },
    {
      // Embeddable widget: framed by customer sites by design.
      source: "/embed/:path*",
      headers: [
        ...security,
        { key: "Content-Security-Policy", value: "frame-ancestors https:" },
      ],
    },
  ];
}
```

> **Note the split.** A blanket `X-Frame-Options: DENY` would break the embeddable widget under `frontend/src/app/embed/[publicId]`. The dashboard gets `frame-ancestors 'none'`; the widget route gets a permissive `frame-ancestors` and no `X-Frame-Options`. Tighten `frame-ancestors https:` to the specific customer domains once you have that list.

### Fix 4 — the ordering trap that actually matters

**`robots.txt` alone will NOT remove already-indexed pages.** `Disallow` blocks *crawling*, which means Google can never see a `noindex` and the URL can persist in results as a bare link. Sequence it correctly:

1. Ship the `X-Robots-Tag: noindex` header **first** and leave the pages crawlable for a cycle so crawlers actually observe it.
2. Verify: `curl -sI https://the-tribunal-two.vercel.app/login | grep -i x-robots-tag`.
3. Use Google Search Console → **Removals** for anything already indexed (and Bing Webmaster Tools' equivalent).
4. Only *after* de-indexing is confirmed, add the `Disallow: /` robots.txt as a belt-and-braces measure.

### Fix 5 — stop serving the app to the public entirely (strongest control)

Headers are advisory; crawlers that ignore them, and anyone with the URL, still reach the app. For a private CRM:

- **Vercel Deployment Protection** → set **Standard Protection** (or Password Protection / Trusted IPs) on the project so all preview *and* production deployments require Vercel SSO. Dashboard → Project → Settings → Deployment Protection. This is the single highest-value change and it is a settings toggle, not code.
- Move the app to a real domain and leave `*.vercel.app` off search entirely — the generated hostname is enumerable via certificate-transparency logs regardless of robots directives.
- If public lead-capture surfaces (`/p/*`, `/embed/*`) must stay open, split them onto a separate project/domain from the authenticated dashboard so protection can be applied to the dashboard unconditionally.

---

## 6. Additional deployment hardening

- **`backend/railway.toml:9`** — replace `--forwarded-allow-ips=*` with the Railway edge CIDR (see H-3). Highest-value one-line change in the file.
- **`backend/docker-compose.yml`** — local Postgres/Redis use default `aicrm` credentials with ports published; bind to `127.0.0.1` so a coffee-shop network can't reach your dev DB.
- **Untracked scratch files** — `frontend/debug-place.tmp.mjs` and `frontend/visual-designer.tmp.mjs` are untracked (verified) but sit in the build root. Delete or move them under a gitignored scratch dir.
- **Alembic bypasses the startup key guard.** `railway.toml:5` runs `alembic upgrade head` as a pre-deploy step; that process never imports `app.main`, so `_validate_security_key` (see §7) doesn't run. Add the same assertion to `alembic/env.py`, and confirm no historical deploy ran with `ENCRYPTION_KEY` unset — migration `c4d5e6f7a8b9_encrypt_integration_credentials.py` would have encrypted tenant credentials under a key derived from the public default string.
- **No data-retention or right-to-erasure implementation.** A repo-wide grep for `gdpr|retention_days|anonymize|erase_contact` returns zero matches, and there is no recording-retention setting. Combined with H-1, call recordings and transcripts accumulate indefinitely in plaintext with no deletion path, and a verified DSAR erasure request cannot be satisfied. Add a `POST /contacts/{id}/erase` service plus `recording_retention_days`/`transcript_retention_days` settings and a purge worker.
- **Argon2 cost is unpinned.** `backend/app/core/security.py:17` — `argon2.PasswordHasher()` with no explicit parameters. Current defaults are fine, but a dependency downgrade silently weakens every new hash with no CI signal. Pin `time_cost=3, memory_cost=65536, parallelism=4, hash_len=32, salt_len=16` and assert them in a unit test.

---

## 7. Verified working — don't regress these

These were actively probed and found correct.

**Authentication & session**
- Argon2id with transparent bcrypt→Argon2 upgrade on login (`core/security.py:20-46`).
- Auth cookies `httponly=True`, `samesite="lax"`, `secure` defaulting True outside dev/test (`services/auth/cookie_service.py:20-53`, `config.py:249-253`); refresh cookie path-scoped to `/api/v1/auth`. **No JWT in localStorage** — verified `frontend/src/providers/auth-provider.tsx:63,98` and grep of `frontend/src/lib`.
- No account enumeration: unknown user, wrong password, and lockout all return an identical 401 (`api/v1/auth.py:171-181`).
- Per-username lockout keyed on a SHA-256 of the lowercased address, independent of IP — the control that survives H-3 (`username_lockout_service.py:16-64`).
- JWT `algorithms=` pinned to one symmetric alg; `secret_key` is `Field(..., min_length=32)` with **no default**; `verify_signature` is never disabled anywhere. No algorithm-confusion path.
- Password change revokes all refresh tokens (`password_change_service.py:48-61`); refresh path re-checks `is_active`.

**Multi-tenancy**
- 502 route handlers AST-enumerated: **zero** routes take a `workspace_id` path param without a membership check (some resolve it imperatively in the body — inconsistent style, not a bypass). The 43 no-auth routes are all intentional.
- API keys are SHA-256 hashed, returned once, checked for `is_active` + `expires_at`, and **bound to their issuing workspace** — `_enforce_api_key_workspace` (`deps.py:156-168`) runs before the membership check in all three resolution paths.
- Cross-workspace reads return **404, not 403** (`db/scope.py:118-136`), so object existence doesn't leak.
- `owner` is not an assignable role (`core/roles.py:53-60`); role→tier mapping fails closed to the lowest tier.
- Contact attachments are triple-scoped on `attachment_id` + `contact_id` + `workspace_id`, with an inline-safe content-type allowlist that excludes HTML/SVG/XML, forced `Content-Disposition: attachment`, `nosniff`, and a capped read (`await file.read(MAX + 1)`) (`api/v1/contact_attachments.py:36-215`).

**Webhooks** — all five surfaces verify signatures **before** any side effect and are **fail-closed** on a missing secret:

| Handler | Mechanism | Raw body | Replay window | Missing secret |
|---|---|---|---|---|
| Telnyx | Ed25519, timestamp inside signed blob | ✅ | ✅ ±300s | 503 |
| Cal.com | `hmac.compare_digest` | ✅ | ⚠️ optional-only (H-8) | 503 |
| Resend | svix | ✅ | ✅ | 503 |
| Stripe | `stripe.Webhook.construct_event` | ✅ | ✅ | 503 |
| Mac relay | `secrets.compare_digest` | n/a | ❌ (H-4) | 503 |

`skip_webhook_verification` defaults False and logs a `severity="high"` warning if enabled outside debug.

**Other**
- Startup **refuses to boot** on a weak `SECRET_KEY`/`ENCRYPTION_KEY`: rejects the literal `change-me-in-production`, `< 32` bytes, **and** `< 128` bits of Shannon entropy — catching long-but-trivial values like `"a"*64`. Enforced on both the API (`main.py:441`) and worker (`workers/runner.py:50`) entry points.
- Backend security headers verified live: CSP (no `unsafe-eval`), HSTS, `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy`, `Permissions-Policy`.
- `/docs`, `/redoc`, `/openapi.json` return **404 in production** (verified live).
- App-wide CORS is exact-match with no regex/suffix matching; `_ALLOWED_REQUEST_HEADERS` correctly omits `Authorization`. Origin wildcard matching in `origin_validation.py:30-44` is implemented correctly — `evilexample.com` does not match `*.example.com`.
- `/metrics` is gated by a constant-time bearer check and **fails closed with 503** when unset.
- **No SQL injection.** Every `text()` use is either a static index predicate, `SELECT 1`, or parameterized. The JSON filter engine resolves user field names through a `column_map` lookup, so untrusted strings never become SQL identifiers.
- **No XSS primitives in the frontend** — zero `dangerouslySetInnerHTML`, `eval`, or `new Function` in `frontend/src` (the only matches are comments explaining their deliberate avoidance).
- **Pagination is bounded everywhere** (`le=100`/`le=500`); there is **no CSV/JSON export endpoint** — the only CSV routes are imports.
- **Git history is clean** — 770 commits across 11 branches, no `.env`/`.pem`/`.key`/dump ever added, and zero real matches for `sk_live_`, `SG.`, `AKIA`, `AIza`, `ghp_`, or `BEGIN PRIVATE KEY`. CI values are verified placeholders.
- **No frontend secret leakage** — only `NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_PLAN_PRICE`, `NEXT_PUBLIC_SENTRY_DSN` (public by design). The widget embeds no keys. The `pk_live_…` analytics key is a *publishable* browser key.
- `backend/static/` contains exactly two marketing PDFs; no upload code writes there. `backend/Dockerfile` runs as non-root `USER app` with narrow `COPY` directives and a `.dockerignore` excluding `.env`.
- Integration credentials (Telnyx/Cal.com/Stripe/Resend/OpenAI per-tenant keys) **are** Fernet-encrypted, and the migration drops the plaintext column in the same transaction. No PAN/CVV anywhere — Stripe tokens only.

---

## 8. Dismissed — do not re-file

| Claim | Verdict |
|---|---|
| `encryption_key: str = "change-me-in-production"` default (`config.py:48`) is exploitable | **False positive.** `_validate_security_key` (`main.py:287-345`) rejects that exact literal plus low-entropy values, and is invoked for `ENCRYPTION_KEY` at `main.py:386` via `_validate_startup_config()` at `:441`. Verified by hand. *(The alembic path is a separate gap — see §6.)* |
| `workspace_id=str(offer.workspace_id)` (`offers.py:483`) orphans rows from workspace-scoped queries | **False positive.** Empirically tested on this exact stack (SQLAlchemy 2.0.49 + asyncpg 0.31.0): the value round-trips as a `UUID` and `WHERE ws = <uuid>` matches. Style inconsistency only. |
| Public offer opt-in is an existence oracle for other tenants' contacts | **Overstated → L-2.** The lookups compare against non-deterministic Fernet ciphertext, so they never match; there is no oracle. |
| `/r/{code}` is an open redirect, brute-forceable | **Overstated → L-3.** `target_url` is operator-authored, not attacker-supplied. Brute-force half dropped. |
| `get_or_404` fail-open is a live cross-tenant leak | **Overstated → L-4.** All 69 call sites pass `workspace_id`. Latent footgun. |
| `get_client_ip` is not spoofable | **Wrong — this was a false *negative*.** One auditor cleared it by reading only `core/utils.py`. The spoof happens one layer up in uvicorn. See H-3. |

---

## 9. Suggested fix order

**Today (hours):**
1. **C-1** — add ticket auth to the voice-bridge WS. Live audio hijack.
2. **C-2** — two-line workspace scope fix on `phone_numbers.py`.
3. **C-3** — shred the three prod dumps, rotate the DB credential.
4. **H-7** — rotate the Telnyx + ngrok credentials, delete the RTF files.
5. **H-3** — one-line `railway.toml` change.
6. **§5 Fix 5** — flip on Vercel Deployment Protection.

**This week:**
7. **§5 Fixes 1-4** — robots/noindex/headers, in the stated order.
8. **H-6** — reuse the existing `assert_workspace_owned` pattern on quotes/invoices.
9. **H-5** — one shared SSRF egress guard.
10. **H-4** — per-workspace mac-relay tokens.

**Next sprint:**
11. **H-1 + H-2** — the encryption migration; share one rotation window, and fix the rotation script to fail loudly.
12. **H-8, M-1 → M-11**, then the §6 hardening items and the L-series.

---

### Coverage gaps in this audit

Stated plainly so they don't read as clean:

- **AI/LLM prompt-injection paths are the largest unaudited area.** Tool executors were confirmed to derive `workspace_id` from server-side state (not model output), which is the right design — but `app/services/ai/crm_assistant/`, `roleplay/`, `prompt_builder.py`, and the inbound SMS/transcript prompt-assembly path were not read. Recommend a dedicated pass.
- `call_supervisor.py:227-293` — the handshake authenticates, but whether `live_call` re-checks that `call_id` belongs to the authenticated workspace is unverified.
- `core/circuit_breakers.py` was not read.
- Public routers `/p/quotes`, `/p/compare`, `/p/offers`, `/p/reviews` were enumerated but their handlers not read — they sit under the same prefix as M-1.
- Backend dependency CVE scan did not complete (`npm audit` for the frontend also failed to run in this environment). Run `uv pip list --outdated` and `npm audit --omit=dev` in CI.
- No finding was validated against a running instance; this was static analysis plus live header probes. C-1, C-2, H-5, and H-6 warrant a PoC before remediation sign-off.
