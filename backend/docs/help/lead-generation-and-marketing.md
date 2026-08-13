---
title: Lead Generation, Offers, Reviews, Referrals, and Lead Magnets
slug: lead-generation-marketing
tags:
  - find leads
  - ads
  - people search
  - offers
  - reviews
  - referrals
  - lead magnets
---

# Lead Generation, Offers, Reviews, Referrals, and Lead Magnets

## Find local business leads

Route: `/find-leads`. Sidebar label: **Find Leads**.

1. Enter a business type and location, such as `plumbers in Austin TX`.
2. Search, then filter the results.
3. Select the businesses you want.
4. Choose the contact status under **Import as** and select **Import Leads**.
5. Review the import summary for imported, duplicate, missing-phone, or failed rows.

Route: `/find-leads-ai`. Sidebar label: **Find Leads AI**. This workflow adds website and social-profile enrichment, an **AI Enrichment** toggle, quality filtering, and selectable result limits before import.

## Research advertising and people

Route: `/find-leads/ad-library`. Sidebar label: **Ad Library**.

1. Search by **Keyword** or **Or a specific page**.
2. Choose Meta Ad Library or Google Ads Transparency and a two-letter country.
3. Optionally use Long-runner, Low creative diversity, and No testing filters.
4. Select **Search ad library** and review the returned advertiser opportunities.
5. Use **Saved monitors** to re-scan a named keyword on a schedule.

Route: `/find-leads/people`. Sidebar label: **People Search**. Search using the available person, company, location, or profile criteria; review results before importing any supported records.

## Create and publish Offers

Route: `/offers`. Sidebar label: **Offers**.

1. Open **Offers** and start a new offer at `/offers/new`.
2. Complete the available offer fields and save it.
3. Open `/offers/{offer_id}` to review or change the saved offer.
4. Publish only when its customer-facing content and settings are ready.

A published customer offer uses `/p/offers/{slug}`. Do not claim a draft is public until its state and public link confirm it.

## Request and monitor Reviews

Route: `/reviews`. Sidebar label: **Reviews**.

Use **Reviews** to monitor received reviews and send eligible review requests. Configure review links and behavior under **Settings → Reviews** at `/settings?tab=reviews`. A customer's tokenized review page uses `/p/reviews/{token}`.

## Manage Referral Partners

Route: `/referral-partners`. Sidebar label: **Referral Partners**.

1. Add a partner and its company/contact details.
2. Track partner activity and referrals from the partner list.
3. Select a partner to open `/referral-partners/{partner_id}` and review its details and related performance.

## Create Lead Magnets

Route: `/lead-magnets`. Sidebar label: **Lead Magnets**.

Open **Lead Magnets** to manage the workspace's resources. Start a new one at `/lead-magnets/new`, complete the available content and capture settings, and save it. Lead magnets can be attached where the Offer workflow offers that selection. Do not describe a private workspace resource as publicly available unless the screen provides a public link.
