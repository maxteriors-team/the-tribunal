# Configuration Guide - Complete Setup

All 5 phases are wired. Here's exactly what you need configured for the end-to-end workflow to work.

---

## 1️⃣ Environment Variables (`.env`)

### Required for Workflow
```bash
# Cal.com Integration
CALCOM_API_KEY=your_calcom_api_key_here
CALCOM_WEBHOOK_SECRET=your_calcom_webhook_secret_here

# Telnyx Integration (already configured)
TELNYX_API_KEY=your_telnyx_api_key_here
TELNYX_PUBLIC_KEY=base64_encoded_public_key_here

# OpenAI (already configured)
OPENAI_API_KEY=your_openai_api_key_here

# Database
DATABASE_URL=postgresql+asyncpg://user:password@localhost/aicrm

# Server
ENVIRONMENT=production
DEBUG=false
```

### Status
- ✅ Cal.com API key: **You mentioned it's in .env**
- ✅ Telnyx API key: **Already configured**
- ✅ OpenAI API key: **Already configured**

---

## 2️⃣ Agent Configuration

### Sales Agent Setup

**Required:**
1. Go to Dashboard → AI Agents
2. Click your Sales Agent (or create one)
3. Fill in these fields:

```
Name: Sales Agent
Description: Handles customer inquiries and books appointments
Channel Mode: text (or both if you want voice later)
Active: ✓ checked
```

**TEXT SETTINGS (Required for SMS):**
```
Language: en-US
System Prompt: "You are a helpful sales agent. Help prospects understand our offerings and guide them toward solutions. If they're interested, offer to schedule a meeting."
Temperature: 0.7
Text Response Delay: 2000ms
Max Context Messages: 20
```

**CALENDAR INTEGRATION (Required for booking):**
```
☑ Enable Calendar Integration
Cal.com Event Type ID: [YOUR_EVENT_ID_HERE]
```

✅ **Status:** You said this is already set in the sales agent settings

---

## 3️⃣ Cal.com Setup

### Get Your Event Type ID

1. Log in to cal.com
2. Go to Settings → Event Types
3. Find your event (e.g., "Sales Meeting", "30-minute Call")
4. Copy the event type ID (usually a number like `123456`)
5. Paste into agent settings above

### Event Type Configuration (in Cal.com)

**Recommended settings:**
- Duration: 30 minutes
- Buffer before: 0 minutes
- Buffer after: 15 minutes (gives you time between calls)
- Booking questions:
  - Email (required) - for video call invite
  - Company (optional)
  - Notes (optional)

### Webhook Setup (in Cal.com)

Cal.com will send webhooks to your server. Configure:

```
Webhook URL: https://your-domain.com/webhooks/calcom/booking
Trigger Events:
  ☑ BOOKING_CREATED
  ☑ BOOKING_RESCHEDULED
  ☑ BOOKING_CANCELLED
```

✅ Your system will automatically:
- Verify the webhook signature (HMAC-SHA256)
- Extract booking details
- Look up contact by email
- Look up agent by event type ID
- Create Appointment record
- Log the sync

---

## 4️⃣ Telnyx Setup (Already Done)

### Phone Numbers

**Verify you have:**
1. At least one Telnyx phone number active
2. Number is SMS-enabled
3. Number is linked to your workspace

**Check in Dashboard:**
- Go to Settings → Phone Numbers
- See your Telnyx number(s)
- Should show SMS capability enabled

✅ **Status:** You mentioned you have Telnyx numbers configured

---

## 5️⃣ Contact Setup

### Nolan Grout Contact

**Required fields for workflow:**
```
First Name: Nolan
Last Name: Grout
Phone: +1-XXX-XXX-XXXX (must match your test phone)
Email: nolan@example.com (REQUIRED - used for Cal.com booking)
Company: (optional)
Status: new (or any status)
```

✅ **Status:** Nolan Grout contact exists in your database

### Email Field Importance

The email is **CRITICAL** because:
1. Cal.com requires email for video call invites
2. When Nolan books, Cal.com sends confirmation to this email
3. Webhook looks up contact by email
4. Pre-fill for Cal.com booking link uses this email

**Make sure Nolan has email set:**
```sql
SELECT first_name, last_name, phone, email FROM contacts WHERE first_name='Nolan';
-- Should show: Nolan | Grout | +1-XXX-XXX-XXXX | nolan@example.com
```

---

## 6️⃣ Offer Configuration

### Create Test Offer

**Option A: Via API**
```bash
curl -X POST http://localhost:8000/api/v1/workspaces/{workspace_id}/offers \
  -H "Authorization: Bearer {token}" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "20% Off Premium Package",
    "discount_type": "percentage",
    "discount_value": 20,
    "description": "Premium support included",
    "terms": "Valid for 90 days",
    "is_active": true
  }'
```

**Option B: Via Dashboard**
1. Dashboard → Offers → Create New
2. Fill in fields
3. Click Create

**Fields:**
```
Name: 20% Off Premium Package
Discount Type: percentage
Discount Value: 20
Description: Premium support included
Terms: Valid for 90 days
Active: ✓ checked
```

---

## 7️⃣ Campaign Configuration

### Create Test Campaign

**Via API:**
```bash
curl -X POST http://localhost:8000/api/v1/workspaces/{workspace_id}/campaigns \
  -H "Authorization: Bearer {token}" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Nolan Test Campaign",
    "type": "sms",
    "agent_id": "sales-agent-uuid",
    "offer_id": "offer-uuid",
    "initial_message": "Hi {first_name}, we have {offer_name} for you - {offer_discount}. {offer_description}. Terms: {offer_terms}. Reply to learn more!",
    "status": "draft"
  }'
```

**Via Dashboard:**
1. Dashboard → Campaigns → New SMS Campaign
2. Fill in:
   - Name: "Nolan Test Campaign"
   - Agent: Select your Sales Agent
   - Offer: Select "20% Off Premium Package"
   - Message: Use template with `{offer_name}`, `{offer_discount}`, etc.
3. Click Create

**Message Template Variables Available:**
```
Contact Variables:
  {first_name}          → "Nolan"
  {last_name}           → "Grout"
  {full_name}           → "Nolan Grout"
  {email}               → "nolan@example.com"
  {company_name}        → Contact's company

Offer Variables (if offer selected):
  {offer_name}          → "20% Off Premium Package"
  {offer_discount}      → "20% off" (formatted)
  {offer_description}   → "Premium support included"
  {offer_terms}         → "Valid for 90 days"
```

---

## 8️⃣ Add Contact to Campaign

### Via API
```bash
curl -X POST http://localhost:8000/api/v1/workspaces/{workspace_id}/campaigns/{campaign_id}/contacts \
  -H "Authorization: Bearer {token}" \
  -H "Content-Type: application/json" \
  -d '{
    "contact_ids": ["nolan-contact-id"]
  }'
```

### Via Dashboard
1. Campaign detail page
2. Click "Add Contacts"
3. Select Nolan Grout
4. Click Add

---

## 9️⃣ Start Campaign

### Via API
```bash
curl -X POST http://localhost:8000/api/v1/workspaces/{workspace_id}/campaigns/{campaign_id}/start \
  -H "Authorization: Bearer {token}"
```

### Via Dashboard
1. Campaign detail page
2. Click "Start Campaign"
3. Confirm

**What happens:**
- ✅ Campaign status → "running"
- ✅ Campaign worker starts polling (5-second interval)
- ✅ Within 5 seconds: SMS sent to Nolan with offer details
- ✅ Campaign worker logs SMS sent

---

## 🔟 Verify Setup is Complete

### Checklist

**Environment:**
- [ ] `CALCOM_API_KEY` in .env
- [ ] `CALCOM_WEBHOOK_SECRET` in .env
- [ ] `TELNYX_API_KEY` in .env
- [ ] `OPENAI_API_KEY` in .env
- [ ] Database connected

**Agent:**
- [ ] Sales Agent exists
- [ ] Sales Agent has system prompt set
- [ ] Sales Agent has `calcom_event_type_id` = your event ID
- [ ] Sales Agent channel_mode = "text" or "both"
- [ ] Sales Agent is_active = true

**Cal.com:**
- [ ] Event type ID copied from cal.com
- [ ] Webhook configured in cal.com to point to `/webhooks/calcom/booking`
- [ ] Webhook events: BOOKING_CREATED, BOOKING_RESCHEDULED, BOOKING_CANCELLED

**Telnyx:**
- [ ] Phone number configured in system
- [ ] Phone number has SMS enabled
- [ ] Phone number linked to workspace

**Contacts:**
- [ ] Nolan Grout exists
- [ ] Nolan has email address (nolan@example.com)
- [ ] Nolan has phone number (+1-XXX-XXX-XXXX)

**Offer:**
- [ ] Offer created (e.g., "20% Off Premium Package")
- [ ] Offer has discount type and value set
- [ ] Offer is_active = true

**Campaign:**
- [ ] Campaign created with agent + offer
- [ ] Campaign has proper message template with `{offer_*}` placeholders
- [ ] Nolan added to campaign
- [ ] Campaign status can be changed to "running"

---

## 🧪 Test Execution

### Step 1: Send Initial SMS
```bash
# Start campaign
POST /api/v1/workspaces/{workspace_id}/campaigns/{campaign_id}/start
```

**Expect within 5 seconds:**
- SMS arrives on Nolan's phone
- Message includes: "Hi Nolan, we have 20% Off Premium Package - 20% off..."
- Check server logs for: `[info] sms_sent offer_id=... offer_name="20% Off Premium Package"`

### Step 2: Nolan Replies
```
Text back: "That sounds great! When can I schedule?"
```

**Expect within 2-3 seconds:**
- Inbound webhook received from Telnyx
- Conversation created
- Message stored
- AI response scheduled
- Check logs for: `[info] ai_response_generated has_booking_link=true`

### Step 3: Receive AI Response
**Expect:**
- SMS arrives: "Thanks for the interest! With our 20% off offer..."
- SMS includes: Cal.com booking link with pre-filled email/name/phone
- Check logs for: `[info] ai_sms_sent offer_included=true booking_link_included=true`

### Step 4: Book Appointment
Click booking link in SMS
- Cal.com opens with fields pre-filled
- Select time
- Click Confirm
- Wait for webhook

**Expect within 1-2 seconds:**
- Webhook arrives at `/webhooks/calcom/booking`
- Appointment created in database
- Check logs for: `[info] booking_received sync_status=synced`

### Step 5: View in Dashboard
```
1. Click Nolan Grout contact
2. See conversation with all messages
3. See "Appointments" section with new appointment
4. Click Calendar page
5. See appointment in week view
```

---

## 🛠️ Troubleshooting

### SMS Not Sending
**Check:**
- Campaign status is "running"
- Telnyx API key is valid
- Phone number exists in workspace
- Contact has phone number

**Logs:**
```
grep -r "sms_sent" backend/logs/ or check structlog output
```

### AI Response Not Generated
**Check:**
- Agent exists and is_active = true
- Agent has calcom_event_type_id set
- OpenAI API key is valid
- Message was received (check Telnyx webhook logs)

**Logs:**
```
grep -r "ai_response_generated" backend/logs/
grep -r "Error in campaign worker" backend/logs/
```

### Appointment Not Syncing
**Check:**
- Cal.com webhook is configured correctly
- Cal.com webhook secret matches CALCOM_WEBHOOK_SECRET in .env
- Contact email matches exactly (case-sensitive)
- Agent event_type_id matches Cal.com event

**Logs:**
```
grep -r "booking_received" backend/logs/
grep -r "sync_error" backend/logs/
```

---

## 📊 Production Checklist

Before going live:

- [ ] All environment variables set
- [ ] Database backups configured
- [ ] Error monitoring/alerting set up
- [ ] Logs are being collected
- [ ] SSL/TLS certificates valid
- [ ] Rate limiting configured on Telnyx/OpenAI/Cal.com
- [ ] Webhook URLs use HTTPS
- [ ] API keys are rotated regularly
- [ ] Database has proper indexes (already done)
- [ ] Campaign worker is monitored
- [ ] Webhook signatures are verified

---

## 🎯 Summary

**Configuration Status:**
- ✅ Cal.com API key: In .env
- ✅ Cal.com event ID: In agent settings
- ✅ Telnyx: Configured with SMS
- ✅ OpenAI: Configured
- ✅ Database: Connected
- ✅ Nolan contact: Exists with email

**Ready to:**
1. Create offer
2. Create campaign
3. Add Nolan
4. Start campaign
5. Send test SMS
6. Receive AI response with booking link
7. Book appointment
8. See in dashboard

**Everything is configured and ready to go! 🚀**
