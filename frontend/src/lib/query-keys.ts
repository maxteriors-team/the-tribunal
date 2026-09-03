/**
 * Centralized React Query key factory.
 *
 * Contract for workspace-scoped CRUD resources:
 * - `root()` -> every query for the resource across workspaces.
 * - `all(workspaceId)` -> every query for the resource in one workspace.
 * - `list(workspaceId, params?)` -> list queries; unfiltered lists intentionally
 *   share the workspace `all` key, while filtered lists append normalized params.
 * - `detail(workspaceId, id)` -> one resource instance.
 *
 * Filtered-list helper names should delegate to `list(workspaceId, params)`.
 * Mutation invalidation should use `all(workspaceId)` or, when intentionally
 * broad, `root()`.
 *
 * RULE: never hand-write a `queryKey: [...]` literal. Add a builder here
 * instead. The `no-restricted-syntax` ESLint rule enforces this.
 */

import type { ResourceId } from "@/types/api";

export type QueryKey = readonly unknown[];
export type QueryKeyParams = Readonly<Record<string, unknown>>;

export interface ResourceQueryKeys<Name extends string = string> {
  root: () => readonly [Name];
  all: (workspaceId: string) => readonly [Name, string];
  list: (workspaceId: string, params?: QueryKeyParams | null) => QueryKey;
  detail: (workspaceId: string, id: ResourceId | null | undefined) => QueryKey;
}

function isPlainRecord(value: unknown): value is Record<string, unknown> {
  return (
    typeof value === "object" &&
    value !== null &&
    !Array.isArray(value) &&
    Object.getPrototypeOf(value) === Object.prototype
  );
}

function normalizeQueryKeyValue(value: unknown): unknown {
  if (Array.isArray(value)) {
    return value.map(normalizeQueryKeyValue);
  }

  if (!isPlainRecord(value)) {
    return value;
  }

  const entries = Object.entries(value)
    .filter(([, entryValue]) => entryValue !== undefined)
    .sort(([leftKey], [rightKey]) => leftKey.localeCompare(rightKey))
    .map(([entryKey, entryValue]) => [entryKey, normalizeQueryKeyValue(entryValue)] as const);

  return Object.fromEntries(entries);
}

function normalizeQueryKeyParams(
  params: QueryKeyParams | null | undefined,
): Record<string, unknown> | undefined {
  if (!params) {
    return undefined;
  }

  const normalized = normalizeQueryKeyValue(params) as Record<string, unknown>;
  return Object.keys(normalized).length > 0 ? normalized : undefined;
}

export function createResourceQueryKeys<Name extends string>(name: Name): ResourceQueryKeys<Name> {
  return {
    root: () => [name] as const,
    all: (workspaceId: string) => [name, workspaceId] as const,
    list: (workspaceId: string, params?: QueryKeyParams | null) => {
      const normalizedParams = normalizeQueryKeyParams(params);
      return normalizedParams
        ? ([name, workspaceId, normalizedParams] as const)
        : ([name, workspaceId] as const);
    },
    detail: (workspaceId: string, id: ResourceId | null | undefined) =>
      [name, workspaceId, id] as const,
  };
}

export function getResourceInvalidationKeys(
  resourceKey: string,
  workspaceId: string,
  relatedResourceKeys: readonly string[] = [],
): QueryKey[] {
  return [resourceKey, ...relatedResourceKeys].map((key) =>
    createResourceQueryKeys(key).all(workspaceId),
  );
}

const adAdvertisers = createResourceQueryKeys("ad-advertisers");
const agents = createResourceQueryKeys("agents");
const appointments = createResourceQueryKeys("appointments");
const automations = createResourceQueryKeys("automations");
const calls = createResourceQueryKeys("calls");
const campaignReports = createResourceQueryKeys("campaign-reports");
const campaigns = createResourceQueryKeys("campaigns");
const catalogItems = createResourceQueryKeys("catalog-items");
const contacts = createResourceQueryKeys("contacts");
const conversations = createResourceQueryKeys("conversations");
const dripCampaigns = createResourceQueryKeys("drip-campaigns");
const improvementSuggestions = createResourceQueryKeys("suggestions");
const integrations = createResourceQueryKeys("integrations");
const invitations = createResourceQueryKeys("invitations");
const inventoryItems = createResourceQueryKeys("inventory-items");
const invoices = createResourceQueryKeys("invoices");
const jobs = createResourceQueryKeys("jobs");
const servicePlans = createResourceQueryKeys("service-plans");
const quotes = createResourceQueryKeys("quotes");
const leadMagnets = createResourceQueryKeys("lead-magnets");
const leadSources = createResourceQueryKeys("lead-sources");
const lightingProjectResource = createResourceQueryKeys("lighting-projects");
const lightingProjects = {
  ...lightingProjectResource,
  browserDraft: (workspaceId: string) => ["lighting-project-browser-draft", workspaceId] as const,
  proposalPreview: (workspaceId: string, selectionSignature: string) =>
    ["lighting-project-proposal-preview", workspaceId, selectionSignature] as const,
  proposalInventoryAvailability: (workspaceId: string, selectionSignature: string) =>
    ["lighting-project-proposal-inventory", workspaceId, selectionSignature] as const,
};
const businessLocations = createResourceQueryKeys("business-locations");
const messageTemplates = createResourceQueryKeys("message-templates");
const messageTests = createResourceQueryKeys("message-tests");
const nudges = createResourceQueryKeys("nudges");
const offers = createResourceQueryKeys("offers");
const opportunities = createResourceQueryKeys("opportunities");
const pendingActions = createResourceQueryKeys("pending-actions");
const phoneNumbers = createResourceQueryKeys("phone-numbers");
const referralPartners = createResourceQueryKeys("referral-partners");
const revenueTargets = createResourceQueryKeys("revenue-targets");
const reviews = createResourceQueryKeys("reviews");
const segments = createResourceQueryKeys("segments");
const technicians = createResourceQueryKeys("technicians");

// Sales-wizard: config + catalog are the inputs the wizard loads per workspace.
const salesWizard = {
  pricing: (workspaceId: string) => ["sales-wizard-pricing", workspaceId] as const,
  catalog: (workspaceId: string) => ["sales-wizard-catalog", workspaceId] as const,
};

// Attach rules: the workspace's cross-sell prompt config, read by the settings
// editor and by the builder's dismissal UI.
const attachRules = {
  config: (workspaceId: string) => ["attach-rules", workspaceId] as const,
};

// Roofline estimator: a live permanent-vs-temporary price for a measured
// footage + option flags. Keyed on the inputs so the recompute is cached.
const estimator = {
  compute: (workspaceId: string, params: QueryKeyParams) =>
    ["estimator", workspaceId, normalizeQueryKeyParams(params)] as const,
};

// Pre-booking: an offer attached to an existing campaign, so the offer and its
// reservations nest under the campaign detail key and a campaign invalidate
// cascades to them. The audience preview is workspace-level on purpose — the
// wizard sizes the warm database before the campaign row exists.
const preBooking = {
  offer: (workspaceId: string, campaignId: string) =>
    [...campaigns.detail(workspaceId, campaignId), "pre-booking"] as const,
  audience: (workspaceId: string, params?: QueryKeyParams | null) =>
    ["pre-booking-audience", workspaceId, normalizeQueryKeyParams(params)] as const,
  reservations: (workspaceId: string, campaignId: string) =>
    [...campaigns.detail(workspaceId, campaignId), "pre-booking", "reservations"] as const,
};

export const queryKeys = {
  attendance: {
    all: (workspaceId: string) => ["attendance", workspaceId] as const,
    mine: (workspaceId: string, params?: QueryKeyParams | null) =>
      ["attendance", workspaceId, "mine", normalizeQueryKeyParams(params)] as const,
    team: (workspaceId: string, params?: QueryKeyParams | null) =>
      ["attendance", workspaceId, "team", normalizeQueryKeyParams(params)] as const,
  },
  salesWizard,
  attachRules,
  estimator,
  adLibrary: {
    ...adAdvertisers,
    advertisers: (workspaceId: string, params?: QueryKeyParams | null) =>
      adAdvertisers.list(workspaceId, params),
    advertiser: (workspaceId: string, advertiserId: string) =>
      adAdvertisers.detail(workspaceId, advertiserId),
    job: (workspaceId: string, jobId: string) => ["ad-library-job", workspaceId, jobId] as const,
    monitors: (workspaceId: string) => ["ad-library-monitors", workspaceId] as const,
  },
  people: {
    search: (workspaceId: string, params?: QueryKeyParams | null) =>
      ["people-search", workspaceId, params ?? null] as const,
    prospectSignals: (workspaceId: string, prospectId: string) =>
      ["prospect-signals", workspaceId, prospectId] as const,
    job: (workspaceId: string, jobId: string) =>
      ["people-discovery-job", workspaceId, jobId] as const,
    missions: (workspaceId: string) => ["people-missions", workspaceId] as const,
  },
  addresses: {
    // Keyed on the typed text, so backtracking a character replays a cached
    // answer instead of re-billing the provider for a query already asked.
    suggest: (workspaceId: string, query: string) =>
      ["addresses", workspaceId, "suggest", query] as const,
  },
  agents: {
    ...agents,
    activeOnly: (workspaceId: string) => agents.list(workspaceId, { active_only: true }),
    versions: (workspaceId: string, agentId: string) =>
      [...agents.detail(workspaceId, agentId), "versions"] as const,
    promptVersions: (workspaceId: string, agentId: string) =>
      ["promptVersions", workspaceId, agentId] as const,
    promptVersionsAll: () => ["promptVersions"] as const,
    promptVersionComparison: (workspaceId: string, agentId: string) =>
      ["promptVersionComparison", workspaceId, agentId] as const,
    promptVersionComparisonAll: () => ["promptVersionComparison"] as const,
    humanProfile: (workspaceId: string, agentId: string) =>
      [...agents.detail(workspaceId, agentId), "human-profile"] as const,
    knowledgeDocs: (workspaceId: string, agentId: string) =>
      [...agents.detail(workspaceId, agentId), "knowledge-documents"] as const,
    embed: (workspaceId: string, agentId: string) =>
      [...agents.detail(workspaceId, agentId), "embed"] as const,
  },
  assistant: {
    all: (workspaceId: string) => ["assistant", workspaceId] as const,
    conversations: (workspaceId: string) => ["assistant", workspaceId, "conversations"] as const,
    conversation: (workspaceId: string, conversationId: string) =>
      ["assistant", workspaceId, "conversation", conversationId] as const,
    history: (workspaceId: string) => ["assistant", workspaceId, "history"] as const,
  },
  appointments: {
    ...appointments,
    stats: (workspaceId: string) => [...appointments.all(workspaceId), "stats"] as const,
    byContact: (workspaceId: string, contactId: number | string | undefined) =>
      appointments.list(workspaceId, { contact_id: contactId }),
  },
  auth: {
    currentUser: () => ["auth", "currentUser"] as const,
    session: () => ["auth", "session"] as const,
    user: () => ["user"] as const,
  },
  automations: {
    ...automations,
    stats: (workspaceId: string) => [...automations.all(workspaceId), "stats"] as const,
  },
  billing: {
    all: (workspaceId: string) => ["billing", workspaceId] as const,
    status: () => ["billing-status"] as const,
    subscription: (workspaceId: string) => ["billing", workspaceId, "subscription"] as const,
    invoices: (workspaceId: string) => ["billing", workspaceId, "invoices"] as const,
    usage: (workspaceId: string) => ["billing", workspaceId, "usage"] as const,
  },
  calls: {
    ...calls,
    listFiltered: (workspaceId: string, direction: string, status: string, search: string) =>
      calls.list(workspaceId, { direction, search, status }),
    transcript: (workspaceId: string, callId: string) =>
      [...calls.detail(workspaceId, callId), "transcript"] as const,
    live: (workspaceId: string) => [...calls.all(workspaceId), "live"] as const,
  },
  campaignReports: {
    ...campaignReports,
    full: (workspaceId: string, reportIds: readonly string[]) =>
      [...campaignReports.all(workspaceId), "full", reportIds] as const,
    count: (workspaceId: string) => [...campaignReports.all(workspaceId), "count"] as const,
  },
  catalogItems,
  campaigns: {
    ...campaigns,
    analytics: (workspaceId: string, campaignId: string) =>
      [...campaigns.detail(workspaceId, campaignId), "analytics"] as const,
    guaranteeProgress: (workspaceId: string, campaignId: string) =>
      [...campaigns.detail(workspaceId, campaignId), "guarantee-progress"] as const,
  },
  contacts: {
    ...contacts,
    stats: (workspaceId: string) => [...contacts.all(workspaceId), "stats"] as const,
    /** Full contact roster fetched by paging through the list endpoint. */
    allRecords: (workspaceId: string) => [...contacts.all(workspaceId), "all-records"] as const,
    ids: (workspaceId: string, params: QueryKeyParams) =>
      [...contacts.all(workspaceId), "ids", normalizeQueryKeyParams(params)] as const,
    infinite: (workspaceId: string | null, filters: QueryKeyParams) =>
      ["contacts", workspaceId, "infinite", normalizeQueryKeyParams(filters)] as const,
    search: (workspaceId: string, term: string) =>
      [...contacts.all(workspaceId), "search", term] as const,
    aiState: (workspaceId: string, contactId: number | string) =>
      [...contacts.detail(workspaceId, contactId), "ai-state"] as const,
    aiKnowledge: (workspaceId: string, contactId: number | string) =>
      [...contacts.detail(workspaceId, contactId), "ai-knowledge"] as const,
    companycamPhotos: (workspaceId: string, contactId: number | string) =>
      [...contacts.detail(workspaceId, contactId), "companycam-photos"] as const,
    attachments: (workspaceId: string, contactId: number | string) =>
      [...contacts.detail(workspaceId, contactId), "attachments"] as const,
    timeline: (
      workspaceId: string,
      contactId: number | string | null | undefined,
      limit?: number,
      conversationId?: string,
    ) =>
      limit === undefined && conversationId === undefined
        ? (["contacts", workspaceId, contactId ?? null, "timeline"] as const)
        : ([
            "contacts",
            workspaceId,
            contactId ?? null,
            "timeline",
            {
              ...(limit === undefined ? {} : { limit }),
              ...(conversationId === undefined ? {} : { conversation_id: conversationId }),
            },
          ] as const),
    conversations: (workspaceId: string, contactId: string) =>
      [...contacts.detail(workspaceId, contactId), "conversations"] as const,
    tags: (workspaceId: string, contactId: string) =>
      [...contacts.detail(workspaceId, contactId), "tags"] as const,
    engagementSummary: (workspaceId: string, contactId: string) =>
      [...contacts.detail(workspaceId, contactId), "engagement-summary"] as const,
    jobTime: (workspaceId: string, contactId: number | string) =>
      [...contacts.detail(workspaceId, contactId), "job-time"] as const,
  },
  conversations: {
    ...conversations,
    byContact: (workspaceId: string, contactId: number | string | undefined | null) =>
      conversations.list(workspaceId, {
        contact_id: contactId ?? null,
        page: 1,
        page_size: 100,
      }),
    messages: (workspaceId: string, conversationId: string) =>
      [...conversations.detail(workspaceId, conversationId), "messages"] as const,
    notes: (workspaceId: string, conversationId: string) =>
      [...conversations.detail(workspaceId, conversationId), "notes"] as const,
    followupSettings: (workspaceId: string, conversationId: string) =>
      [...conversations.detail(workspaceId, conversationId), "followup-settings"] as const,
    unreadSummary: (workspaceId: string) =>
      [...conversations.all(workspaceId), "unread-summary"] as const,
  },
  dripCampaigns,
  dashboard: {
    all: (workspaceId: string) => ["dashboard", workspaceId] as const,
    stats: (workspaceId: string) => ["dashboard", workspaceId, "stats"] as const,
    activity: (workspaceId: string) => ["dashboard", workspaceId, "activity"] as const,
    revenue: (workspaceId: string) => ["dashboard", workspaceId, "revenue"] as const,
    outboundGrowth: (workspaceId: string) => ["dashboard", workspaceId, "outbound-growth"] as const,
    todayQueue: (workspaceId: string) => ["dashboard", workspaceId, "today-queue"] as const,
  },
  findLeadsAi: createResourceQueryKeys("find-leads-ai"),
  humanProfiles: createResourceQueryKeys("human-profiles"),
  improvementSuggestions: {
    ...improvementSuggestions,
    pendingCount: (workspaceId: string) =>
      [...improvementSuggestions.all(workspaceId), "pending-count"] as const,
    stats: (workspaceId: string) => [...improvementSuggestions.all(workspaceId), "stats"] as const,
  },
  integrations: {
    ...integrations,
    openAIOAuth: (workspaceId: string) =>
      [...integrations.all(workspaceId), "openai-oauth"] as const,
  },
  invitations: {
    ...invitations,
    byToken: (token: string) => ["invitation", token] as const,
  },
  inventory: {
    ...inventoryItems,
    ledger: (workspaceId: string, itemId: string, params?: QueryKeyParams | null) =>
      [
        ...inventoryItems.detail(workspaceId, itemId),
        "ledger",
        normalizeQueryKeyParams(params),
      ] as const,
    reorderSuggestion: (workspaceId: string, itemId: string) =>
      [...inventoryItems.detail(workspaceId, itemId), "reorder-suggestion"] as const,
    stock: (workspaceId: string, params?: QueryKeyParams | null) =>
      ["inventory-stock", workspaceId, normalizeQueryKeyParams(params)] as const,
    reorderReport: (workspaceId: string, params?: QueryKeyParams | null) =>
      ["inventory-reorder-report", workspaceId, normalizeQueryKeyParams(params)] as const,
    locations: (workspaceId: string, params?: QueryKeyParams | null) =>
      ["inventory-locations", workspaceId, normalizeQueryKeyParams(params)] as const,
  },
  invoices,
  jobs: {
    ...jobs,
    materials: (workspaceId: string, jobId: string) =>
      [...jobs.detail(workspaceId, jobId), "materials"] as const,
    crews: (workspaceId: string) => [...jobs.all(workspaceId), "crews"] as const,
    installationPlan: (workspaceId: string, jobId: string) =>
      [...jobs.detail(workspaceId, jobId), "installation-plan"] as const,
    handoffImages: (workspaceId: string, jobId: string) =>
      [...jobs.detail(workspaceId, jobId), "handoff-images"] as const,
    inventoryPlan: (workspaceId: string, jobId: string) =>
      [...jobs.detail(workspaceId, jobId), "inventory-plan"] as const,
    visits: (workspaceId: string, jobId: string) =>
      [...jobs.detail(workspaceId, jobId), "visits"] as const,
    pricing: (workspaceId: string, jobId: string) =>
      [...jobs.detail(workspaceId, jobId), "pricing"] as const,
    mine: (workspaceId: string, params?: QueryKeyParams | null) =>
      [...jobs.all(workspaceId), "mine", normalizeQueryKeyParams(params)] as const,
    timeEntries: (workspaceId: string, jobId: string) =>
      [...jobs.detail(workspaceId, jobId), "time-entries"] as const,
    expenses: (workspaceId: string, jobId: string) =>
      [...jobs.detail(workspaceId, jobId), "expenses"] as const,
    profitability: (workspaceId: string, jobId: string) =>
      [...jobs.detail(workspaceId, jobId), "profitability"] as const,
    neighbors: (workspaceId: string, jobId: string) =>
      [...jobs.detail(workspaceId, jobId), "neighbors"] as const,
  },
  servicePlans: {
    ...servicePlans,
  },
  reports: {
    arAging: (workspaceId: string, asOf?: string) =>
      ["reports", workspaceId, "ar-aging", asOf ?? null] as const,
    jobPnl: (workspaceId: string, params?: QueryKeyParams | null) =>
      ["reports", workspaceId, "job-pnl", normalizeQueryKeyParams(params)] as const,
    attributionGap: (workspaceId: string, params?: QueryKeyParams | null) =>
      ["reports", workspaceId, "attribution-gap", normalizeQueryKeyParams(params)] as const,
    salesPerformance: (workspaceId: string, params?: QueryKeyParams | null) =>
      ["reports", workspaceId, "sales-performance", normalizeQueryKeyParams(params)] as const,
    cogs: (workspaceId: string, params?: QueryKeyParams | null) =>
      ["reports", workspaceId, "cogs", normalizeQueryKeyParams(params)] as const,
  },
  knowledgeDocuments: createResourceQueryKeys("knowledge-documents"),
  leadMagnets,
  lightingProjects,
  leadSources: {
    ...leadSources,
    campaigns: (workspaceId: string, leadSourceId: string) =>
      [...leadSources.detail(workspaceId, leadSourceId), "campaigns"] as const,
    spend: (workspaceId: string, params?: QueryKeyParams | null) =>
      [...leadSources.all(workspaceId), "spend", normalizeQueryKeyParams(params)] as const,
    unattributed: (workspaceId: string) =>
      [...leadSources.all(workspaceId), "unattributed"] as const,
    captureSettings: (workspaceId: string) =>
      [...leadSources.all(workspaceId), "capture-settings"] as const,
  },
  messageTemplates,
  messageTests: {
    ...messageTests,
    analytics: (workspaceId: string, testId: string) =>
      [...messageTests.detail(workspaceId, testId), "analytics"] as const,
  },
  referralPartners: {
    ...referralPartners,
    scoreboard: (workspaceId: string, params?: QueryKeyParams | null) =>
      [
        ...referralPartners.all(workspaceId),
        "scoreboard",
        normalizeQueryKeyParams(params),
      ] as const,
    publicIntake: (instanceId: string) => ["public-intake", instanceId] as const,
  },
  nudges: {
    ...nudges,
    stats: (workspaceId: string) => [...nudges.all(workspaceId), "stats"] as const,
    settings: (workspaceId: string) => ["nudge-settings", workspaceId] as const,
  },
  offers,
  opportunities: {
    ...opportunities,
    pipelines: (workspaceId: string) => [...opportunities.all(workspaceId), "pipelines"] as const,
  },
  pendingActions: {
    ...pendingActions,
    count: (workspaceId: string) => [...pendingActions.all(workspaceId), "count"] as const,
    stats: (workspaceId: string) => [...pendingActions.all(workspaceId), "stats"] as const,
  },
  preBooking,
  phoneNumbers: {
    ...phoneNumbers,
    smsEnabled: (workspaceId: string) => phoneNumbers.list(workspaceId, { sms_enabled: true }),
    activeTextCapable: (workspaceId: string) =>
      phoneNumbers.list(workspaceId, { active_only: true, text_capable: true }),
    activeOnlyFalse: (workspaceId: string) =>
      phoneNumbers.list(workspaceId, { active_only: false }),
    inboundReadiness: (workspaceId: string, phoneNumberId: string) =>
      [...phoneNumbers.detail(workspaceId, phoneNumberId), "inbound-readiness"] as const,
  },
  promptVersions: createResourceQueryKeys("prompt-versions"),
  revenueTargets: {
    ...revenueTargets,
    /** One calendar year of monthly targets — the seasonal planning screen. */
    byYear: (workspaceId: string, year: number) => revenueTargets.list(workspaceId, { year }),
    /** Month-pace report; `month` is any date in the month, null = this month. */
    pace: (workspaceId: string, month?: string | null) =>
      [...revenueTargets.all(workspaceId), "pace", month ?? null] as const,
  },
  quotes: {
    ...quotes,
    byContact: (workspaceId: string, contactId: number | string | undefined) =>
      quotes.list(workspaceId, { contact_id: contactId }),
    handoffImages: (workspaceId: string, quoteId: string) =>
      [...quotes.detail(workspaceId, quoteId), "handoff-images"] as const,
  },
  proposalTemplate: {
    settings: (workspaceId: string) => ["proposal-template", workspaceId] as const,
  },
  publicProposals: {
    all: () => ["public-proposals"] as const,
    byToken: (token: string) => ["public-proposals", token] as const,
  },
  publicInvoices: {
    all: () => ["public-invoices"] as const,
    byToken: (token: string) => ["public-invoices", token] as const,
  },
  publicComparisons: {
    all: () => ["public-comparisons"] as const,
    byToken: (token: string) => ["public-comparisons", token] as const,
  },
  reviews: {
    ...reviews,
    summary: (workspaceId: string) => [...reviews.all(workspaceId), "summary"] as const,
    settings: (workspaceId: string) => [...reviews.all(workspaceId), "settings"] as const,
    requests: (workspaceId: string, params?: QueryKeyParams | null) =>
      [...reviews.all(workspaceId), "requests", normalizeQueryKeyParams(params)] as const,
  },
  publicReviews: {
    all: () => ["public-reviews"] as const,
    byToken: (token: string) => ["public-reviews", token] as const,
  },
  publicDemo: {
    all: () => ["public-demo"] as const,
    detail: (slug: string) => ["public-demo", "detail", slug] as const,
  },
  publicOffers: {
    all: () => ["public-offers"] as const,
    detail: (slug: string) => ["public-offers", "detail", slug] as const,
    bySlug: (slug: string) => ["public-offer", slug] as const,
  },
  roleplay: {
    all: (workspaceId: string) => ["roleplay", workspaceId] as const,
    personas: (workspaceId: string) => ["roleplay", workspaceId, "personas"] as const,
    runs: (workspaceId: string, params?: QueryKeyParams | null) =>
      ["roleplay", workspaceId, "runs", normalizeQueryKeyParams(params)] as const,
    run: (workspaceId: string, runId: string) => ["roleplay", workspaceId, "run", runId] as const,
  },
  scorecard: {
    all: (workspaceId: string) => ["scorecard", workspaceId] as const,
    range: (workspaceId: string, params?: QueryKeyParams | null) =>
      ["scorecard", workspaceId, normalizeQueryKeyParams(params)] as const,
    technicians: (workspaceId: string, params?: QueryKeyParams | null) =>
      ["scorecard", workspaceId, "technicians", normalizeQueryKeyParams(params)] as const,
  },
  technicianScoreboard: {
    all: (workspaceId: string) => ["technician-scoreboard", workspaceId] as const,
    detail: (workspaceId: string, technicianId: string) =>
      ["technician-scoreboard", workspaceId, "technicians", technicianId] as const,
  },
  scraping: createResourceQueryKeys("scraping"),
  segments: {
    ...segments,
    contacts: (workspaceId: string, segmentId: string) =>
      [...segments.detail(workspaceId, segmentId), "contacts"] as const,
    preview: (workspaceId: string, definition: unknown) =>
      [...segments.all(workspaceId), "preview", JSON.stringify(definition ?? null)] as const,
  },
  settings: {
    all: (workspaceId: string) => ["settings", workspaceId] as const,
    detail: (workspaceId: string, section: string) =>
      ["settings", workspaceId, "detail", section] as const,
    profile: () => ["settings", "profile"] as const,
    notifications: () => ["settings", "notifications"] as const,
    team: (workspaceId: string) => ["settings", "team", workspaceId] as const,
    activeTeam: (workspaceId: string) => ["settings", "team", workspaceId, "active"] as const,
    integrations: (workspaceId: string) => ["settings", "integrations", workspaceId] as const,
    autoPipeline: (workspaceId: string) => ["settings", "auto-pipeline", workspaceId] as const,
    speedToLead: (workspaceId: string) => ["settings", "speed-to-lead", workspaceId] as const,
    speedToLeadMetrics: (workspaceId: string) =>
      ["settings", "speed-to-lead-metrics", workspaceId] as const,
    missedCallTextback: (workspaceId: string) =>
      ["settings", "missed-call-textback", workspaceId] as const,
    quoteFollowup: (workspaceId: string) =>
      ["settings", "post-estimate-followup", workspaceId] as const,
    quoteRevival: (workspaceId: string) =>
      ["settings", "unsold-quote-revival", workspaceId] as const,
    neighborOutreach: (workspaceId: string) =>
      ["settings", "neighbor-outreach", workspaceId] as const,
  },
  smsCampaigns: createResourceQueryKeys("sms-campaigns"),
  tags: createResourceQueryKeys("tags"),
  // Business locations = the company's own branches / business units.
  locations: {
    ...businessLocations,
    active: (workspaceId: string) => businessLocations.list(workspaceId, { is_active: true }),
  },
  technicians: {
    ...technicians,
    active: (workspaceId: string) => technicians.list(workspaceId, { is_active: true }),
  },
  // Who in the workspace has a booking calendar. Read by Settings → Team, which
  // toggles the `bookable_staff.user_id` link that puts appointments on a
  // member's own calendar.
  bookableStaff: createResourceQueryKeys("bookable-staff"),
  // On-site upsell: the technician's own jobs and the attachable add-on menu.
  // Keyed separately from `jobs`/`catalogItems` because these are different,
  // server-scoped projections of those resources, not cacheable as the same data.
  upsell: {
    all: (workspaceId: string) => ["upsell", workspaceId] as const,
    jobs: (workspaceId: string) => ["upsell", workspaceId, "jobs"] as const,
    customer: (workspaceId: string, jobId: string) =>
      ["upsell", workspaceId, "jobs", jobId, "customer"] as const,
    catalog: (workspaceId: string, attachTarget?: string | null) =>
      ["upsell", workspaceId, "catalog", attachTarget ?? null] as const,
    // Keyed by fixture count: the price is a function of it, so two counts are
    // genuinely different data rather than a filtered view of one list.
    carePlans: (workspaceId: string, fixtureCount: number) =>
      ["upsell", workspaceId, "care-plans", fixtureCount] as const,
    // Self-scoped by the server; no user id in the key because the endpoint has
    // no user parameter and the auth token already decides whose stats these are.
    myStats: (workspaceId: string) => ["upsell", workspaceId, "my-stats"] as const,
  },
  voiceCampaigns: createResourceQueryKeys("voice-campaigns"),
  workspaces: {
    all: () => ["workspaces"] as const,
    detail: (workspaceId: string) => ["workspaces", workspaceId] as const,
    members: (workspaceId: string) => ["workspaces", workspaceId, "members"] as const,
  },
} as const;
