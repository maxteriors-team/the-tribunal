---
title: Setup, Settings, Integrations, Team, and Billing
slug: settings-billing-onboarding
tags:
  - onboarding
  - setup
  - settings
  - integrations
  - team
  - billing
  - permissions
---

# Setup, Settings, Integrations, Team, and Billing

## Finish workspace setup

Route: `/onboarding`. Sidebar reminder label: **Finish setup**.

Follow the guided setup to configure the workspace profile, connect the supported CRM and calendar services, import leads, prepare agents and sending resources, and launch the first workflow. Owners and admins can return to `/onboarding`; field users are not forced into owner-only setup. Completing an item should be verified by the status shown in the setup wizard.

## Find a Settings tab

Route: `/settings`. Sidebar label: **Settings**.

Settings contains these route-addressable tabs:

- **Profile**: `/settings?tab=profile` — account and workspace profile preferences.
- **Tags**: `/settings?tab=tags` — create, edit, and organize contact tags.
- **Notifications**: `/settings?tab=notifications` — choose supported notification preferences.
- **Nudges**: `/settings?tab=nudges` — configure relationship-reminder behavior.
- **Reviews**: `/settings?tab=reviews` — configure review-request links and behavior.
- **Proposals**: `/settings?tab=proposals` — configure proposal content and defaults.
- **Pricing**: `/settings?tab=pricing` — configure financing, add-on ranks, permanent lighting, and seasonal pricing.
- **Attach Rules**: `/settings?tab=attach-rules` — define which add-ons attach to service categories.
- **Sales Targets**: `/settings?tab=sales-targets` — set targets used by sales reporting.
- **Pipeline**: `/settings?tab=pipeline` — manage opportunity pipelines and stages.
- **Speed to Lead**: `/settings?tab=speed-to-lead` — configure lead-response behavior.
- **Estimate Follow-up**: `/settings?tab=estimate-followup` — configure quote follow-up rules.
- **Quote Revival**: `/settings?tab=quote-revival` — configure old-quote revival behavior.
- **Neighbors**: `/settings?tab=neighbors` — configure neighbor outreach.
- **My Calendar**: `/settings?tab=calendar` — connect your own Google account so the AI checks your busy times and creates your assigned appointments there.
- **Integrations**: `/settings?tab=integrations` — connect and configure workspace-wide providers and phone resources.
- **Billing**: `/settings?tab=billing` — view workspace billing settings.
- **Team**: `/settings?tab=team` — invite members and manage roles.
- **Locations**: `/settings?tab=locations` — manage operating locations.
- **Lead Sources**: `/settings?tab=lead-sources` — manage lead-attribution source labels.

Select the visible tab by its UI label. Saving a setting affects future behavior unless the page explicitly says it backfills existing records.

## Connect your Google Calendar

1. Open **Settings → My Calendar** at `/settings?tab=calendar`.
2. Select **Connect Google Calendar** and authorize the Google account where your own meetings belong.
3. Each sales rep repeats this with their own login; never share one Google refresh token across the team.
4. Owners, admins, managers, and dispatchers can view all rep appointments on the CRM calendar; lower roles see only their assigned appointments.

## Connect a workspace integration

1. Open **Settings → Integrations** at `/settings?tab=integrations`.
2. Find the provider and select **Connect** or **Configure**.
3. Enter the requested credentials or complete the provider authorization flow.
4. Save, then verify that the integration card says **Connected**.

Do not paste credentials into Assistant chat. Integration availability depends on the deployment and workspace.

## Manage the team

1. Open **Settings → Team** at `/settings?tab=team`.
2. Select **Invite Member**, enter the invitee's details, and choose the intended role.
3. Send the invite, then confirm the member appears with the correct role.
4. Select **Edit** beside a member to change only the role or state controls that are available.

Roles control visible navigation and API access. Use the least-privileged role that supports the person's work.

## Open Billing

Route: `/billing`. Sidebar label: **Billing**.

Use Billing to view the workspace plan, subscription status, usage, and available plan-management controls. This is workspace subscription billing, not customer invoicing. To create a customer invoice, use **Invoices** at `/invoices`.
