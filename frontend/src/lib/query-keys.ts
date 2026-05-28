/**
 * Centralized React Query key factory.
 *
 * Inspired by TkDodo's "Effective React Query Keys" — each resource exposes
 * builder functions that return `readonly` tuples, so invalidation, prefetch,
 * and cache access all share a single source of truth.
 *
 * @example
 * ```ts
 * import { queryKeys } from "@/lib/query-keys";
 *
 * useQuery({
 *   queryKey: queryKeys.contacts.detail(workspaceId, contactId),
 *   queryFn: () => fetchContact(contactId),
 * });
 *
 * // Invalidate every contact query for a workspace
 * queryClient.invalidateQueries({ queryKey: queryKeys.contacts.all(workspaceId) });
 * ```
 *
 * RULE: never hand-write a `queryKey: [...]` literal. Add a builder here
 * instead. The `no-restricted-syntax` ESLint rule enforces this.
 */

type Key = readonly unknown[];

const resource = <Name extends string>(name: Name) => ({
  all: (workspaceId: string) => [name, workspaceId] as const,
  list: (workspaceId: string, params?: Record<string, unknown>) =>
    (params ? ([name, workspaceId, "list", params] as const) : ([name, workspaceId, "list"] as const)) as Key,
  detail: (workspaceId: string, id: string) => [name, workspaceId, "detail", id] as const,
});

export const queryKeys = {
  agents: {
    ...resource("agents"),
    /** Bare `["agents", workspaceId]` — matches what `createResourceHooks` emits for `useList`/`useGet`. */
    bare: (workspaceId: string) => ["agents", workspaceId] as const,
    /** `["agents", workspaceId, id]` — matches `createResourceHooks` `useGet` shape. */
    get: (workspaceId: string, agentId: string) => ["agents", workspaceId, agentId] as const,
    /** `["agents", workspaceId, params]` — matches `createResourceHooks` `useList` with params. */
    listWith: (workspaceId: string, params: object) =>
      ["agents", workspaceId, params] as const,
    activeOnly: (workspaceId: string) =>
      ["agents", workspaceId, { active_only: true }] as const,
    versions: (workspaceId: string, agentId: string) =>
      ["agents", workspaceId, "detail", agentId, "versions"] as const,
    promptVersions: (workspaceId: string, agentId: string) =>
      ["promptVersions", workspaceId, agentId] as const,
    promptVersionsAll: () => ["promptVersions"] as const,
    promptVersionComparison: (workspaceId: string, agentId: string) =>
      ["promptVersionComparison", workspaceId, agentId] as const,
    promptVersionComparisonAll: () => ["promptVersionComparison"] as const,
    humanProfile: (workspaceId: string, agentId: string) =>
      ["humanProfile", workspaceId, agentId] as const,
    knowledgeDocs: (workspaceId: string, agentId: string) =>
      ["knowledgeDocs", workspaceId, agentId] as const,
    embed: (workspaceId: string, agentId: string) =>
      ["agent-embed", workspaceId, agentId] as const,
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
    ...resource("appointments"),
    /** Bare `["appointments", workspaceId]` — `createResourceHooks` `useList` shape. */
    bare: (workspaceId: string) => ["appointments", workspaceId] as const,
    listWith: (workspaceId: string, params: object) =>
      ["appointments", workspaceId, params] as const,
    stats: (workspaceId: string) => ["appointments", "stats", workspaceId] as const,
    byContact: (workspaceId: string, contactId: number | string | undefined) =>
      ["appointments", workspaceId, { contact_id: contactId }] as const,
  },
  auth: {
    currentUser: () => ["auth", "currentUser"] as const,
    session: () => ["auth", "session"] as const,
    user: () => ["user"] as const,
  },
  automations: {
    ...resource("automations"),
    bare: (workspaceId: string) => ["automations", workspaceId] as const,
    root: () => ["automations"] as const,
    stats: (workspaceId: string) => ["automationStats", workspaceId] as const,
  },
  billing: {
    all: (workspaceId: string) => ["billing", workspaceId] as const,
    status: () => ["billing-status"] as const,
    subscription: (workspaceId: string) => ["billing", workspaceId, "subscription"] as const,
    invoices: (workspaceId: string) => ["billing", workspaceId, "invoices"] as const,
    usage: (workspaceId: string) => ["billing", workspaceId, "usage"] as const,
  },
  calls: {
    ...resource("calls"),
    listFiltered: (
      workspaceId: string,
      direction: string,
      status: string,
      search: string,
    ) => ["calls", workspaceId, direction, status, search] as const,
    transcript: (workspaceId: string, callId: string) =>
      ["calls", workspaceId, "detail", callId, "transcript"] as const,
  },
  campaignReports: {
    ...resource("campaign-reports"),
    list: (workspaceId: string) => ["campaignReports", workspaceId] as const,
    full: (workspaceId: string, reportIds: readonly string[]) =>
      ["campaignReportsFull", workspaceId, reportIds] as const,
    count: (workspaceId: string) => ["campaignReportsCount", workspaceId] as const,
  },
  campaigns: {
    ...resource("campaigns"),
    bare: (workspaceId: string) => ["campaigns", workspaceId] as const,
    get: (workspaceId: string, campaignId: string) =>
      ["campaigns", workspaceId, campaignId] as const,
    analytics: (workspaceId: string, campaignId: string) =>
      ["campaignAnalytics", workspaceId, campaignId] as const,
    guaranteeProgress: (workspaceId: string, campaignId: string) =>
      ["guarantee-progress", workspaceId, campaignId] as const,
  },
  contacts: {
    ...resource("contacts"),
    bare: (workspaceId: string) => ["contacts", workspaceId] as const,
    listWith: (workspaceId: string, params: object) =>
      ["contacts", workspaceId, params] as const,
    ids: (workspaceId: string, params: object) =>
      ["contact-ids", workspaceId, params] as const,
    infinite: (workspaceId: string | null, filters: Record<string, unknown>) =>
      ["contacts-infinite", workspaceId, filters] as const,
    aiState: (workspaceId: string, contactId: number | string) =>
      ["contact-ai-state", workspaceId, contactId] as const,
    timeline: (workspaceId: string, contactId: string) =>
      ["contacts", workspaceId, "detail", contactId, "timeline"] as const,
    /** Legacy timeline key used by `useContactTimeline` and consumers that poll it. */
    timelineLegacy: (
      workspaceId: string,
      contactId: number | string | null | undefined,
      limit?: number,
    ) =>
      (limit === undefined
        ? (["contact-timeline", workspaceId, contactId] as const)
        : (["contact-timeline", workspaceId, contactId, limit] as const)) as Key,
    conversations: (workspaceId: string, contactId: string) =>
      ["contacts", workspaceId, "detail", contactId, "conversations"] as const,
    tags: (workspaceId: string, contactId: string) =>
      ["contacts", workspaceId, "detail", contactId, "tags"] as const,
    engagementSummary: (workspaceId: string, contactId: string) =>
      ["contacts", workspaceId, "detail", contactId, "engagement-summary"] as const,
  },
  conversations: {
    ...resource("conversations"),
    bare: (workspaceId: string) => ["conversations", workspaceId] as const,
    byContact: (workspaceId: string, contactId: number | string | undefined | null) =>
      ["conversations", workspaceId, contactId] as const,
    detail: (workspaceId: string, conversationId: string) =>
      ["conversation", workspaceId, conversationId] as const,
    detailAll: () => ["conversation"] as const,
    messages: (workspaceId: string, conversationId: string) =>
      ["conversations", workspaceId, "detail", conversationId, "messages"] as const,
    followupSettings: (workspaceId: string, conversationId: string) =>
      ["followup-settings", workspaceId, conversationId] as const,
  },
  dashboard: {
    all: (workspaceId: string) => ["dashboard", workspaceId] as const,
    stats: (workspaceId: string) => ["dashboard", workspaceId, "stats"] as const,
    activity: (workspaceId: string) => ["dashboard", workspaceId, "activity"] as const,
    outboundGrowth: (workspaceId: string) =>
      ["dashboard", workspaceId, "outbound-growth"] as const,
  },
  findLeadsAi: resource("find-leads-ai"),
  humanProfiles: resource("human-profiles"),
  improvementSuggestions: {
    ...resource("improvement-suggestions"),
    list: (workspaceId: string, agentId: string | null | undefined, statusFilter: string) =>
      ["improvementSuggestions", workspaceId, agentId ?? null, statusFilter] as const,
    pendingCount: (workspaceId: string) =>
      ["suggestionsPendingCount", workspaceId] as const,
    stats: (workspaceId: string) => ["suggestionsStats", workspaceId] as const,
    root: () => ["improvementSuggestions"] as const,
  },
  integrations: {
    ...resource("integrations"),
    bare: (workspaceId: string) => ["integrations", workspaceId] as const,
    openAIOAuth: (workspaceId: string) => ["integrations", workspaceId, "openai-oauth"] as const,
  },
  invitations: {
    ...resource("invitations"),
    bare: (workspaceId: string) => ["invitations", workspaceId] as const,
    byToken: (token: string) => ["invitation", token] as const,
  },
  knowledgeDocuments: resource("knowledge-documents"),
  leadMagnets: {
    ...resource("lead-magnets"),
    bare: (workspaceId: string) => ["lead-magnets", workspaceId] as const,
  },
  leadSources: {
    ...resource("lead-sources"),
    bare: (workspaceId: string) => ["lead-sources", workspaceId] as const,
  },
  messageTemplates: {
    ...resource("message-templates"),
    bare: (workspaceId: string) => ["message-templates", workspaceId] as const,
  },
  messageTests: {
    ...resource("message-tests"),
    bare: (workspaceId: string) => ["message-tests", workspaceId] as const,
    get: (workspaceId: string, testId: string) =>
      ["message-test", workspaceId, testId] as const,
    analytics: (workspaceId: string, testId: string) =>
      ["message-test-analytics", workspaceId, testId] as const,
  },
  nudges: {
    ...resource("nudges"),
    list: (workspaceId: string, statusFilter: string, page: number) =>
      ["nudges", workspaceId, statusFilter, page] as const,
    root: () => ["nudges"] as const,
    stats: (workspaceId: string) => ["nudgeStats", workspaceId] as const,
    statsRoot: () => ["nudgeStats"] as const,
    settings: (workspaceId: string) => ["nudge-settings", workspaceId] as const,
  },
  offers: {
    ...resource("offers"),
    bare: (workspaceId: string) => ["offers", workspaceId] as const,
    get: (workspaceId: string, offerId: string) =>
      ["offers", workspaceId, offerId] as const,
  },
  opportunities: {
    ...resource("opportunities"),
    bare: (workspaceId: string) => ["opportunities", workspaceId] as const,
    list: (workspaceId: string, page: number, search: string) =>
      ["opportunities", workspaceId, page, search] as const,
    get: (workspaceId: string, opportunityId: string | undefined) =>
      ["opportunity", workspaceId, opportunityId] as const,
    pipelines: (workspaceId: string) => ["pipelines", workspaceId] as const,
  },
  pendingActions: {
    ...resource("pending-actions"),
    list: (workspaceId: string, statusFilter: string, page: number) =>
      ["pendingActions", workspaceId, statusFilter, page] as const,
    root: () => ["pendingActions"] as const,
    count: (workspaceId: string) => ["pending-actions", workspaceId, "count"] as const,
    stats: (workspaceId: string) => ["pendingActionStats", workspaceId] as const,
    statsRoot: () => ["pendingActionStats"] as const,
  },
  phoneNumbers: {
    ...resource("phone-numbers"),
    bare: (workspaceId: string) => ["phone-numbers", workspaceId] as const,
    listWith: (workspaceId: string, params: object) =>
      ["phone-numbers", workspaceId, params] as const,
    smsEnabled: (workspaceId: string) =>
      ["phone-numbers", workspaceId, { sms_enabled: true }] as const,
    activeOnlyFalse: (workspaceId: string) =>
      ["phone-numbers", workspaceId, { active_only: false }] as const,
    detail: (workspaceId: string, phoneNumberId: string) =>
      ["phoneNumber", workspaceId, phoneNumberId] as const,
    /** Legacy duplicate key used in agents-list — kept until that screen is refactored. */
    legacyList: (workspaceId: string) => ["phoneNumbers", workspaceId] as const,
  },
  promptVersions: resource("prompt-versions"),
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
  scraping: resource("scraping"),
  segments: {
    ...resource("segments"),
    contacts: (workspaceId: string, segmentId: string) =>
      ["segment-contacts", workspaceId, segmentId] as const,
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
  },
  smsCampaigns: resource("sms-campaigns"),
  tags: {
    ...resource("tags"),
    bare: (workspaceId: string) => ["tags", workspaceId] as const,
  },
  voiceCampaigns: {
    ...resource("voice-campaigns"),
    bare: (workspaceId: string) => ["voice-campaigns", workspaceId] as const,
  },
  workspaces: {
    all: () => ["workspaces"] as const,
    detail: (workspaceId: string) => ["workspaces", "detail", workspaceId] as const,
    members: (workspaceId: string) => ["workspaces", "detail", workspaceId, "members"] as const,
  },
} as const;
