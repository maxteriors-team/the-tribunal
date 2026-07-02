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

export { fmt, fmt2 } from "./document";
export type { WizardDocument, WizardTierView } from "./document";

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

export interface NightPreviewState {
  /** Composited "lit at night" JPEG data-URL saved into the proposal. */
  image: string | null;
  lights: NightLight[];
  dusk: number;
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
  night: NightPreviewState;
  setNight: (patch: Partial<NightPreviewState>) => void;
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
  const [night, setNightState] = useState<NightPreviewState>({
    image: null,
    lights: [],
    dusk: 0.55,
  });

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
    return {
      client: toWizardClient(client),
      quantities: qtyList,
      additional_charges: chargeList,
      selected_tier: activeTier || null,
      care_plan_tier: carePlanTier,
      care_count_manual: careCountManual,
      bistro:
        feet > 0
          ? { product: bistro.product, tier: bistro.tier, feet }
          : null,
      night_preview: night.image
        ? { image: night.image, lights: night.lights, dusk: night.dusk }
        : null,
    };
  }, [
    client,
    quantities,
    charges,
    activeTier,
    carePlanTier,
    careCountManual,
    bistro,
    night,
  ]);

  // ── Debounced live preview ──
  const [isPreviewing, setIsPreviewing] = useState(false);
  const generationRef = useRef(0);

  useEffect(() => {
    if (!pricing) return;
    const generation = ++generationRef.current;
    const timer = setTimeout(() => {
      setIsPreviewing(true);
      salesWizardApi
        .preview(workspaceId, payload)
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
    activeTier,
    setActiveTier,
    carePlanTier,
    setCarePlanTier,
    careCountManual,
    setCareCountManual,
    bistro,
    setBistro,
    night,
    setNight,
    document,
    isPreviewing,
    tierView,
    lineFor,
    tierConfig,
    save,
    isSaving,
    savedQuote,
  };
}
