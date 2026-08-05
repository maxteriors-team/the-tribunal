/**
 * Sales-wizard state + server-driven pricing.
 *
 * Holds the rep's raw *selection* (client fields, fixture quantities, add-on
 * charges, care/bistro/night picks) and continuously mirrors it to the backend
 * `wizard/preview` endpoint, which returns the fully-priced `ProposalDocument`.
 * No money is ever computed here — every figure rendered by the wizard comes
 * from that document, exactly like the saved snapshot the client later sees.
 */
import { useQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { salesWizardApi } from "@/lib/api/sales-wizard";
import { DEFAULT_DUSK } from "@/lib/estimator/render";
import type { ServiceKey as DesignerServiceKey } from "@/lib/estimator/services";
import type { Design, PhotoInfo } from "@/lib/estimator/types";
import { queryKeys } from "@/lib/query-keys";
import { getApiErrorDetails } from "@/lib/utils/errors";
import { formatPhoneNumber } from "@/lib/utils/phone";
import type { CatalogItem, Contact } from "@/types";
import type {
  AttachWarning,
  CatalogItemResponse,
  PricingSettings,
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
 * line); the wizard keeps the composited image plus the drawing itself, so
 * re-opening the designer resumes exactly where they left off. `photo` stays in
 * memory only — the saved snapshot carries the flattened composite, never the
 * multi-megabyte original.
 */
export interface NightPreviewState {
  /** Composited "lit at night" JPEG data-URL saved into the proposal. */
  image: string | null;
  /** The drawing, so re-opening the designer restores it. */
  design: Design | null;
  /** Dusk level the composite was rendered at. */
  dusk: number;
  /** Source photo, held in memory for the current session only. */
  photo: PhotoInfo | null;
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
): UseSalesWizardReturn {
  const pricingQuery = useQuery({
    queryKey: queryKeys.salesWizard.pricing(workspaceId),
    queryFn: () => salesWizardApi.getPricing(workspaceId),
  });
  const catalogQuery = useQuery({
    queryKey: queryKeys.salesWizard.catalog(workspaceId),
    queryFn: () => salesWizardApi.listCatalog(workspaceId),
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
    image: null,
    design: null,
    dusk: DEFAULT_DUSK,
    photo: null,
    services: [],
  });
  // Upfront deposit the rep requests on the quote. Value is a raw string so
  // typing feels native; empty/0 means "use the workspace default".
  const [depositMode, setDepositMode] = useState<DepositMode>("percentage");
  const [depositInput, setDepositInput] = useState<string>("");
  const depositValue = Math.max(0, Number.parseFloat(depositInput) || 0);

  // Defaults derive from loaded config/preview instead of effect-synced state,
  // so first render is already correct and no cascading setState is needed.
  const activeTier =
    activeTierState ||
    pricing?.tier_order?.[0] ||
    pricing?.tiers?.[0]?.key ||
    "";
  const bistro = useMemo<BistroDraft>(() => {
    if (
      bistroState.tier &&
      (pricing?.bistro?.tiers ?? []).some((t) => t.key === bistroState.tier)
    ) {
      return bistroState;
    }
    const firstBistro = pricing?.bistro?.tiers?.[0]?.key ?? "";
    return { ...bistroState, tier: firstBistro };
  }, [bistroState, pricing]);
  // Care plan defaults to the "popular" option from the priced document until
  // the rep explicitly picks one (derived — no effect-synced state).
  const [document, setDocument] = useState<WizardDocument | null>(null);
  const carePlanTier = useMemo(() => {
    if (carePlanTierState) return carePlanTierState;
    const options = document?.care_plan?.options ?? [];
    if (!options.length) return null;
    return (options.find((o) => o.popular) ?? options[0]).key;
  }, [carePlanTierState, document]);

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
      night_preview: night.image
        ? {
            image: night.image,
            // Opaque to the server (JSONB): the drawing rides along so a later
            // edit re-opens the designer with the same runs, items and scale,
            // and the services drive the client's value propositions.
            design: night.design,
            dusk: night.dusk,
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
    const generation = ++generationRef.current;
    const timer = setTimeout(() => {
      setIsPreviewing(true);
      // Mockups never affect pricing; stripping them keeps the debounced live
      // preview light. They ride along only on save, into the saved snapshot.
      salesWizardApi
        .preview(workspaceId, { ...payload, mockups: [] })
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
  }, [workspaceId, payload, pricing]);

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

  // ── Save flow (draft quote + snapshot, then mark sent for the share token) ──
  const [isSaving, setIsSaving] = useState(false);
  const [savedQuote, setSavedQuote] = useState<QuoteDetail | null>(null);
  const save = useCallback(
    async (): Promise<QuoteDetail> => {
      setIsSaving(true);
      try {
        const quote = await salesWizardApi.save(workspaceId, {
          ...payload,
          // Only sent once the rep explicitly skips the prompt, and only the
          // reason crosses the wire — the server resolves which categories were
          // skipped from the rule that actually fired, so a stale dismissal can
          // never invent a "they declined" event on a quote that has the attach.
          attach_dismissal: attachDismissal
            ? { reason: attachDismissal.reason }
            : null,
        });
        const sent = await salesWizardApi.send(workspaceId, String(quote.id));
        setSavedQuote(sent);
        return sent;
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
    [workspaceId, payload, attachDismissal],
  );

  // ── Deliver flow (server emails/texts the client link) ──
  const [isDelivering, setIsDelivering] = useState(false);

  const deliver = useCallback(
    async (channel: "email" | "sms"): Promise<{ to: string }> => {
      setIsDelivering(true);
      try {
        // Reuse the saved quote; save first if the rep skipped that step.
        const quote = savedQuote ?? (await save());
        return await salesWizardApi.deliver(
          workspaceId,
          String(quote.id),
          channel,
        );
      } finally {
        setIsDelivering(false);
      }
    },
    [workspaceId, savedQuote, save],
  );

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
    deliver,
    isDelivering,
  };
}
