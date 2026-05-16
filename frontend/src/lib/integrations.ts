export type IntegrationType =
  | "crm"
  | "calendar"
  | "database"
  | "productivity"
  | "communication"
  | "other";

export type AuthType = "oauth" | "api_key" | "basic" | "none";

export type ToolRiskLevel = "safe" | "moderate" | "high";

export interface IntegrationTool {
  id: string;
  name: string;
  description: string;
  riskLevel: ToolRiskLevel;
  defaultEnabled?: boolean;
}

export interface Integration {
  id: string;
  name: string;
  slug: string;
  description: string;
  category: IntegrationType;
  authType: AuthType;
  icon: string;
  enabled: boolean;
  isPopular?: boolean;
  isBuiltIn?: boolean;
  badge?: string;
  tools?: IntegrationTool[];
}

export const AVAILABLE_INTEGRATIONS: Integration[] = [
  // Built-in Tools (No external API needed)
  {
    id: "call_control",
    name: "Call Control",
    slug: "call-control",
    description: "End calls, transfer to agents, send DTMF tones for IVR navigation",
    category: "communication",
    authType: "none",
    icon: "https://cdn.simpleicons.org/phone",
    enabled: true,
    isBuiltIn: true,
    badge: "Built-in",
    tools: [
      {
        id: "end_call",
        name: "End Call",
        description: "Hang up and end the current phone call gracefully",
        riskLevel: "moderate",
        defaultEnabled: true,
      },
      {
        id: "transfer_call",
        name: "Transfer Call",
        description: "Transfer the caller to another phone number or human agent",
        riskLevel: "high",
        defaultEnabled: true,
      },
      {
        id: "send_dtmf",
        name: "Send DTMF",
        description: "Send touch-tone digits for IVR navigation or entering codes",
        riskLevel: "safe",
        defaultEnabled: true,
      },
    ],
  },
  {
    id: "crm",
    name: "Contact Management",
    slug: "crm",
    description: "Search customers, view contact details, manage customer data",
    category: "crm",
    authType: "none",
    icon: "https://cdn.simpleicons.org/contactlessPayment",
    enabled: true,
    isBuiltIn: true,
    badge: "Built-in",
    tools: [
      {
        id: "search_customer",
        name: "Search Customer",
        description: "Search for a customer by phone number, email, or name",
        riskLevel: "safe",
        defaultEnabled: true,
      },
      {
        id: "create_contact",
        name: "Create Contact",
        description: "Create a new contact/customer in the CRM",
        riskLevel: "moderate",
        defaultEnabled: true,
      },
    ],
  },
  {
    id: "bookings",
    name: "Appointment Booking",
    slug: "bookings",
    description: "Check availability, book appointments, cancel/reschedule bookings",
    category: "calendar",
    authType: "none",
    icon: "https://cdn.simpleicons.org/calendly",
    enabled: true,
    isBuiltIn: true,
    badge: "Built-in",
    tools: [
      {
        id: "check_availability",
        name: "Check Availability",
        description: "Check available appointment time slots for a specific date",
        riskLevel: "safe",
        defaultEnabled: true,
      },
      {
        id: "book_appointment",
        name: "Book Appointment",
        description: "Book an appointment for a customer",
        riskLevel: "moderate",
        defaultEnabled: true,
      },
      {
        id: "list_appointments",
        name: "List Appointments",
        description: "List upcoming appointments, optionally filtered by date or contact",
        riskLevel: "safe",
        defaultEnabled: true,
      },
      {
        id: "cancel_appointment",
        name: "Cancel Appointment",
        description: "Cancel an existing appointment",
        riskLevel: "high",
        defaultEnabled: false,
      },
      {
        id: "reschedule_appointment",
        name: "Reschedule Appointment",
        description: "Reschedule an existing appointment to a new time",
        riskLevel: "moderate",
        defaultEnabled: true,
      },
    ],
  },

  // External CRM Integrations
  {
    id: "hubspot",
    name: "HubSpot",
    slug: "hubspot",
    description: "Manage contacts, deals, and customer interactions",
    category: "crm",
    authType: "api_key",
    icon: "https://cdn.simpleicons.org/hubspot",
    enabled: true,
    isPopular: true,
    tools: [
      {
        id: "hubspot_search_contact",
        name: "Search Contact",
        description: "Search for a contact in HubSpot by email, phone, or name",
        riskLevel: "safe",
        defaultEnabled: true,
      },
      {
        id: "hubspot_create_contact",
        name: "Create Contact",
        description: "Create a new contact in HubSpot",
        riskLevel: "moderate",
        defaultEnabled: true,
      },
      {
        id: "hubspot_update_contact",
        name: "Update Contact",
        description: "Update an existing contact's information",
        riskLevel: "moderate",
        defaultEnabled: true,
      },
    ],
  },
  {
    id: "salesforce",
    name: "Salesforce",
    slug: "salesforce",
    description: "Access customer data, create leads, update opportunities",
    category: "crm",
    authType: "api_key",
    icon: "https://cdn.simpleicons.org/salesforce",
    enabled: true,
    isPopular: true,
    tools: [
      {
        id: "salesforce_search_lead",
        name: "Search Lead",
        description: "Search for a lead in Salesforce",
        riskLevel: "safe",
        defaultEnabled: true,
      },
      {
        id: "salesforce_create_lead",
        name: "Create Lead",
        description: "Create a new lead in Salesforce",
        riskLevel: "moderate",
        defaultEnabled: true,
      },
    ],
  },

  // Calendar Integrations
  {
    id: "google-calendar",
    name: "Google Calendar",
    slug: "google-calendar",
    description: "Schedule meetings, check availability, create events",
    category: "calendar",
    authType: "api_key",
    icon: "https://cdn.simpleicons.org/googlecalendar",
    enabled: true,
    isPopular: true,
    tools: [
      {
        id: "gcal_check_availability",
        name: "Check Availability",
        description: "Check available time slots on Google Calendar",
        riskLevel: "safe",
        defaultEnabled: true,
      },
      {
        id: "gcal_create_event",
        name: "Create Event",
        description: "Create a new calendar event",
        riskLevel: "moderate",
        defaultEnabled: true,
      },
    ],
  },
  {
    id: "cal-com",
    name: "Cal.com",
    slug: "cal-com",
    description: "Open-source scheduling platform with direct booking support",
    category: "calendar",
    authType: "api_key",
    icon: "https://cdn.simpleicons.org/caldotcom",
    enabled: true,
    isPopular: true,
    tools: [
      {
        id: "calcom_get_availability",
        name: "Get Availability",
        description: "Get available time slots for booking",
        riskLevel: "safe",
        defaultEnabled: true,
      },
      {
        id: "calcom_create_booking",
        name: "Create Booking",
        description: "Create a booking/appointment directly",
        riskLevel: "moderate",
        defaultEnabled: true,
      },
      {
        id: "calcom_cancel_booking",
        name: "Cancel Booking",
        description: "Cancel a booking/appointment",
        riskLevel: "high",
        defaultEnabled: false,
      },
    ],
  },

  // Communication
  {
    id: "slack",
    name: "Slack",
    slug: "slack",
    description: "Send messages, notifications, and alerts",
    category: "communication",
    authType: "api_key",
    icon: "https://cdn.simpleicons.org/slack",
    enabled: true,
    isPopular: true,
    tools: [
      {
        id: "slack_send_message",
        name: "Send Message",
        description: "Send a message to a Slack channel or user",
        riskLevel: "moderate",
        defaultEnabled: true,
      },
    ],
  },
  {
    id: "twilio-sms",
    name: "Twilio SMS",
    slug: "twilio-sms",
    description: "Send SMS messages and receive replies",
    category: "communication",
    authType: "api_key",
    icon: "https://cdn.simpleicons.org/twilio",
    enabled: true,
    isPopular: true,
    tools: [
      {
        id: "twilio_send_sms",
        name: "Send SMS",
        description: "Send an SMS message to a phone number",
        riskLevel: "moderate",
        defaultEnabled: true,
      },
    ],
  },

  // Other
  {
    id: "stripe",
    name: "Stripe",
    slug: "stripe",
    description: "Payment processing and subscription management",
    category: "other",
    authType: "api_key",
    icon: "https://cdn.simpleicons.org/stripe",
    enabled: true,
    isPopular: true,
    tools: [
      {
        id: "stripe_get_customer",
        name: "Get Customer",
        description: "Look up customer payment information",
        riskLevel: "safe",
        defaultEnabled: true,
      },
      {
        id: "stripe_create_payment_link",
        name: "Create Payment Link",
        description: "Create a payment link for the customer",
        riskLevel: "moderate",
        defaultEnabled: true,
      },
    ],
  },
];
