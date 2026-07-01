"""API v1 router aggregator."""

from fastapi import APIRouter

from app.api.v1 import (
    ad_library,
    agents,
    api_keys,
    appointments,
    auth,
    automations,
    billing,
    bookable_staff,
    call_feedback,
    call_outcomes,
    calls,
    campaign_reports,
    campaigns,
    catalog,
    contacts,
    conversations,
    crm_assistant,
    dashboard,
    demo,
    device_tokens,
    drip_campaigns,
    email_unsubscribe,
    embed,
    field_service,
    find_leads_ai,
    human_profiles,
    improvement_suggestions,
    integrations,
    invitations,
    invoices,
    jobs,
    knowledge_documents,
    lead_form,
    lead_magnets,
    lead_sources,
    message_templates,
    message_tests,
    nudges,
    offers,
    opportunities,
    outbound_missions,
    pending_actions,
    phone_numbers,
    prompt_versions,
    prospects,
    quotes,
    realtime,
    recurring_jobs,
    reporting,
    reviews,
    roleplay,
    scorecard,
    scraping,
    segments,
    settings,
    tags,
    voice_campaigns,
    workspaces,
)
from app.api.v1.integrations import followupboss as fub_integration
from app.api.v1.integrations import openai_oauth as openai_oauth_integration
from app.api.v1.onboarding import realtor_setup

api_router = APIRouter()

# Include routers
api_router.include_router(auth.router, prefix="/auth", tags=["Authentication"])
api_router.include_router(settings.router, prefix="/settings", tags=["Settings"])
api_router.include_router(realtime.router, prefix="/realtime", tags=["Realtime"])
api_router.include_router(device_tokens.router, prefix="/settings", tags=["Settings"])
api_router.include_router(workspaces.router, prefix="/workspaces", tags=["Workspaces"])
api_router.include_router(
    api_keys.router,
    prefix="/workspaces/{workspace_id}/api-keys",
    tags=["API Keys"],
)
api_router.include_router(
    contacts.router,
    prefix="/workspaces/{workspace_id}/contacts",
    tags=["Contacts"],
)
api_router.include_router(
    tags.router,
    prefix="/workspaces/{workspace_id}/tags",
    tags=["Tags"],
)
api_router.include_router(
    segments.router,
    prefix="/workspaces/{workspace_id}/segments",
    tags=["Segments"],
)
api_router.include_router(
    conversations.router,
    prefix="/workspaces/{workspace_id}/conversations",
    tags=["Conversations"],
)
api_router.include_router(
    agents.router,
    prefix="/workspaces/{workspace_id}/agents",
    tags=["Agents"],
)
api_router.include_router(
    crm_assistant.router,
    prefix="/workspaces/{workspace_id}/assistant",
    tags=["CRM Assistant"],
)
api_router.include_router(
    prompt_versions.router,
    prefix="/workspaces/{workspace_id}/agents/{agent_id}/prompts",
    tags=["Prompt Versions"],
)
api_router.include_router(
    bookable_staff.router,
    prefix="/workspaces/{workspace_id}/agents/{agent_id}/staff",
    tags=["Bookable Staff"],
)
api_router.include_router(
    improvement_suggestions.router,
    prefix="/workspaces/{workspace_id}/suggestions",
    tags=["Improvement Suggestions"],
)
api_router.include_router(
    campaigns.router,
    prefix="/workspaces/{workspace_id}/campaigns",
    tags=["Campaigns"],
)
api_router.include_router(
    voice_campaigns.router,
    prefix="/workspaces/{workspace_id}/voice-campaigns",
    tags=["Voice Campaigns"],
)
api_router.include_router(
    campaign_reports.router,
    prefix="/workspaces/{workspace_id}/campaign-reports",
    tags=["Campaign Reports"],
)
api_router.include_router(
    message_tests.router,
    prefix="/workspaces/{workspace_id}/message-tests",
    tags=["Message Tests"],
)
api_router.include_router(
    message_templates.router,
    prefix="/workspaces/{workspace_id}/message-templates",
    tags=["Message Templates"],
)
api_router.include_router(
    offers.router,
    prefix="/workspaces/{workspace_id}/offers",
    tags=["Offers"],
)
api_router.include_router(
    lead_magnets.router,
    prefix="/workspaces/{workspace_id}/lead-magnets",
    tags=["Lead Magnets"],
)
api_router.include_router(
    phone_numbers.router,
    prefix="/workspaces/{workspace_id}/phone-numbers",
    tags=["Phone Numbers"],
)
api_router.include_router(
    appointments.router,
    prefix="/workspaces/{workspace_id}/appointments",
    tags=["Appointments"],
)
api_router.include_router(
    calls.router,
    prefix="/workspaces/{workspace_id}/calls",
    tags=["Voice Calls"],
)
api_router.include_router(
    call_outcomes.router,
    prefix="/workspaces/{workspace_id}/calls/{message_id}/outcome",
    tags=["Call Outcomes"],
)
api_router.include_router(
    call_feedback.router,
    prefix="/workspaces/{workspace_id}/calls/{message_id}/feedback",
    tags=["Call Feedback"],
)
api_router.include_router(
    automations.router,
    prefix="/workspaces/{workspace_id}/automations",
    tags=["Automations"],
)
api_router.include_router(
    opportunities.router,
    prefix="/workspaces/{workspace_id}/opportunities",
    tags=["Opportunities"],
)
api_router.include_router(
    invoices.router,
    prefix="/workspaces/{workspace_id}/invoices",
    tags=["Invoices"],
)
api_router.include_router(
    quotes.router,
    prefix="/workspaces/{workspace_id}/quotes",
    tags=["Quotes"],
)
api_router.include_router(
    catalog.router,
    prefix="/workspaces/{workspace_id}/catalog-items",
    tags=["Catalog"],
)
api_router.include_router(
    dashboard.router,
    prefix="/workspaces/{workspace_id}/dashboard",
    tags=["Dashboard"],
)
api_router.include_router(
    scorecard.router,
    prefix="/workspaces/{workspace_id}/scorecard",
    tags=["Receptionist Scorecard"],
)
api_router.include_router(
    integrations.router,
    prefix="/workspaces/{workspace_id}/integrations",
    tags=["Integrations"],
)
api_router.include_router(
    openai_oauth_integration.router,
    prefix="/workspaces/{workspace_id}/integrations",
    tags=["Integrations"],
)
api_router.include_router(
    openai_oauth_integration.public_router,
    prefix="/integrations/openai/oauth",
    tags=["Integrations"],
)
api_router.include_router(
    invitations.router,
    prefix="/workspaces/{workspace_id}/invitations",
    tags=["Invitations"],
)
api_router.include_router(
    scraping.router,
    prefix="/workspaces/{workspace_id}/scraping",
    tags=["Lead Scraping"],
)
api_router.include_router(
    find_leads_ai.router,
    prefix="/workspaces/{workspace_id}/find-leads-ai",
    tags=["Find Leads AI"],
)
api_router.include_router(
    outbound_missions.router,
    prefix="/workspaces/{workspace_id}/outbound-missions",
    tags=["Outbound Missions"],
)
api_router.include_router(
    ad_library.router,
    prefix="/workspaces/{workspace_id}/ad-library",
    tags=["Ad Library"],
)
api_router.include_router(
    prospects.router,
    prefix="/workspaces/{workspace_id}/prospects",
    tags=["Prospects"],
)
# Public invitation endpoints (token-based)
api_router.include_router(
    invitations.public_router,
    prefix="/invitations",
    tags=["Invitations"],
)
# Public offer endpoints (no auth)
api_router.include_router(
    offers.public_router,
    prefix="/p/offers",
    tags=["Public Offers"],
)
# Public email unsubscribe endpoint (no auth) — linked from marketing email footers
api_router.include_router(
    email_unsubscribe.public_router,
    prefix="/email",
    tags=["Email Unsubscribe"],
)
# Public demo endpoints (no auth, rate limited)
api_router.include_router(
    demo.router,
    prefix="/p/demo",
    tags=["Public Demo"],
)
# Public embed endpoints (no auth, origin-validated)
api_router.include_router(
    embed.router,
    prefix="/p/embed",
    tags=["Public Embed"],
)
# Lead Sources CRUD (authenticated)
api_router.include_router(
    lead_sources.router,
    prefix="/workspaces/{workspace_id}/lead-sources",
    tags=["Lead Sources"],
)
api_router.include_router(
    lead_sources.campaigns_router,
    prefix="/workspaces/{workspace_id}/lead-source-campaigns",
    tags=["Lead Sources"],
)
api_router.include_router(
    lead_sources.spend_router,
    prefix="/workspaces/{workspace_id}/lead-source-spend",
    tags=["Lead Sources"],
)
# Field service: locations, crews, technicians (ServiceTitan/Jobber-style)
api_router.include_router(
    field_service.locations_router,
    prefix="/workspaces/{workspace_id}/service-locations",
    tags=["Field Service"],
)
api_router.include_router(
    field_service.crews_router,
    prefix="/workspaces/{workspace_id}/crews",
    tags=["Field Service"],
)
api_router.include_router(
    field_service.technicians_router,
    prefix="/workspaces/{workspace_id}/technicians",
    tags=["Field Service"],
)
api_router.include_router(
    jobs.router,
    prefix="/workspaces/{workspace_id}/jobs",
    tags=["Field Service"],
)
api_router.include_router(
    recurring_jobs.router,
    prefix="/workspaces/{workspace_id}/recurring-jobs",
    tags=["Field Service"],
)
api_router.include_router(
    reporting.router,
    prefix="/workspaces/{workspace_id}/reports",
    tags=["Reporting"],
)
api_router.include_router(
    nudges.router,
    prefix="/workspaces/{workspace_id}/nudges",
    tags=["Human Nudges"],
)
api_router.include_router(
    nudges.settings_router,
    prefix="/workspaces/{workspace_id}/nudge-settings",
    tags=["Human Nudges"],
)
# Public lead form endpoint (no auth, origin-validated, rate-limited)
api_router.include_router(
    lead_form.router,
    prefix="/p/leads",
    tags=["Public Lead Form"],
)
api_router.include_router(
    human_profiles.router,
    prefix="/workspaces/{workspace_id}/agents/{agent_id}/human-profile",
    tags=["Human Profile"],
)
api_router.include_router(
    knowledge_documents.router,
    prefix="/workspaces/{workspace_id}/agents/{agent_id}/knowledge",
    tags=["Knowledge Documents"],
)
api_router.include_router(
    pending_actions.router,
    prefix="/workspaces/{workspace_id}/pending-actions",
    tags=["Pending Actions"],
)
api_router.include_router(
    drip_campaigns.router,
    prefix="/workspaces/{workspace_id}/drip-campaigns",
    tags=["Drip Campaigns"],
)
api_router.include_router(
    reviews.router,
    prefix="/workspaces/{workspace_id}/reviews",
    tags=["Reviews"],
)
api_router.include_router(
    roleplay.router,
    prefix="/workspaces/{workspace_id}/roleplay",
    tags=["Practice Arena"],
)
# Public review rating-gate landing page (no auth)
api_router.include_router(
    reviews.public_router,
    prefix="/p/reviews",
    tags=["Public Reviews"],
)
api_router.include_router(billing.router, prefix="/billing", tags=["Billing"])
api_router.include_router(
    realtor_setup.router,
    prefix="/realtor",
    tags=["Realtor Onboarding"],
)
api_router.include_router(
    fub_integration.router,
    prefix="/realtor",
    tags=["Follow Up Boss"],
)
api_router.include_router(
    realtor_setup.workspace_router,
    prefix="/workspaces/{workspace_id}/realtor",
    tags=["Realtor Onboarding"],
)
