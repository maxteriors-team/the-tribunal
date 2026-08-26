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

1. Create a customer estimate from **Light Designer** at `/quotes?tab=designer` or from a saved **Permanent Lighting** or **Landscape Lighting** project.
2. Open the **Quotes** tab and find the saved quote.
3. Open the quote's **Actions** menu.
4. Use **Email proposal to client** or **Text proposal to client** to deliver the customer proposal. Either action can send a draft and create its client link.
5. Use **Preview client proposal** for a staff preview or **Copy client link** when those actions are available. The customer route is `/p/quotes/{token}`.

The row menu can also offer **Assign owner**, **Edit quote**, **Manage services**, **Mark as sent**, **Re-send email**, **Approve**, **Decline**, **Convert to job & invoice**, and **Delete quote** according to status. **Manage services** can edit a plain quote line's name, description, and overall amount; rich proposal fixture lines remain server-priced in their originating designer. Quote editing happens in a dialog on `/quotes`; there is no separate edit route.

After approval, the **Copy to Job** tab shows every selected permanent-light kit and quantity so the operator can order and track the installation package before scheduling.

## Use lighting estimators

Route: `/quotes?tab=designer`. Open the **Light Designer** tab to trace permanent or seasonal rooflines on a customer photo, price the design from workspace settings, and save or deliver the estimate. For a selected permanent run, **Aerial Pics · 1.5×** is available alongside Easy, Standard, and Complex and prices that run's measured feet at the fixed 1.5× multiplier.

Route: `/permanent-lighting`. Sidebar label: **Permanent Lighting**. Select **New lighting project**, name the design, and select the customer before creating it. Open the saved designer at `/permanent-lighting/{project_id}` to draw permanent roofline track. Select **Save** and wait for **Saved to Tribunal**; the client-linked drawing can then be reopened, edited, and saved again. Active projects can be archived and later restored.

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
