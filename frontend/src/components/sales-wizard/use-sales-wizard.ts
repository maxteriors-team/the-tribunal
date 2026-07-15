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
import { REFERENCE_PRESETS, type Point } from "@/lib/estimator/measure";
import { queryKeys } from "@/lib/query-keys";
import type {
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

// ─── Draft state shapes (inputs stay strings so typing feels native) ────────
export interface ChargeDraft {
  description: string;
  amount: string; // net the rep keeps; server grosses it up
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
}

const EMPTY_CHRISTMAS: ChristmasDraft = {
  roofline_feet: "",
  items: {},
  takedown: false,
  storage: false,
};

function countsToList(
  counts: Record<string, number>,
): { key: string; quantity: number }[] {
  return Object.entries(counts)
    .filter(([, q]) => q > 0)
    .map(([key, quantity]) => ({ key, quantity }));
}

export interface NightLight {
  nx: number;
  ny: number;
  /** Second anchor — only for string ("bistro") lights. */
  nx2?: number;
  ny2?: number;
  type: string;
  glow: number;
  intensity: number;
  spread: number;
  warmth: number;
}

/** How a wizard deposit's value is read: percent of total, or a flat amount. */
export type DepositMode = "percentage" | "fixed";

export interface NightPreviewState {
  /** Composited "lit at night" JPEG data-URL saved into the proposal. */
  image: string | null;
  lights: NightLight[];
  dusk: number;
  // ── Roofline "measure-as-you-draw" trace (persists so re-opening the night
  // screen restores the drawing; rides into the opaque `night_preview` snapshot).
  /** Key of the chosen `REFERENCE_PRESETS` object used to set the pixel scale. */
  referenceKey: string;
  /** Two canvas points marking the known-width reference object. */
  referencePts: Point[];
  /** Traced roofline polyline, in canvas pixels. */
  rooflinePts: Point[];
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
  // Config + catalog
  pricing: PricingSettings | undefined;
  catalog: CatalogItemResponse[] | undefined;
  isLoadingConfig: boolean;
  configError: boolean;
  // Product-line selection (which categories this quote includes)
  categories: CategoryKey[];
  hasCategory: (key: CategoryKey) => boolean;
  toggleCategory: (key: CategoryKey) => void;
  // Selection state
  client: ClientDraft;
  setClientField: (key: keyof ClientDraft, value: string) => void;
  quantities: Record<string, number>;
  setQty: (itemId: string, qty: number) => void;
  changeQty: (itemId: string, delta: number) => void;
  charges: ChargeDraft[];
  setCharge: (index: number, patch: Partial<ChargeDraft>) => void;
  addCharge: () => void;
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
  // Deliver flow (server emails/texts the client link)
  deliver: (channel: "email" | "sms") => Promise<{ to: string }>;
  isDelivering: boolean;
}

export function useSalesWizard(workspaceId: string): UseSalesWizardReturn {
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
  const [categories, setCategories] = useState<CategoryKey[]>(["landscape"]);
  const [permanent, setPermanentState] = useState<PermanentDraft>({
    feet: "",
    channels: "",
  });
  const [christmas, setChristmasState] = useState<ChristmasDraft>(
    () => EMPTY_CHRISTMAS,
  );
  const [night, setNightState] = useState<NightPreviewState>({
    image: null,
    lights: [],
    dusk: 0.55,
    referenceKey: REFERENCE_PRESETS[0].key,
    referencePts: [],
    rooflinePts: [],
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
      setClient((prev) => ({ ...prev, [key]: value }));
    },
    [],
  );

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
  const toggleCategory = useCallback((key: CategoryKey) => {
    setCategories((prev) =>
      prev.includes(key)
        ? prev.filter((c) => c !== key)
        : CATEGORY_KEYS.filter((c) => c === key || prev.includes(c)),
    );
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
      }))
      .filter((c) => c.net_amount > 0);
    const feet = Number.parseFloat(bistro.feet) || 0;
    const hasBistro = categories.includes("bistro");
    const hasPermanent = categories.includes("permanent");
    const hasChristmas = categories.includes("christmas");
    const permFeet = Number.parseFloat(permanent.feet) || 0;
    return {
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
          }
        : null,
      night_preview: night.image
        ? {
            image: night.image,
            lights: night.lights,
            dusk: night.dusk,
            reference_key: night.referenceKey,
            reference_pts: night.referencePts,
            roofline_pts: night.rooflinePts,
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

  // ── Save flow (draft quote + snapshot, then mark sent for the share token) ──
  const [isSaving, setIsSaving] = useState(false);
  const [savedQuote, setSavedQuote] = useState<QuoteDetail | null>(null);

  const save = useCallback(async (): Promise<QuoteDetail> => {
    setIsSaving(true);
    try {
      const quote = await salesWizardApi.save(workspaceId, payload);
      const sent = await salesWizardApi.send(workspaceId, String(quote.id));
      setSavedQuote(sent);
      return sent;
    } finally {
      setIsSaving(false);
    }
  }, [workspaceId, payload]);

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
    pricing,
    catalog: catalogQuery.data,
    isLoadingConfig: pricingQuery.isPending || catalogQuery.isPending,
    configError: pricingQuery.isError || catalogQuery.isError,
    client,
    setClientField,
    quantities,
    setQty,
    changeQty,
    charges,
    setCharge,
    addCharge,
    removeCharge,
    categories,
    hasCategory,
    toggleCategory,
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
    deliver,
    isDelivering,
  };
}
