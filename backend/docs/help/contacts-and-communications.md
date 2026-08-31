---
title: Contacts, Messages, Segments, and Calls
slug: contacts-communications
tags:
  - contacts
  - leads
  - segments
  - messages
  - calls
  - import
---

# Contacts, Messages, Segments, and Calls

## Find and filter contacts

Route: `/contacts`. Sidebar label: **Contacts**.

1. Open **Contacts**.
2. Search by contact details or use the status, source, campaign, tag, and date filters.
3. Select a row to open its conversation at `/contacts/{contact_id}`.
4. Use **Contact details** to open `/contacts/{contact_id}/details`, where you can review activity, update fields and tags, or start an available message or call action.

Filters can also be opened from a shared URL using `/contacts?filters=...`. Available records and actions depend on the signed-in user's workspace and role.

## Add, import, export, and bulk-update contacts

- Select **Add Contact** on `/contacts`, enter the required name and phone details, then save.
- Select **Import** to upload a CSV, map its columns, validate the preview, and complete the import. Duplicate or invalid rows are reported rather than silently replacing records.
- Select **Export CSV** to download the contacts currently allowed by your role.
- Select contact checkboxes to reveal bulk actions such as status changes, tags, assignment, adding to a campaign, or deletion. Read the confirmation before applying an action to many records.

## Build reusable Segments

Route: `/segments`. Sidebar label: **Segments**.

1. Open **Segments**.
2. Select **New Segment**.
3. Name the segment and define its contact rules.
4. Save it, then use the segment anywhere the CRM offers segment-based campaign or audience selection.

Segments are saved dynamic audiences; contact filters are temporary until saved as a segment.

## Message a contact

A contact's conversation route is `/contacts/{contact_id}`.

1. Open **Contacts** and select the contact.
2. Read the conversation history in context.
3. Write the reply in the message composer and send it when messaging is available.
4. Select **Contact details** when you need profile, tags, or broader activity context.

If sending is unavailable, verify that an SMS-capable number is configured under **Phone Numbers** at `/phone-numbers` and that the contact has not opted out.

## Browse past conversations

Route: `/messages`. Sidebar label: **Messages**.

Every text and email conversation with your customers, newest first, going back as far as the workspace has history. Use this when you need an old thread and do not already know whose it is; the header chat menu only lists the most recent threads, and a contact's own route requires knowing the contact first.

1. Open **Messages**.
2. Search by contact name, or filter by channel (SMS or email) and status.
3. Select **View** on a row to read that conversation, and load older messages to page further back.

Search matches contact names only. Message text is encrypted at rest and cannot be searched, so an old thread is found by the person rather than by something they said. Reading a conversation here does not mark it as read.

## Place and review calls

Route: `/calls`. Sidebar label: **Calls**.

- Review current and historical call records, outcomes, transcripts, recordings when available, and active calls.
- To start an outbound call, use **Call Contact** from Calls or a contact record, choose **AI agent** for an automated call or **My phone** to ring yourself first and then connect the contact, and confirm the caller number.
- Active calls can be ended from the live-calls panel after confirmation.

Calls require a voice-capable number and the appropriate communications role. Never promise that a call was placed until the CRM shows the call result.
