# Email Sending — Domain Setup (maxteriorslighting.com)

Recall doc for sending email from **maxteriorslighting.com** via Resend.
Everything here is **non-secret**. The actual API tokens live in Railway env vars
and Resend/Cloudflare dashboards — never in this repo (gitleaks will block them).

## Summary

Transactional + campaign email sends from a verified **subdomain** so the main
website DNS and any inbound mail on the root domain stay untouched.

| Thing | Value |
|---|---|
| Website domain | `maxteriorslighting.com` |
| DNS provider | **Cloudflare** (nameservers `aiden.ns.cloudflare.com` / `ingrid.ns.cloudflare.com`) |
| Registrar | Network Solutions |
| Website host | Vultr (WordPress) |
| Sending domain (Resend) | `send.maxteriorslighting.com` |
| Resend domain ID | `c8b678a7-ac5f-4234-bb46-1abb2aca30df` |
| Resend region | `us-east-1` |
| Cloudflare Zone ID | `fdb483223fd40d703d3e659bee68bd0f` |
| From address | `hello@send.maxteriorslighting.com` |
| Status | ✅ Verified + test email delivered to a real inbox |

## Env vars (Railway → `the-tribunal-api` service)

| Var | Purpose | Secret? |
|---|---|---|
| `RESEND_API_KEY` | Send-only key used by the app at runtime | yes |
| `RESEND_FROM_EMAIL` | `hello@send.maxteriorslighting.com` | no |
| `RESEND_FROM_NAME` | `Maxteriors Lighting` (display name) | no |
| `CLOUDFLARE_DNS_TOKEN` | Edit-zone-DNS token for automating future record adds | yes |

> The app's runtime `RESEND_API_KEY` is **send-only**. Registering/verifying a new
> domain needs a **full-access** Resend key — create a temporary one in the Resend
> dashboard, use it, then delete it. Do not store a full-access key long-term.

## DNS records (already added in Cloudflare)

All three are on the `send.` subdomain. Cloudflare auto-appends the zone name, so
the "Name" column is what you type into the Cloudflare UI (no trailing domain).

| Record | Type | Name | Value | Priority |
|---|---|---|---|---|
| DKIM | `TXT` | `resend._domainkey.send` | `p=MIGfMA0GCSqG...` (from Resend domain page) | — |
| SPF  | `MX`  | `send.send` | `feedback-smtp.us-east-1.amazonses.com` | `10` |
| SPF  | `TXT` | `send.send` | `v=spf1 include:amazonses.com ~all` | — |

> `send.send` is **correct**, not a typo — it's the `send.` host under the
> `send.maxteriorslighting.com` sending domain.

## How to re-run this for a new domain

1. **Register** the sending domain in Resend (full-access key):
   `POST https://api.resend.com/domains {"name":"send.<domain>","region":"us-east-1"}`
2. **Read the records** from the response (`records[]`) — DKIM value is unique per domain.
3. **Add records** in Cloudflare via API using `CLOUDFLARE_DNS_TOKEN`:
   `POST https://api.cloudflare.com/client/v4/zones/<ZONE_ID>/dns_records`
   - The token must belong to the **same Cloudflare account** that holds the zone.
     If `GET /zones` returns 0 results, the token is in the wrong account.
4. **Verify**: `POST https://api.resend.com/domains/<DOMAIN_ID>/verify`, then poll
   `GET /domains/<DOMAIN_ID>` until `status: verified` (SES can take a few minutes).
5. **Point the app**: set `RESEND_FROM_EMAIL=hello@send.<domain>` in Railway.

## Verify a send worked

```
# status of a specific message
GET https://api.resend.com/emails/<MESSAGE_ID>   ->  last_event: delivered
```

## Gotchas hit during setup

- **Bluehost / WordPress / registrar panels are dead ends** for DNS. Only the
  authoritative nameservers (Cloudflare) matter. `dig +short NS <domain>` is truth.
- **Wrong Cloudflare account**: a token that authenticates but sees 0 zones/accounts
  is scoped to a different account than the one holding the domain.
- **Token start/expire dates**: leaving a future "Start Date" makes a valid token
  return `9109 invalid access token` until that date. Leave TTL dates blank.
- **Root domain has its own MX** — do not touch it. Sending records live on `send.`.
