/**
 * Sales-wizard state + server-driven pricing.
 *
 * Holds the rep's raw *selection* (client fields, fixture quantities, add-on
 * charges, care/bistro/night picks) and continuously mirrors it to the backend
 * `wizard/preview` endpoint, which returns the fully-priced `ProposalDocument`.
 * No money is ever computed here — every figure rendered by the wizard comes
 * from that document, exactly like the saved snapshot the client later sees.
 */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type { DesignerShot } from "@/components/estimator/proposal-host";
import { salesWizardApi } from "@/lib/api/sales-wizard";
import type { ServiceKey as DesignerServiceKey } from "@/lib/estimator/services";
import { queryKeys } from "@/lib/query-keys";
import { getApiErrorDetails } from "@/lib/utils/errors";
import { formatPhoneNumber } from "@/lib/utils/phone";
import type { CatalogItem, Contact } from "@/types";
import type {
  AttachWarning,
  CatalogItemResponse,
  PricingSettings,
  ProposalDocument,
  ProposalLine,
  ProposalWizardPayload,
  QuoteDetail,
  TierConfig,
  WizardClient,
} from "@/types/sales-wizard";

import { normalizeDocument, type WizardDocument, type WizardTierView } from "./document";
import { fileToResizedDataUrl } from "./image-resize";

export { fmt, fmt2 } from "./document";
export type { WizardDocument, WizardTierView } from "./document";

// ─── Product lines the unified builder can quote (canonical order) ──────────
export const CATEGORY_KEYS = [
  "landscape",
  "permanent",
  "bistro",
  "christmas",
] as const;
export type CategoryKey = (typeof CATEGORY_KEYS)[number];

// ─── Service paths (one quote = one service) ─────────────────────────────────
// Landscape lighting, year-round permanent LED track, and seasonal Christmas are
// three separate services, each owning the product lines it sells. A quote never
// spans two of them: picking a service replaces the selection rather than adding
// to it. Mirrors ``SERVICE_CATEGORIES`` in
// ``backend/app/schemas/proposal_wizard.py``.
export const SERVICE_CATEGORIES = {
  landscape: ["landscape", "bistro"],
  permanent: ["permanent"],
  christmas: ["christmas"],
} as const satisfies Record<string, readonly CategoryKey[]>;

export type ServiceKey = keyof typeof SERVICE_CATEGORIES;

export const SERVICE_KEYS = [
  "landscape",
  "permanent",
  "christmas",
] as const satisfies readonly ServiceKey[];

/** The service path a product line belongs to. */
export function serviceForCategory(key: CategoryKey): ServiceKey {
  return (
    SERVICE_KEYS.find((service) =>
      (SERVICE_CATEGORIES[service] as readonly CategoryKey[]).includes(key),
    ) ?? "landscape"
  );
}

/**
 * Which service the current selection belongs to.
 *
 * Falls back to `"landscape"` for an empty selection so the wizard always has an
 * active branch to render. The first matching service wins, which only matters
 * for a legacy cross-service draft loaded from an existing quote.
 */
export function serviceForCategories(
  keys: readonly CategoryKey[],
): ServiceKey {
  return (
    SERVICE_KEYS.find((service) =>
      keys.some((key) =>
        (SERVICE_CATEGORIES[service] as readonly CategoryKey[]).includes(key),
      ),
    ) ?? "landscape"
  );
}

// ─── Draft state shapes (inputs stay strings so typing feels native) ────────
/**
 * A recorded skip of the attach prompt, carried on the save payload.
 *
 * Held in builder state rather than passed to `save()` so it survives the rep
 * skipping the prompt and then continuing to edit: the dismissal is part of the
 * quote being built, not a property of one button press.
 */
interface AttachDismissalDraft {
  reason: string | null;
  /** Identity of the prompt this answered, so it cannot answer a later one. */
  promptKey: string;
}

/** Identity of a prompt: the job it fired on and what it asked for. */
function attachPromptKey(warning: AttachWarning | null): string | null {
  if (!warning) return null;
  return `${warning.primary_service}:${warning.suggested_categories.join(",")}`;
}

/**
 * Narrow an unknown server `details` payload to an attach warning.
 *
 * A rejected save is the one path where the warning arrives as untyped error
 * data, so it is checked structurally before the UI renders an action from it.
 */
function asAttachWarning(value: unknown): AttachWarning | null {
  if (typeof value !== "object" || value === null) return null;
  const candidate = value as Partial<AttachWarning>;
  const validMode =
    candidate.mode === "advisory" || candidate.mode === "blocking";
  if (
    typeof candidate.primary_service !== "string" ||
    typeof candidate.message !== "string" ||
    !Array.isArray(candidate.suggested_categories) ||
    !validMode
  ) {
    return null;
  }
  return candidate as AttachWarning;
}

export interface ChargeDraft {
  description: string;
  amount: string; // net the rep keeps; server grosses it up
  /**
   * Price-book item this charge came from, when it was picked rather than
   * typed. It rides to the server so the saved quote line snapshots that item's
   * `service_category` — which is what makes an attach added from the prompt
   * actually count as an attach instead of an uncategorized custom charge.
   */
  catalogItemId?: string | null;
  /**
   * Package this charge belongs to, or null/undefined for "every package" —
   * the default. Pinning it means the charge follows the tier it was sold with:
   * core drilling the Premier install needs stops inflating the Starter.
   */
  tierKey?: string | null;
}

export interface BistroDraft {
  product: "color" | "classic";
  tier: string;
  feet: string;
}

/** A rep-uploaded design mockup (downscaled data URL + optional caption). */
export interface MockupDraft {
  image: string;
  caption: string;
}

/** Hard cap on gallery images, mirrored by the backend payload validation. */
export const MAX_MOCKUPS = 8;

export interface PermanentDraft {
  feet: string;
  channels: string;
}

export interface ChristmasDraft {
  roofline_feet: string;
  // Standardized decor selection: category key -> { option key -> value }. Value
  // is a count for `each` items (trees/bushes/wreaths) and linear feet for
  // `per_ft` items (garland). Categories come from the workspace pricing config.
  items: Record<string, Record<string, number>>;
  takedown: boolean;
  storage: boolean;
  // Selected Good/Better/Best package key when the workspace sells Christmas as
  // packages (`ChristmasConfig.packages_enabled`). "" lets the server pick the
  // most-inclusive priced package; ignored entirely in the à la carte flow.
  selected_package: string;
}

const EMPTY_CHRISTMAS: ChristmasDraft = {
  roofline_feet: "",
  items: {},
  takedown: false,
  storage: false,
  selected_package: "",
};

function countsToList(
  counts: Record<string, number>,
): { key: string; quantity: number }[] {
  return Object.entries(counts)
    .filter(([, q]) => q > 0)
    .map(([key, quantity]) => ({ key, quantity }));
}

/** How a wizard deposit's value is read: percent of total, or a flat amount. */
export type DepositMode = "percentage" | "fixed";

/**
 * The Light Designer's output as the proposal carries it.
 *
 * The rep designs in the shared designer (one photo tool for every product
 * line) and can work several photos of the same job at once; the wizard keeps
 * every composited image plus the drawings themselves, so re-opening the
 * designer resumes exactly where they left off. Source photos stay in memory
 * only — the saved snapshot carries the flattened composites, never the
 * multi-megabyte originals.
 */
export interface NightPreviewState {
  /**
   * Composited "lit at night" JPEGs saved into the proposal, in the order the
   * rep built them. One job is usually several photos — front, back, walkway —
   * and the client sees every one. The first is the hero image.
   */
  images: string[];
  /**
   * Every photo the rep has open in the designer with its drawing, held in
   * memory for this session only, so leaving the designer and coming back
   * resumes the whole set rather than just the last saved shot.
   */
  shots: DesignerShot[];
  /**
   * Services the design covers. Drives the client-facing value propositions on
   * the presentation and the shared page, so a landscape + Christmas design
   * argues both cases instead of blending them into one list.
   */
  services: DesignerServiceKey[];
}

export interface ClientDraft {
  first_name: string;
  last_name: string;
  email: string;
  phone: string;
  rep_name: string;
  street: string;
  city: string;
  state: string;
  zip: string;
}

const EMPTY_CLIENT: ClientDraft = {
  first_name: "",
  last_name: "",
  email: "",
  phone: "",
  rep_name: "",
  street: "",
  city: "",
  state: "",
  zip: "",
};

/**
 * Fields that identify *who* the quote is for. Hand-editing one means this is
 * no longer the customer the rep picked, so the contact link drops rather than
 * silently filing the quote on the wrong record. The job site and rep name are
 * not identity: a quote for a second property keeps the link.
 */
const IDENTITY_FIELDS: ReadonlySet<keyof ClientDraft> = new Set([
  "first_name",
  "last_name",
  "email",
  "phone",
]);

const PREVIEW_DEBOUNCE_MS = 350;

function toWizardClient(draft: ClientDraft): WizardClient {
  const trim = (v: string) => v.trim() || null;
  return {
    first_name: trim(draft.first_name),
    last_name: trim(draft.last_name),
    email: trim(draft.email),
    phone: trim(draft.phone),
    rep_name: trim(draft.rep_name),
    street: trim(draft.street),
    city: trim(draft.city),
    state: trim(draft.state),
    zip: trim(draft.zip),
  };
}

type EditableQuoteDetail = QuoteDetail & {
  contact_id?: number | null;
  service_location_id?: string | null;
  opportunity_id?: string | null;
  lighting_project_id?: string | null;
  title?: string | null;
  notes?: string | null;
  terms?: string | null;
  proposal_document?: Record<string, unknown> | null;
  proposal_input?: ProposalWizardPayload | null;
  proposal_input_version?: number | null;
  wizard_edit_mode?: "update" | "revise" | null;
};

export type WizardHydrationSource = "input" | "snapshot";

interface WizardHydration {
  payload: ProposalWizardPayload;
  source: WizardHydrationSource;
}

function record(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function records(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value)
    ? value.map(record).filter((row): row is Record<string, unknown> => row !== null)
    : [];
}

function finiteNumber(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

function nullableString(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null;
}

function withCurrentQuoteLinks(
  payload: ProposalWizardPayload,
  quote: EditableQuoteDetail,
 ): ProposalWizardPayload {
  return {
    ...payload,
    attach_dismissal: null,
    contact_id: quote.contact_id ?? payload.contact_id ?? null,
    service_location_id: quote.service_location_id ?? payload.service_location_id ?? null,
    opportunity_id: quote.opportunity_id ?? payload.opportunity_id ?? null,
    lighting_project_id: quote.lighting_project_id ?? payload.lighting_project_id ?? null,
    title: quote.title ?? payload.title ?? null,
    notes: quote.notes ?? payload.notes ?? null,
    terms: quote.terms ?? payload.terms ?? null,
  };
}

/**
 * Recover the builder's raw selection. Versioned `proposal_input` is exact; the
 * document fallback exists for pre-migration quotes and is visibly labelled in
 * the UI because rendered snapshots cannot recover every historical net add-on.
 */
export function hydrationForQuote(quote: EditableQuoteDetail): WizardHydration {
  if (quote.proposal_input) {
    return {
      payload: withCurrentQuoteLinks(quote.proposal_input, quote),
      source: "input",
    };
  }

  const document = record(quote.proposal_document);
  if (!document) throw new Error("This quote was not created in the quote builder.");

  const quantityByItem = new Map<string, number>();
  for (const tier of records(document.tiers)) {
    for (const line of records(tier.lines)) {
      const itemId = nullableString(line.item_id);
      const quantity = finiteNumber(line.quantity);
      if (itemId && quantity > 0) quantityByItem.set(itemId, quantity);
    }
  }

  const categories = Array.isArray(document.categories)
    ? document.categories.filter(
        (key): key is CategoryKey =>
          typeof key === "string" && CATEGORY_KEYS.includes(key as CategoryKey),
      )
    : [];
  const bistro = record(document.bistro);
  const carePlan = record(document.care_plan);
  const nightPreview = record(document.night_preview);
  const sectionByKey = new Map(
    records(document.category_sections).map((section) => [section.key, section]),
  );

  const permanentSection = sectionByKey.get("permanent");
  const permanentLines = records(permanentSection?.lines);
  const roofline = permanentLines.find((line) =>
    nullableString(line.label)?.toLowerCase().includes("roofline"),
  );
  const controller = permanentLines.find((line) =>
    nullableString(line.label)?.toLowerCase().includes("controller"),
  );
  const includedChannels = nullableString(controller?.detail)?.match(/includes (\d+)/i);
  const extraChannels = permanentLines.find((line) =>
    nullableString(line.label)?.toLowerCase().includes("additional zone"),
  );

  const christmasSection = sectionByKey.get("christmas");
  const christmasLines = records(christmasSection?.lines);
  const christmasRoofline = christmasLines.find((line) =>
    nullableString(line.label)?.toLowerCase().includes("roofline"),
  );

  const pricingSource =
    document.pricing_source === "price_book" ? "price_book" : "workspace_rules";
  const payload: ProposalWizardPayload = {
    pricing_source: pricingSource,
    client: record(document.client) as WizardClient | null,
    quantities: Array.from(quantityByItem, ([item_id, quantity]) => ({
      item_id,
      quantity,
    })),
    additional_charges: records(document.additional_charges)
      .map((charge) => ({
        description: nullableString(charge.description),
        // Exact only for price-book quotes. The legacy warning tells the rep to
        // review these values before saving a workspace-rules snapshot.
        net_amount: finiteNumber(charge.amount),
        catalog_item_id: nullableString(charge.catalog_item_id),
        tier_key: nullableString(charge.tier_key),
      }))
      .filter((charge) => charge.net_amount > 0),
    selected_tier: nullableString(document.selected_tier),
    care_plan_tier: nullableString(carePlan?.selected),
    categories: categories.length ? categories : ["landscape"],
    bistro: bistro
      ? {
          product: bistro.product === "classic" ? "classic" : "color",
          tier: nullableString(bistro.tier) ?? "",
          feet: finiteNumber(bistro.feet),
        }
      : null,
    permanent: permanentSection
      ? {
          feet: finiteNumber(roofline?.quantity),
          channels:
            Number.parseInt(includedChannels?.[1] ?? "0", 10) +
            finiteNumber(extraChannels?.quantity),
        }
      : null,
    christmas: christmasSection
      ? {
          roofline_feet: finiteNumber(christmasRoofline?.quantity),
          items: {},
          takedown: christmasSection.takedown === true,
          storage: christmasSection.storage === true,
          selected_package: null,
        }
      : null,
    night_preview: nightPreview,
    mockups: records(document.mockups)
      .map((mockup) => ({
        image: nullableString(mockup.image) ?? "",
        caption: nullableString(mockup.caption),
      }))
      .filter((mockup) => mockup.image),
    deposit:
      (document.deposit_mode === "fixed" || document.deposit_mode === "percentage") &&
      finiteNumber(document.deposit_value) > 0
        ? {
            mode: document.deposit_mode,
            value: finiteNumber(document.deposit_value),
          }
        : null,
  };

  return { payload: withCurrentQuoteLinks(payload, quote), source: "snapshot" };
}

export interface UseSalesWizardReturn {
  /** Workspace this quote belongs to (scopes client lookups to its own CRM). */
  workspaceId: string;
  // Config + catalog
  pricing: PricingSettings | undefined;
  catalog: CatalogItemResponse[] | undefined;
  isLoadingConfig: boolean;
  configError: boolean;
  // Product-line selection (which categories this quote includes)
  categories: CategoryKey[];
  hasCategory: (key: CategoryKey) => boolean;
  toggleCategory: (key: CategoryKey) => void;
  // The service path this quote is on. One quote = one service; `setService`
  // switches branch and replaces the selection so a mix can never be built.
  activeService: ServiceKey;
  setService: (service: ServiceKey) => void;
  // Selection state
  client: ClientDraft;
  setClientField: (key: keyof ClientDraft, value: string) => void;
  /** Existing customer this quote is filed against, when the rep picked one. */
  linkedContactId: number | null;
  /** Fill the client block from an existing contact and link the quote to it. */
  applyContact: (contact: Contact) => void;
  /** Detach the linked customer, keeping the typed details as a new client. */
  clearLinkedContact: () => void;
  quantities: Record<string, number>;
  setQty: (itemId: string, qty: number) => void;
  changeQty: (itemId: string, delta: number) => void;
  charges: ChargeDraft[];
  setCharge: (index: number, patch: Partial<ChargeDraft>) => void;
  addCharge: () => void;
  /** Append a price-book item as a charge, keeping its category provenance. */
  addCatalogCharge: (item: CatalogItem) => void;
  removeCharge: (index: number) => void;
  activeTier: string;
  setActiveTier: (key: string) => void;
  carePlanTier: string | null;
  setCarePlanTier: (key: string) => void;
  careCountManual: number | null;
  setCareCountManual: (count: number | null) => void;
  bistro: BistroDraft;
  setBistro: (patch: Partial<BistroDraft>) => void;
  mockups: MockupDraft[];
  addMockupFiles: (files: FileList | File[]) => Promise<number>;
  removeMockup: (index: number) => void;
  setMockupCaption: (index: number, caption: string) => void;
  permanent: PermanentDraft;
  setPermanent: (patch: Partial<PermanentDraft>) => void;
  christmas: ChristmasDraft;
  setChristmas: (patch: Partial<ChristmasDraft>) => void;
  setSeasonalItem: (
    categoryKey: string,
    optionKey: string,
    value: number,
  ) => void;
  setChristmasPackage: (key: string) => void;
  night: NightPreviewState;
  setNight: (patch: Partial<NightPreviewState>) => void;
  // Upfront deposit selection (empty value => workspace default on save).
  depositMode: DepositMode;
  setDepositMode: (mode: DepositMode) => void;
  depositInput: string;
  setDepositInput: (value: string) => void;
  // Server-computed document (live preview)
  document: WizardDocument | null;
  isPreviewing: boolean;
  tierView: (key: string) => WizardTierView | undefined;
  lineFor: (tierKey: string, itemId: string) => ProposalLine | undefined;
  tierConfig: (key: string) => TierConfig | undefined;
  // Save flow
  save: () => Promise<QuoteDetail>;
  isSaving: boolean;
  savedQuote: QuoteDetail | null;
  /**
   * The live cross-sell prompt for the current selection, or null when there is
   * nothing to ask. Comes from the server preview (so it tracks every edit) and
   * is re-asserted from a blocking save rejection. Null once the rep adds the
   * service or dismisses the prompt.
   */
  attachWarning: AttachWarning | null;
  /** Skip the prompt, recording the reason on the quote when it is saved. */
  dismissAttach: (reason: string | null) => void;
  /** Existing quote being edited or copied, null for a new proposal. */
  editingQuoteId: string | null;
  editMode: "update" | "revise" | null;
  hydrationSource: WizardHydrationSource | null;
  isLoadingQuote: boolean;
  quoteLoadError: boolean;
  reloadQuote: () => void;
  // Deliver flow (server emails/texts the client link)
  deliver: (channel: "email" | "sms") => Promise<{ to: string }>;
  isDelivering: boolean;
}

export function useSalesWizard(
  workspaceId: string,
  /**
   * Service branch this quote starts on (from `/sales-wizard?service=…`), so the
   * hub's service-scoped entries land the rep directly on that path. Defaults to
   * landscape, the previous behavior.
   */
  initialService: ServiceKey = "landscape",
  /** Existing wizard quote to hydrate and update/revise. */
  editingQuoteId: string | null = null,
): UseSalesWizardReturn {
  const queryClient = useQueryClient();
  const pricingQuery = useQuery({
    queryKey: queryKeys.salesWizard.pricing(workspaceId),
    queryFn: () => salesWizardApi.getPricing(workspaceId),
  });
  const catalogQuery = useQuery({
    queryKey: queryKeys.salesWizard.catalog(workspaceId),
    queryFn: () => salesWizardApi.listCatalog(workspaceId),
  });
  const quoteQuery = useQuery({
    queryKey: queryKeys.quotes.detail(workspaceId, editingQuoteId ?? "new"),
    queryFn: () => salesWizardApi.getQuote(workspaceId, editingQuoteId ?? ""),
    enabled: Boolean(workspaceId && editingQuoteId),
  });

  const pricing = pricingQuery.data;

  // ── Selection state ──
  const [client, setClient] = useState<ClientDraft>(EMPTY_CLIENT);
  const [linkedContactId, setLinkedContactId] = useState<number | null>(null);
  const [quantities, setQuantities] = useState<Record<string, number>>({});
  const [charges, setCharges] = useState<ChargeDraft[]>([
    { description: "", amount: "" },
  ]);
  const [activeTierState, setActiveTier] = useState<string>("");
  const [carePlanTierState, setCarePlanTierState] = useState<string | null>(
    null,
  );
  const [careCountManual, setCareCountManual] = useState<number | null>(null);
  const [bistroState, setBistroState] = useState<BistroDraft>({
    product: "color",
    tier: "",
    feet: "",
  });
  const [mockups, setMockups] = useState<MockupDraft[]>([]);
  const [categories, setCategories] = useState<CategoryKey[]>(() => [
    SERVICE_CATEGORIES[initialService][0],
  ]);
  const [permanent, setPermanentState] = useState<PermanentDraft>({
    feet: "",
    channels: "",
  });
  const [christmas, setChristmasState] = useState<ChristmasDraft>(
    () => EMPTY_CHRISTMAS,
  );
  const [night, setNightState] = useState<NightPreviewState>({
    images: [],
    shots: [],
    services: [],
  });
  // Upfront deposit the rep requests on the quote. Value is a raw string so
  // typing feels native; empty/0 means "use the workspace default".
  const [depositMode, setDepositMode] = useState<DepositMode>("percentage");
  const [depositInput, setDepositInput] = useState<string>("");
  const depositValue = Math.max(0, Number.parseFloat(depositInput) || 0);

  const [editMode, setEditMode] = useState<"update" | "revise" | null>(null);
  const [hydrationSource, setHydrationSource] =
    useState<WizardHydrationSource | null>(null);
  const [hydratedQuoteId, setHydratedQuoteId] = useState<string | null>(null);
  const [hydrationError, setHydrationError] = useState<Error | null>(null);
  const editTargetRef = useRef<{
    quoteId: string;
    mode: "update" | "revise";
  } | null>(null);
  const [hydratedMetadata, setHydratedMetadata] =
    useState<Partial<ProposalWizardPayload>>({});

  // Defaults derive from loaded config/preview instead of effect-synced state,
  // so first render is already correct and no cascading setState is needed.
  const activeTier =
    activeTierState ||
    pricing?.tier_order?.[0] ||
    pricing?.tiers?.[0]?.key ||
    "";
  const bistro = useMemo<BistroDraft>(() => {
    const bistroTiers = pricing?.bistro?.tiers ?? [];
    // Do not silently replace a historical saved tier while hydrating. If pricing
    // has since changed, the preview can report it and the rep can choose openly.
    if (hydrationSource && bistroState.tier) return bistroState;
    if (
      !bistroTiers.length ||
      bistroTiers.some((tier) => tier.key === bistroState.tier)
    ) {
      return bistroState;
    }
    return { ...bistroState, tier: bistroTiers[0]?.key ?? "" };
  }, [bistroState, hydrationSource, pricing]);
  // Care plan defaults to the "popular" option from the priced document until
  // the rep explicitly picks one (derived — no effect-synced state).
  const [document, setDocument] = useState<WizardDocument | null>(null);
  const carePlanTier = useMemo(() => {
    if (carePlanTierState) return carePlanTierState;
    const options = document?.care_plan?.options ?? [];
    if (!options.length) return null;
    return (options.find((o) => o.popular) ?? options[0]).key;
  }, [carePlanTierState, document]);

  /* eslint-disable react-hooks/set-state-in-effect -- The component gates rendering
     until this one-time async query snapshot has hydrated the controlled form. */
  useEffect(() => {
    if (!editingQuoteId || !quoteQuery.data || hydratedQuoteId === editingQuoteId) return;

    try {
      const quote = quoteQuery.data as EditableQuoteDetail;
      const hydration = hydrationForQuote(quote);
      const input = hydration.payload;
      const savedClient = input.client;
      const nextCategories = (input.categories ?? []).filter(
        (key): key is CategoryKey => CATEGORY_KEYS.includes(key as CategoryKey),
      );

      setClient({
        first_name: savedClient?.first_name ?? "",
        last_name: savedClient?.last_name ?? "",
        email: savedClient?.email ?? "",
        phone: savedClient?.phone ?? "",
        rep_name: savedClient?.rep_name ?? "",
        street: savedClient?.street ?? "",
        city: savedClient?.city ?? "",
        state: savedClient?.state ?? "",
        zip: savedClient?.zip ?? "",
      });
      setLinkedContactId(typeof input.contact_id === "number" ? input.contact_id : null);
      setQuantities(
        Object.fromEntries(
          (input.quantities ?? []).map((row) => [row.item_id, row.quantity]),
        ),
      );
      setCharges(
        input.additional_charges?.length
          ? input.additional_charges.map((charge) => ({
              description: charge.description ?? "",
              amount: String(charge.net_amount),
              catalogItemId: charge.catalog_item_id ?? null,
              tierKey: charge.tier_key ?? null,
            }))
          : [{ description: "", amount: "" }],
      );
      setActiveTier(input.selected_tier ?? "");
      setCarePlanTierState(input.care_plan_tier ?? null);
      setCareCountManual(input.care_count_manual ?? null);
      setCategories(
        nextCategories.length
          ? nextCategories
          : [SERVICE_CATEGORIES[initialService][0]],
      );
      setBistroState(
        input.bistro
          ? {
              product: input.bistro.product === "classic" ? "classic" : "color",
              tier: input.bistro.tier,
              feet: String(input.bistro.feet),
            }
          : { product: "color", tier: "", feet: "" },
      );
      setPermanentState(
        input.permanent
          ? {
              feet: String(input.permanent.feet),
              channels: String(input.permanent.channels),
            }
          : { feet: "", channels: "" },
      );
      setChristmasState(
        input.christmas
          ? {
              roofline_feet: String(input.christmas.roofline_feet),
              items: Object.fromEntries(
                Object.entries(input.christmas.items ?? {}).map(([category, rows]) => [
                  category,
                  Object.fromEntries((rows ?? []).map((row) => [row.key, row.quantity])),
                ]),
              ),
              takedown: input.christmas.takedown,
              storage: input.christmas.storage,
              selected_package: input.christmas.selected_package ?? "",
            }
          : EMPTY_CHRISTMAS,
      );
      const savedNight = record(input.night_preview);
      const savedImages = Array.isArray(savedNight?.images)
        ? savedNight.images.filter((image): image is string => typeof image === "string")
        : nullableString(savedNight?.image)
          ? [String(savedNight?.image)]
          : [];
      setNightState({
        images: savedImages,
        shots: [],
        services: Array.isArray(savedNight?.services)
          ? (savedNight.services.filter(
              (service): service is string => typeof service === "string",
            ) as DesignerServiceKey[])
          : [],
      });
      setMockups(
        (input.mockups ?? []).map((mockup) => ({
          image: mockup.image,
          caption: mockup.caption ?? "",
        })),
      );
      setDepositMode(input.deposit?.mode ?? "percentage");
      setDepositInput(input.deposit ? String(input.deposit.value) : "");
      setDocument(
        quote.proposal_document
          ? normalizeDocument(quote.proposal_document as ProposalDocument)
          : null,
      );

      setHydratedMetadata({
        pricing_source: input.pricing_source,
        service_location_id: input.service_location_id ?? null,
        opportunity_id: input.opportunity_id ?? null,
        lighting_project_id: input.lighting_project_id ?? null,
        title: input.title ?? null,
        notes: input.notes ?? null,
        terms: input.terms ?? null,
      });
      const mode = quote.wizard_edit_mode ?? "revise";
      editTargetRef.current = { quoteId: String(quote.id), mode };
      setEditMode(mode);
      setHydrationSource(hydration.source);
      setHydrationError(null);
      setHydratedQuoteId(String(quote.id));
    } catch (error) {
      setHydrationError(
        error instanceof Error ? error : new Error("The saved quote could not be loaded."),
      );
    }
  }, [editingQuoteId, hydratedQuoteId, initialService, quoteQuery.data]);
  /* eslint-enable react-hooks/set-state-in-effect */

  const setClientField = useCallback(
    (key: keyof ClientDraft, value: string) => {
      if (IDENTITY_FIELDS.has(key)) setLinkedContactId(null);
      setClient((prev) => ({ ...prev, [key]: value }));
    },
    [],
  );

  // Taking a suggestion adopts that customer's details wholesale, except where
  // the record is blank — an empty address must not wipe what the rep typed.
  const applyContact = useCallback((contact: Contact) => {
    setLinkedContactId(contact.id);
    setClient((prev) => ({
      ...prev,
      first_name: contact.first_name ?? "",
      last_name: contact.last_name ?? "",
      email: contact.email || prev.email,
      // Formatted on the way in so the filled field reads the way a rep types
      // it. Phone lookups hash on digits only, so this can't break matching.
      phone: contact.phone_number
        ? formatPhoneNumber(contact.phone_number)
        : prev.phone,
      street: contact.address_line1 || prev.street,
      city: contact.address_city || prev.city,
      state: contact.address_state || prev.state,
      zip: contact.address_zip || prev.zip,
    }));
  }, []);

  const clearLinkedContact = useCallback(() => setLinkedContactId(null), []);

  const setQty = useCallback((itemId: string, qty: number) => {
    const clamped = Math.max(0, Math.min(999, Math.floor(qty)));
    setQuantities((prev) => ({ ...prev, [itemId]: clamped }));
  }, []);

  const changeQty = useCallback((itemId: string, delta: number) => {
    setQuantities((prev) => {
      const next = Math.max(
        0,
        Math.min(999, Math.floor((prev[itemId] ?? 0) + delta)),
      );
      return { ...prev, [itemId]: next };
    });
  }, []);

  const setCharge = useCallback(
    (index: number, patch: Partial<ChargeDraft>) => {
      setCharges((prev) =>
        prev.map((c, i) => (i === index ? { ...c, ...patch } : c)),
      );
    },
    [],
  );
  const addCharge = useCallback(() => {
    setCharges((prev) => [...prev, { description: "", amount: "" }]);
  }, []);
  const addCatalogCharge = useCallback((item: CatalogItem) => {
    setCharges((prev) => {
      const charge: ChargeDraft = {
        description: item.name,
        amount: String(item.unit_price ?? 0),
        catalogItemId: item.id,
      };
      // Reuse the trailing blank row the editor always leaves behind rather
      // than pushing the attach below an empty one.
      const blank = prev.findIndex(
        (c) => c.description.trim() === "" && c.amount.trim() === "",
      );
      if (blank === -1) return [...prev, charge];
      return prev.map((c, i) => (i === blank ? charge : c));
    });
  }, []);
  const removeCharge = useCallback((index: number) => {
    setCharges((prev) => {
      const next = prev.filter((_, i) => i !== index);
      return next.length ? next : [{ description: "", amount: "" }];
    });
  }, []);

  const setBistro = useCallback((patch: Partial<BistroDraft>) => {
    setBistroState((prev) => ({ ...prev, ...patch }));
  }, []);
  // Resize each picked file in the browser, then append (respecting the cap).
  // Returns how many were actually added so the UI can report skips/failures.
  const addMockupFiles = useCallback(
    async (files: FileList | File[]): Promise<number> => {
      const picked = Array.from(files).filter((f) => f.type.startsWith("image/"));
      if (!picked.length) return 0;
      const resized: string[] = [];
      for (const file of picked) {
        try {
          resized.push(await fileToResizedDataUrl(file));
        } catch {
          // Skip unreadable files; the rest still upload.
        }
      }
      if (!resized.length) return 0;
      let added = 0;
      setMockups((prev) => {
        const room = Math.max(0, MAX_MOCKUPS - prev.length);
        const next = resized
          .slice(0, room)
          .map((image) => ({ image, caption: "" }));
        added = next.length;
        return next.length ? [...prev, ...next] : prev;
      });
      return added;
    },
    [],
  );
  const removeMockup = useCallback((index: number) => {
    setMockups((prev) => prev.filter((_, i) => i !== index));
  }, []);
  const setMockupCaption = useCallback((index: number, caption: string) => {
    setMockups((prev) =>
      prev.map((m, i) => (i === index ? { ...m, caption } : m)),
    );
  }, []);
  const hasCategory = useCallback(
    (key: CategoryKey) => categories.includes(key),
    [categories],
  );
  const activeService = useMemo(
    () => serviceForCategories(categories),
    [categories],
  );
  const setService = useCallback((service: ServiceKey) => {
    // Replace, never merge: switching branch drops the previous service's lines
    // so a quote can't end up spanning two services. Each service starts on its
    // primary line (bistro stays an opt-in line chip within landscape).
    setCategories([SERVICE_CATEGORIES[service][0]]);
  }, []);
  const toggleCategory = useCallback((key: CategoryKey) => {
    setCategories((prev) => {
      // A line from another service switches the branch instead of mixing.
      if (serviceForCategories(prev) !== serviceForCategory(key)) return [key];
      return prev.includes(key)
        ? prev.filter((c) => c !== key)
        : CATEGORY_KEYS.filter((c) => c === key || prev.includes(c));
    });
  }, []);
  const setPermanent = useCallback((patch: Partial<PermanentDraft>) => {
    setPermanentState((prev) => ({ ...prev, ...patch }));
  }, []);
  const setChristmas = useCallback((patch: Partial<ChristmasDraft>) => {
    setChristmasState((prev) => ({ ...prev, ...patch }));
  }, []);
  const setSeasonalItem = useCallback(
    (categoryKey: string, optionKey: string, value: number) => {
      // `each` steppers pass integers; `per_ft` (garland) passes linear feet.
      // Clamp non-negative only; the UI floors counts where appropriate.
      const clamped = Number.isFinite(value) ? Math.max(0, value) : 0;
      setChristmasState((prev) => ({
        ...prev,
        items: {
          ...prev.items,
          [categoryKey]: { ...(prev.items[categoryKey] ?? {}), [optionKey]: clamped },
        },
      }));
    },
    [],
  );
  const setChristmasPackage = useCallback((key: string) => {
    setChristmasState((prev) => ({ ...prev, selected_package: key }));
  }, []);
  const setNight = useCallback((patch: Partial<NightPreviewState>) => {
    setNightState((prev) => ({ ...prev, ...patch }));
  }, []);
  const setCarePlanTier = useCallback((key: string) => {
    setCarePlanTierState(key);
  }, []);

  // ── Payload (raw selection only — server owns all money) ──
  const payload = useMemo<ProposalWizardPayload>(() => {
    const qtyList = Object.entries(quantities)
      .filter(([, q]) => q > 0)
      .map(([item_id, quantity]) => ({ item_id, quantity }));
    const chargeList = charges
      .map((c) => ({
        description: c.description.trim() || null,
        net_amount: Number.parseFloat(c.amount) || 0,
        catalog_item_id: c.catalogItemId ?? null,
        // Omitted rather than null when the charge is global: an absent field
        // is what asks the server for the ride-on-every-tier default.
        ...(c.tierKey ? { tier_key: c.tierKey } : {}),
      }))
      .filter((c) => c.net_amount > 0);
    const feet = Number.parseFloat(bistro.feet) || 0;
    const hasBistro = categories.includes("bistro");
    const hasPermanent = categories.includes("permanent");
    const hasChristmas = categories.includes("christmas");
    const permFeet = Number.parseFloat(permanent.feet) || 0;
    return {
      ...hydratedMetadata,
      pricing_source: hydratedMetadata.pricing_source ?? "workspace_rules",
      // Linked customer wins over the server's email/phone lookup, so re-quoting
      // an existing client files on their record instead of creating a twin.
      contact_id: linkedContactId,
      client: toWizardClient(client),
      quantities: qtyList,
      additional_charges: chargeList,
      selected_tier: activeTier || null,
      care_plan_tier: carePlanTier,
      care_count_manual: careCountManual,
      categories,
      bistro:
        hasBistro && feet > 0
          ? { product: bistro.product, tier: bistro.tier, feet }
          : null,
      permanent: hasPermanent
        ? {
            feet: permFeet,
            channels: Number.parseInt(permanent.channels, 10) || 0,
          }
        : null,
      christmas: hasChristmas
        ? {
            roofline_feet: Number.parseFloat(christmas.roofline_feet) || 0,
            items: Object.fromEntries(
              Object.entries(christmas.items)
                .map(([key, counts]) => [key, countsToList(counts)] as const)
                .filter(([, list]) => list.length > 0),
            ),
            takedown: christmas.takedown,
            storage: christmas.storage,
            // Empty selection => server prices the most inclusive package.
            selected_package: christmas.selected_package || null,
          }
        : null,
      night_preview: night.images.length
        ? {
            // Opaque to the server (JSONB). `image` stays the hero shot on its
            // own key because proposals saved before multi-photo designs only
            // ever had one, and every reader still falls back to it.
            image: night.images[0],
            images: night.images,
            services: night.services,
          }
        : null,
      mockups: mockups
        .filter((m) => m.image)
        .map((m) => ({ image: m.image, caption: m.caption.trim() || null })),
      // Deposit rides along when the rep entered one; a zero value falls back to
      // the workspace default on the server.
      deposit:
        depositValue > 0 ? { mode: depositMode, value: depositValue } : null,
    };
  }, [
    hydratedMetadata,
    client,
    linkedContactId,
    quantities,
    charges,
    activeTier,
    carePlanTier,
    careCountManual,
    categories,
    bistro,
    permanent,
    christmas,
    night,
    mockups,
    depositMode,
    depositValue,
  ]);

  // ── Debounced live preview ──
  const [isPreviewing, setIsPreviewing] = useState(false);
  const generationRef = useRef(0);

  useEffect(() => {
    if (!pricing) return;
    if (editingQuoteId && hydratedQuoteId !== editingQuoteId) return;
    const generation = ++generationRef.current;
    const timer = setTimeout(() => {
      setIsPreviewing(true);
      // Neither the mockups nor the lit-photo composites affect pricing, and
      // both are multi-megabyte base64 — a design can span several photos.
      // Stripping them keeps the debounced live preview light; they ride along
      // only on save, into the saved snapshot. The rep's presentation reads the
      // composites from `night` state, so nothing on screen depends on the echo.
      salesWizardApi
        .preview(workspaceId, { ...payload, mockups: [], night_preview: null })
        .then((doc) => {
          if (generationRef.current === generation)
            setDocument(normalizeDocument(doc));
        })
        .catch(() => {
          // Keep the last good document; the next edit retries automatically.
        })
        .finally(() => {
          if (generationRef.current === generation) setIsPreviewing(false);
        });
    }, PREVIEW_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [editingQuoteId, hydratedQuoteId, payload, pricing, workspaceId]);

  // ── Lookups ──
  const tierView = useCallback(
    (key: string) => document?.tiers.find((t) => t.key === key),
    [document],
  );
  const lineFor = useCallback(
    (tierKey: string, itemId: string) =>
      document?.tiers
        .find((t) => t.key === tierKey)
        ?.lines.find((l) => l.item_id === itemId),
    [document],
  );
  const tierConfig = useCallback(
    (key: string) => pricing?.tiers?.find((t) => t.key === key),
    [pricing],
  );

  // ── Attach prompt (the cross-sell reminder) ──
  //
  // The live preview reports whether this selection is missing its add-on, so
  // the prompt tracks every edit and the rep can act before a quote exists.
  // `blockedWarning` re-asserts it from a rejected save, which covers a stale
  // or in-flight preview. A dismissal suppresses the prompt locally and rides
  // on the save payload so the skip is recorded against the quote it belongs to.
  const [attachDismissal, setAttachDismissal] =
    useState<AttachDismissalDraft | null>(null);
  const [blockedWarning, setBlockedWarning] = useState<AttachWarning | null>(null);

  const previewWarning = document?.attach_warning ?? null;
  const liveWarning = previewWarning ?? blockedWarning;
  const attachWarning = attachDismissal === null ? liveWarning : null;

  // A skip must never outlive the prompt it answered. Retire the dismissal when
  // the rep adds the service (no warning left) *or* when a different rule starts
  // firing, because "customer declined the gutters" is not an answer about the
  // trim, and recording it as one would poison the report this exists to feed.
  if (attachDismissal !== null && attachPromptKey(liveWarning) !== attachDismissal.promptKey) {
    setAttachDismissal(null);
  }
  if (blockedWarning !== null && previewWarning === null) {
    setBlockedWarning(null);
  }

  const dismissAttach = useCallback(
    (reason: string | null) => {
      const promptKey = attachPromptKey(liveWarning);
      // Nothing to skip: the prompt cleared underneath the click.
      if (promptKey === null) return;
      setAttachDismissal({ reason, promptKey });
    },
    [liveWarning],
  );

  // ── Save flow (new quotes mint a link; edits preserve their lifecycle) ──────
  const [isSaving, setIsSaving] = useState(false);
  const [savedQuote, setSavedQuote] = useState<QuoteDetail | null>(null);
  const save = useCallback(
    async (): Promise<QuoteDetail> => {
      setIsSaving(true);
      try {
        const savePayload: ProposalWizardPayload = {
          ...payload,
          // Only sent once the rep explicitly skips the prompt, and only the
          // reason crosses the wire — the server resolves which categories were
          // skipped from the rule that actually fired, so a stale dismissal can
          // never invent a "they declined" event on a quote that has the attach.
          attach_dismissal: attachDismissal
            ? { reason: attachDismissal.reason }
            : null,
        };

        const target = editTargetRef.current;
        let persisted: QuoteDetail;
        if (target?.mode === "revise") {
          persisted = await salesWizardApi.revise(
            workspaceId,
            target.quoteId,
            savePayload,
          );
        } else if (target) {
          persisted = await salesWizardApi.update(
            workspaceId,
            target.quoteId,
            savePayload,
          );
        } else {
          const draft = await salesWizardApi.save(workspaceId, savePayload);
          persisted = await salesWizardApi.send(workspaceId, String(draft.id));
        }

        const persistedId = String(persisted.id);
        // Every successful save becomes the mutable target. This prevents both a
        // second new quote and a sibling revision when the rep saves twice.
        editTargetRef.current = { quoteId: persistedId, mode: "update" };
        if (target) setEditMode("update");
        queryClient.setQueryData(
          queryKeys.quotes.detail(workspaceId, persistedId),
          persisted,
        );
        await queryClient.invalidateQueries({
          queryKey: queryKeys.quotes.all(workspaceId),
        });
        setSavedQuote(persisted);
        return persisted;
      } catch (error) {
        // A blocking rule rejects the save carrying the same warning shape the
        // preview returns, so the builder offers the identical Add / Skip
        // affordances instead of a dead-end error toast. This also covers the
        // case where the preview is mid-flight or stale.
        const warning = asAttachWarning(getApiErrorDetails(error));
        if (warning) setBlockedWarning(warning);
        throw error;
      } finally {
        setIsSaving(false);
      }
    },
    [workspaceId, payload, attachDismissal, queryClient],
  );

  // ── Deliver flow (server emails/texts the client link) ──
  const [isDelivering, setIsDelivering] = useState(false);

  const deliver = useCallback(
    async (channel: "email" | "sms"): Promise<{ to: string }> => {
      setIsDelivering(true);
      try {
        // Always save first. The current session targets the same quote after its
        // first save, so this persists last-second edits without creating copies.
        const quote = await save();
        const result = await salesWizardApi.deliver(
          workspaceId,
          String(quote.id),
          channel,
        );
        const sent = await salesWizardApi.getQuote(workspaceId, String(quote.id));
        setSavedQuote(sent);
        queryClient.setQueryData(
          queryKeys.quotes.detail(workspaceId, String(quote.id)),
          sent,
        );
        return result;
      } finally {
        setIsDelivering(false);
      }
    },
    [queryClient, save, workspaceId],
  );

  const isLoadingQuote = Boolean(
    editingQuoteId &&
      !hydrationError &&
      (quoteQuery.isPending || hydratedQuoteId !== editingQuoteId),
  );
  const quoteLoadError = quoteQuery.isError || hydrationError !== null;
  const reloadQuote = () => {
    setHydrationError(null);
    setHydratedQuoteId(null);
    void quoteQuery.refetch();
  };

  return {
    workspaceId,
    pricing,
    catalog: catalogQuery.data,
    isLoadingConfig: pricingQuery.isPending || catalogQuery.isPending,
    configError: pricingQuery.isError || catalogQuery.isError,
    client,
    setClientField,
    linkedContactId,
    applyContact,
    clearLinkedContact,
    quantities,
    setQty,
    changeQty,
    charges,
    setCharge,
    addCharge,
    addCatalogCharge,
    removeCharge,
    categories,
    hasCategory,
    toggleCategory,
    activeService,
    setService,
    activeTier,
    setActiveTier,
    carePlanTier,
    setCarePlanTier,
    careCountManual,
    setCareCountManual,
    bistro,
    setBistro,
    mockups,
    addMockupFiles,
    removeMockup,
    setMockupCaption,
    permanent,
    setPermanent,
    christmas,
    setChristmas,
    setSeasonalItem,
    setChristmasPackage,
    night,
    setNight,
    depositMode,
    setDepositMode,
    depositInput,
    setDepositInput,
    document,
    isPreviewing,
    tierView,
    lineFor,
    tierConfig,
    save,
    isSaving,
    savedQuote,
    attachWarning,
    dismissAttach,
    editingQuoteId,
    editMode,
    hydrationSource,
    isLoadingQuote,
    quoteLoadError,
    reloadQuote,
    deliver,
    isDelivering,
  };
}
