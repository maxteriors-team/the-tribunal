---
title: CRM Screen and Route Reference
slug: screen-route-reference
tags:
  - routes
  - screens
  - navigation
  - sidebar
---

# CRM Screen and Route Reference

Use these exact labels and routes in product instructions. A screen can be hidden when the signed-in role lacks its capability.

## Work

| UI label | Route | Purpose |
| --- | --- | --- |
| Today | `/today` | Prioritized daily action queue and briefing |
| Dashboard | `/dashboard` | Workspace activity and performance overview |
| Assistant | `/assistant` | Conversational CRM queries, actions, and product help |
| Nudges | `/nudges` | Relationship reminders and follow-up prompts |
| Pending Actions | `/pending-actions` | Approve, reject, or edit held outbound actions |

## CRM

| UI label | Route | Purpose |
| --- | --- | --- |
| Contacts | `/contacts` | Search, add, import, export, filter, and bulk-manage contacts |
| Segments | `/segments` | Create and manage reusable contact audiences |
| Calls | `/calls` | Start and review voice calls |

Contact overview uses `/contacts/{contact_id}` and the full details screen uses `/contacts/{contact_id}/details`.

## Outreach

| UI label | Route | Purpose |
| --- | --- | --- |
| Campaigns | `/campaigns` | Manage SMS, voice, email, and supported pre-booking campaigns |
| AI Agents | `/agents` | Create and configure conversational agents |
| Practice / Roleplay | `/agents/practice` | Run scored roleplay sessions |
| Knowledge Base | `/knowledge` | Manage agent knowledge documents |
| AI Suggestions | `/suggestions` | Review proposed prompt improvements |
| Automations | `/automations` | Build event, condition, and schedule workflows |
| Experiments | `/experiments` | Compare supported agent or prompt variants |

Campaign creation routes are `/campaigns/new`, `/campaigns/sms/new`, `/campaigns/voice/new`, `/campaigns/email/new`, and `/campaigns/pre-booking/new`; campaign detail uses `/campaigns/{campaign_id}`. Agent creation uses `/agents/create`; agent detail uses `/agents/{agent_id}`. Experiment creation uses `/experiments/new`; experiment detail uses `/experiments/{experiment_id}`.

## Lead Generation

| UI label | Route | Purpose |
| --- | --- | --- |
| Find Leads | `/find-leads` | Search for businesses and import selected results |
| Find Leads AI | `/find-leads-ai` | Enrich and score business leads before import |
| Ad Library | `/find-leads/ad-library` | Research competitor ads and saved monitors |
| People Search | `/find-leads/people` | Find people by available profile criteria |
| Offers | `/offers` | Build and publish offers |
| Reviews | `/reviews` | Monitor reviews and send eligible requests |
| Referral Partners | `/referral-partners` | Manage partners and attributed referrals |
| Lead Magnets | `/lead-magnets` | Manage lead-capture resources |

Offer creation uses `/offers/new`; offer detail uses `/offers/{offer_id}`. Referral detail uses `/referral-partners/{partner_id}`. Lead-magnet creation uses `/lead-magnets/new`.

## Sales

| UI label | Route | Purpose |
| --- | --- | --- |
| Opportunities | `/opportunities` | Manage the pipeline board |
| Quotes & Estimates | `/quotes` | Create, send, and track proposals |
| Quote Builder | `/sales-wizard` | Guided quote-building workflow |
| Landscape Lighting | `/landscape-lighting` | Manage synced customer lighting projects and designs |
| Christmas Light Estimator | `/christmas-lights` | Build a seasonal lighting estimate |
| Invoices | `/invoices` | Create, send, track, and manage invoices |

A landscape-lighting project uses `/landscape-lighting/{project_id}`. Quotes and invoices are created and edited in controls on their list screens, not on separate new/edit routes.

## Operations

| UI label | Route | Purpose |
| --- | --- | --- |
| Calendar | `/calendar` | Schedule and review appointments |
| Jobs | `/jobs` | Dispatch and work scheduled or unscheduled jobs |
| Sell add-on | `/upsell` | Build and share on-site add-on proposals |
| Service Plans | `/service-plans` | Create and manage recurring customer plans |
| Inventory | `/inventory` | Track stock, receipts, adjustments, and reorder needs |
| Price Book | `/catalog` | Manage reusable service and product line items |

## Insights

| UI label | Route | Purpose |
| --- | --- | --- |
| Scorecard | `/scorecard` | AI receptionist demand and booking scorecard |
| Reports | `/reports` | Workspace and campaign reporting |
| Sales Performance | `/reports/sales` | Revenue, quote, close-rate, and attribution reporting |

## Account and setup

| UI label | Route | Purpose |
| --- | --- | --- |
| Phone Numbers | `/phone-numbers` | Provision and configure communications numbers |
| Billing | `/billing` | Workspace plan, subscription, and usage |
| Settings | `/settings` | Profile, workflow, integration, team, and workspace configuration |
| Finish setup | `/onboarding` | Guided workspace setup; shown while setup is incomplete |

## Other application and customer routes

These customer routes require a valid public token or slug and do not expose the CRM shell:

- Quote or proposal: `/p/quotes/{token}`
- Quote comparison: `/p/compare/{token}`
- Invoice: `/p/invoices/{token}`
- Offer: `/p/offers/{slug}`
- Review request: `/p/reviews/{token}`
- Public landing page: `/p/landing`
- Embedded agent: `/embed/{public_id}`, `/embed/{public_id}/chat`, `/embed/{public_id}/both`, or `/embed/{public_id}/fullpage`

The standalone estimator is `/estimator`. Authentication and invite routes are `/login`, `/register`, and `/invite/{token}`. Hosted payment returns use `/payment-complete` and `/payment-cancelled`. These are not signed-in CRM workflow destinations unless the question is specifically about that flow.
