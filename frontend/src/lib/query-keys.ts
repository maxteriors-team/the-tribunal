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
    .map(
      ([entryKey, entryValue]) =>
        [entryKey, normalizeQueryKeyValue(entryValue)] as const,
    );

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

export function createResourceQueryKeys<Name extends string>(
  name: Name,
): ResourceQueryKeys<Name> {
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
const improvementSuggestions = createResourceQueryKeys("suggestions");
const integrations = createResourceQueryKeys("integrations");
const invitations = createResourceQueryKeys("invitations");
const invoices = createResourceQueryKeys("invoices");
const jobs = createResourceQueryKeys("jobs");
const quotes = createResourceQueryKeys("quotes");
const leadMagnets = createResourceQueryKeys("lead-magnets");
const leadSources = createResourceQueryKeys("lead-sources");
const messageTemplates = createResourceQueryKeys("message-templates");
const messageTests = createResourceQueryKeys("message-tests");
const nudges = createResourceQueryKeys("nudges");
const offers = createResourceQueryKeys("offers");
const opportunities = createResourceQueryKeys("opportunities");
const pendingActions = createResourceQueryKeys("pending-actions");
const phoneNumbers = createResourceQueryKeys("phone-numbers");
const reviews = createResourceQueryKeys("reviews");
const segments = createResourceQueryKeys("segments");
const technicians = createResourceQueryKeys("technicians");

export const queryKeys = {
  adLibrary: {
    ...adAdvertisers,
    advertisers: (workspaceId: string, params?: QueryKeyParams | null) =>
      adAdvertisers.list(workspaceId, params),
    advertiser: (workspaceId: string, advertiserId: string) =>
      adAdvertisers.detail(workspaceId, advertiserId),
    job: (workspaceId: string, jobId: string) =>
      ["ad-library-job", workspaceId, jobId] as const,
    monitors: (workspaceId: string) =>
      ["ad-library-monitors", workspaceId] as const,
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
  agents: {
    ...agents,
    activeOnly: (workspaceId: string) =>
      agents.list(workspaceId, { active_only: true }),
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
    conversations: (workspaceId: string) =>
      ["assistant", workspaceId, "conversations"] as const,
    conversation: (workspaceId: string, conversationId: string) =>
      ["assistant", workspaceId, "conversation", conversationId] as const,
    history: (workspaceId: string) => ["assistant", workspaceId, "history"] as const,
  },
  appointments: {
    ...appointments,
    stats: (workspaceId: string) =>
      [...appointments.all(workspaceId), "stats"] as const,
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
    stats: (workspaceId: string) =>
      [...automations.all(workspaceId), "stats"] as const,
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
    listFiltered: (
      workspaceId: string,
      direction: string,
      status: string,
      search: string,
    ) => calls.list(workspaceId, { direction, search, status }),
    transcript: (workspaceId: string, callId: string) =>
      [...calls.detail(workspaceId, callId), "transcript"] as const,
    live: (workspaceId: string) =>
      [...calls.all(workspaceId), "live"] as const,
  },
  campaignReports: {
    ...campaignReports,
    full: (workspaceId: string, reportIds: readonly string[]) =>
      [...campaignReports.all(workspaceId), "full", reportIds] as const,
    count: (workspaceId: string) =>
      [...campaignReports.all(workspaceId), "count"] as const,
  },
  catalogItems: {
    ...catalogItems,
    active: (workspaceId: string, params?: QueryKeyParams | null) =>
      catalogItems.list(workspaceId, params),
  },
  campaigns: {
    ...campaigns,
    analytics: (workspaceId: string, campaignId: string) =>
      [...campaigns.detail(workspaceId, campaignId), "analytics"] as const,
    guaranteeProgress: (workspaceId: string, campaignId: string) =>
      [...campaigns.detail(workspaceId, campaignId), "guarantee-progress"] as const,
  },
  contacts: {
    ...contacts,
    ids: (workspaceId: string, params: QueryKeyParams) =>
      [...contacts.all(workspaceId), "ids", normalizeQueryKeyParams(params)] as const,
    infinite: (workspaceId: string | null, filters: QueryKeyParams) =>
      ["contacts", workspaceId, "infinite", normalizeQueryKeyParams(filters)] as const,
    search: (workspaceId: string, term: string) =>
      [...contacts.all(workspaceId), "search", term] as const,
    aiState: (workspaceId: string, contactId: number | string) =>
      [...contacts.detail(workspaceId, contactId), "ai-state"] as const,
    timeline: (
      workspaceId: string,
      contactId: number | string | null | undefined,
      limit?: number,
    ) =>
      limit === undefined
        ? (["contacts", workspaceId, contactId ?? null, "timeline"] as const)
        : ([
            "contacts",
            workspaceId,
            contactId ?? null,
            "timeline",
            { limit },
          ] as const),
    conversations: (workspaceId: string, contactId: string) =>
      [...contacts.detail(workspaceId, contactId), "conversations"] as const,
    tags: (workspaceId: string, contactId: string) =>
      [...contacts.detail(workspaceId, contactId), "tags"] as const,
    engagementSummary: (workspaceId: string, contactId: string) =>
      [...contacts.detail(workspaceId, contactId), "engagement-summary"] as const,
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
    followupSettings: (workspaceId: string, conversationId: string) =>
      [...conversations.detail(workspaceId, conversationId), "followup-settings"] as const,
  },
  dashboard: {
    all: (workspaceId: string) => ["dashboard", workspaceId] as const,
    stats: (workspaceId: string) => ["dashboard", workspaceId, "stats"] as const,
    activity: (workspaceId: string) => ["dashboard", workspaceId, "activity"] as const,
    revenue: (workspaceId: string) => ["dashboard", workspaceId, "revenue"] as const,
    outboundGrowth: (workspaceId: string) =>
      ["dashboard", workspaceId, "outbound-growth"] as const,
    todayQueue: (workspaceId: string) =>
      ["dashboard", workspaceId, "today-queue"] as const,
  },
  findLeadsAi: createResourceQueryKeys("find-leads-ai"),
  humanProfiles: createResourceQueryKeys("human-profiles"),
  improvementSuggestions: {
    ...improvementSuggestions,
    pendingCount: (workspaceId: string) =>
      [...improvementSuggestions.all(workspaceId), "pending-count"] as const,
    stats: (workspaceId: string) =>
      [...improvementSuggestions.all(workspaceId), "stats"] as const,
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
  invoices,
  jobs: {
    ...jobs,
    mine: (workspaceId: string, params?: QueryKeyParams | null) =>
      [...jobs.all(workspaceId), "mine", normalizeQueryKeyParams(params)] as const,
  },
  knowledgeDocuments: createResourceQueryKeys("knowledge-documents"),
  leadMagnets,
  leadSources: {
    ...leadSources,
    campaigns: (workspaceId: string, leadSourceId: string) =>
      [...leadSources.detail(workspaceId, leadSourceId), "campaigns"] as const,
    spend: (workspaceId: string, params?: QueryKeyParams | null) =>
      [...leadSources.all(workspaceId), "spend", normalizeQueryKeyParams(params)] as const,
    unattributed: (workspaceId: string) =>
      [...leadSources.all(workspaceId), "unattributed"] as const,
  },
  messageTemplates,
  messageTests: {
    ...messageTests,
    analytics: (workspaceId: string, testId: string) =>
      [...messageTests.detail(workspaceId, testId), "analytics"] as const,
  },
  nudges: {
    ...nudges,
    stats: (workspaceId: string) => [...nudges.all(workspaceId), "stats"] as const,
    settings: (workspaceId: string) => ["nudge-settings", workspaceId] as const,
  },
  offers,
  opportunities: {
    ...opportunities,
    pipelines: (workspaceId: string) =>
      [...opportunities.all(workspaceId), "pipelines"] as const,
    coach: (workspaceId: string, opportunityId: string) =>
      [...opportunities.detail(workspaceId, opportunityId), "coach"] as const,
    atRisk: (workspaceId: string, params?: QueryKeyParams | null) =>
      [...opportunities.all(workspaceId), "at-risk", params ?? null] as const,
  },
  pendingActions: {
    ...pendingActions,
    count: (workspaceId: string) =>
      [...pendingActions.all(workspaceId), "count"] as const,
    stats: (workspaceId: string) =>
      [...pendingActions.all(workspaceId), "stats"] as const,
  },
  phoneNumbers: {
    ...phoneNumbers,
    smsEnabled: (workspaceId: string) =>
      phoneNumbers.list(workspaceId, { sms_enabled: true }),
    activeTextCapable: (workspaceId: string) =>
      phoneNumbers.list(workspaceId, { active_only: true, text_capable: true }),
    activeOnlyFalse: (workspaceId: string) =>
      phoneNumbers.list(workspaceId, { active_only: false }),
  },
  promptVersions: createResourceQueryKeys("prompt-versions"),
  quotes,
  reviews: {
    ...reviews,
    summary: (workspaceId: string) =>
      [...reviews.all(workspaceId), "summary"] as const,
    settings: (workspaceId: string) =>
      [...reviews.all(workspaceId), "settings"] as const,
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
  realtor: {
    all: (workspaceId: string) => ["realtor", workspaceId] as const,
    onboarding: (workspaceId: string) => ["realtor", workspaceId, "onboarding"] as const,
    stats: (workspaceId: string) => ["realtor-stats", workspaceId] as const,
    appointments: (workspaceId: string) =>
      ["realtor-appointments", workspaceId] as const,
  },
  roleplay: {
    all: (workspaceId: string) => ["roleplay", workspaceId] as const,
    personas: (workspaceId: string) =>
      ["roleplay", workspaceId, "personas"] as const,
    runs: (workspaceId: string, params?: QueryKeyParams | null) =>
      ["roleplay", workspaceId, "runs", normalizeQueryKeyParams(params)] as const,
    run: (workspaceId: string, runId: string) =>
      ["roleplay", workspaceId, "run", runId] as const,
  },
  scorecard: {
    all: (workspaceId: string) => ["scorecard", workspaceId] as const,
    range: (workspaceId: string, params?: QueryKeyParams | null) =>
      ["scorecard", workspaceId, normalizeQueryKeyParams(params)] as const,
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
    integrations: (workspaceId: string) =>
      ["settings", "integrations", workspaceId] as const,
    speedToLead: (workspaceId: string) =>
      ["settings", "speed-to-lead", workspaceId] as const,
    speedToLeadMetrics: (workspaceId: string) =>
      ["settings", "speed-to-lead-metrics", workspaceId] as const,
    missedCallTextback: (workspaceId: string) =>
      ["settings", "missed-call-textback", workspaceId] as const,
  },
  smsCampaigns: createResourceQueryKeys("sms-campaigns"),
  tags: createResourceQueryKeys("tags"),
  technicians: {
    ...technicians,
    active: (workspaceId: string) => technicians.list(workspaceId, { is_active: true }),
  },
  voiceCampaigns: createResourceQueryKeys("voice-campaigns"),
  workspaces: {
    all: () => ["workspaces"] as const,
    detail: (workspaceId: string) => ["workspaces", workspaceId] as const,
    members: (workspaceId: string) => ["workspaces", workspaceId, "members"] as const,
  },
} as const;
