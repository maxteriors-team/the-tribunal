---
title: Calendar, Jobs, Add-ons, Service Plans, Inventory, and Price Book
slug: operations-service-delivery
tags:
  - calendar
  - appointments
  - jobs
  - scoreboard
  - lighting league
  - upsell
  - service plans
  - inventory
  - price book
---

# Calendar, Jobs, Add-ons, Service Plans, Inventory, and Price Book

## Schedule appointments in Calendar

Route: `/calendar`. Sidebar label: **Calendar**.

Use Calendar to view scheduled appointments and create or update an appointment. Choose the contact, date and time, duration, assigned user when available, and notes; then save. Open an existing appointment to review its details or use the available reschedule or cancellation controls. Calendar availability can depend on the workspace's configured calendar integration.

## Dispatch and complete Jobs

Route: `/jobs`. Sidebar label: **Jobs**.

1. Open **Jobs**. Dispatchers can select **New Job**; field roles see assigned work.
2. Enter the customer, title, schedule, status, assigned technicians, and supported job details.
3. Use the weekly board to open a job or work from the **Unscheduled** queue.
4. Use **My jobs** to show work assigned to you. Dispatch roles can use the location and status filters.
5. Open a job to update its schedule, assignment, notes, and progress when your role permits it.

A field technician may have a read-only or operational subset of the job controls. Dispatch changes should be made on `/jobs`, not inferred from a calendar card alone.

## Review Lighting League progress

Route: `/scoreboard`. Sidebar label: **Lighting League**.

Active technicians can compare current-month rank, XP, and lifetime lighting levels. Technicians see only their own attendance, completed-job, and approved-upsell breakdown; authorized office roles can open those private details for any technician. Monthly standings reset, while lifetime levels remain. Lighting League is recognition only—not payroll, prizes, discipline, or a performance review.

## Sell an add-on on site

Route: `/upsell`. Sidebar label: **Sell add-on**.

1. Pick the job you are on.
2. Select Price Book add-ons, adjust quantities, and optionally add custom work or an eligible care plan.
3. Select **Build proposal** and review the frozen proposal total.
4. Select **Share proposal** to present it on the device or send the supported approval link.

Only roles with add-on selling capability can use this workflow. If a proposal exceeds the configured limit, ask the office to send it rather than promising the customer it was approved.

## Manage Service Plans

Route: `/service-plans`. Sidebar label: **Service Plans**.

Use this screen to review customer service plans and their active, paused, or other supported states. Create a plan for a contact using the available service, frequency, interval, pricing, and schedule fields. Open a plan to apply only the state changes or service actions offered by the current record.

## Maintain the Price Book

Route: `/catalog`. Sidebar label: **Price Book**.

1. Select **New item**.
2. Enter the item name, type, optional code/SKU, unit price, tax behavior, service category, and active state.
3. Mark an item as attachable and choose **Attaches to** categories when it should be suggested as an add-on.
4. Select **Add item**. Use the row menu to **Edit** or **Delete** an existing item.

Price Book items can autofill quotes and invoices. Pricing and proposal rules also live under **Settings → Pricing**, **Settings → Attach Rules**, and **Settings → Proposals**.

## Track Inventory

Route: `/inventory`. Sidebar label: **Inventory**.

1. Select **Track item** and enter the item name, SKU, unit, reorder point and quantity, safety stock, lead time, supplier details, and notes.
2. Receive a delivery with the item's **Receive stock** action so the receipt updates on-hand quantity and cost.
3. Use **Adjust stock** for a counted correction and record its reason.
4. Review low-stock and reorder information before placing an order.
5. Edit an item to change its tracking settings or mark it inactive while preserving report history.

Stock quantities are changed through receipts and adjustments, not by editing the item's starting form.
