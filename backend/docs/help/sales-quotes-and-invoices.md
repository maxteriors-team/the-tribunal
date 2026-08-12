---
title: Opportunities, Quotes, Estimates, and Invoices
slug: sales-quotes-invoices
tags:
  - opportunities
  - pipeline
  - quotes
  - estimates
  - invoices
  - payments
  - quote builder
  - lighting
---

# Opportunities, Quotes, Estimates, and Invoices

## Work the Opportunities pipeline

Route: `/opportunities`. Sidebar label: **Opportunities**.

1. Open **Opportunities** and choose the pipeline you want to view.
2. Select **New Opportunity** to connect a contact, value, and pipeline stage.
3. Move an opportunity through stages as work progresses, or open its detail dialog to edit it.
4. Use **Configure Pipelines** for pipeline administration, or open **Settings → Pipeline** at `/settings?tab=pipeline`.

A stage change updates the CRM record. It does not send a customer message unless an enabled automation separately handles that event.

## Create and send a quote or estimate

Route: `/quotes`. Sidebar label: **Quotes & Estimates**.

1. Open **Quotes & Estimates** and select **New quote**. The CRM opens **Quote Builder** at `/sales-wizard`.
2. Build the quote in the guided wizard, review the priced lines and proposal, and save it.
3. Return to `/quotes` and open the quote's **Actions** menu.
4. Use **Email proposal to client** or **Text proposal to client** to deliver the customer proposal. Either action can send a draft and create its client link.
5. Use **Preview client proposal** for a staff preview or **Copy client link** when those actions are available. The customer route is `/p/quotes/{token}`.

The row menu can also offer **Assign owner**, **Edit quote**, **Add services**, **Mark as sent**, **Re-send email**, **Approve**, **Decline**, **Convert to job & invoice**, and **Delete quote** according to status. Quote editing happens in a dialog on `/quotes`; there is no separate edit route.

## Use Quote Builder and lighting estimators

Route: `/sales-wizard`. Sidebar label: **Quote Builder**. Build the guided quote from workspace pricing and Price Book products. If pricing is unavailable, configure **Settings → Pricing** at `/settings?tab=pricing`.

Route: `/landscape-lighting`. Sidebar label: **Landscape Lighting**. Select **New lighting project**, enter the project and customer details, and select **Create project**. Open the saved designer at `/landscape-lighting/{project_id}`. The list can show active and archived projects and can recover a browser draft when one exists.

Route: `/christmas-lights`. Sidebar label: **Christmas Light Estimator**. Create a seasonal estimate using the configured Christmas pricing.

## Create an invoice

Route: `/invoices`. Sidebar label: **Invoices**.

1. Open **Invoices**.
2. Select **New invoice**. The **New invoice** dialog opens on the same route.
3. Under **Bill to**, search by name or email and select the customer. A customer without an email can have a draft, but **Create & send** cannot email it.
4. Under **Line items**, select **Add from price book** or select **Add line** and enter a description, quantity, and price. At least one line is required; each line can be marked **Optional item**.
5. Set the optional **Due date**, **Tax**, and **Notes**, then verify **Total**.
6. Select **Save draft** to create an internal draft, or **Create & send** to create the invoice and attempt email delivery immediately.

Confirm the customer, email availability, line items, total, and due date before selecting **Create & send**. The delivery notice reports whether an email actually reached a configured destination.

## Send, text, edit, void, or delete an invoice

1. Open `/invoices` and find the invoice.
2. Open its **Actions** menu.
3. Use **Edit invoice** for a non-void invoice; a paid invoice offers **Edit notes** and keeps its accounting lines locked.
4. Use **Send invoice** for a draft or **Resend invoice** for an eligible issued invoice. Use **Text invoice** when the invoice has a contact and the customer should receive its public link by SMS.
5. Use **Void invoice** for an eligible issued invoice. Use **Delete draft** only for a draft that should be permanently removed, then confirm **Delete invoice**.

Statuses shown by the list are Draft, Sent, Partial, Paid, Overdue, and Void. There is no duplicate or manual **Mark as Paid** action on this screen.

## Customer invoice and payment

A delivered invoice opens at `/p/invoices/{token}`. The public page shows the customer's invoice and available hosted-payment control without exposing the CRM. Successful or canceled hosted-payment returns use `/payment-complete` and `/payment-cancelled`.

If the customer link is dead, an admin should verify the deployment's frontend URL before resending it. A successful send action without a delivered destination is not proof that the customer received the invoice.
