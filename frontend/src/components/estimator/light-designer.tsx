"use client";

/**
 * Light Designer — the one place a rep designs lighting on a photo of the home.
 *
 * The rep uploads a house photo, sets the scale from a known measurement, then
 * draws the job: landscape fixtures from the workspace price book (uplights,
 * spots, path lights, wall washes, bistro), glowing C9 roofline, mini-lights on
 * bushes and trees, and wreaths. Dusk is a slider, so the customer watches their
 * own house light up.
 *
 * A job is rarely one photo. The rep adds as many shots as the house needs
 * (front elevation, back patio, the walkway) and each keeps its own drawing,
 * scale, and dusk; the thumbnail strip switches between them. Measurements are
 * totalled across every shot — the quote covers the whole job, not the photo
 * that happened to be on screen — and every drawn shot becomes a mockup on the
 * proposal.
 *
 * What the canvas produces is geometry — feet and counts, never money:
 *
 * - Holiday work is priced **server-side** into a live permanent-vs-seasonal
 *   comparison; "Client preview" renders the exact feet-free comparison the
 *   homeowner gets and "Save & share" mints a public link.
 * - Landscape fixtures resolve to real price-book items, so each one carries its
 *   SKU and bill-of-materials through to the quote and the technician's parts
 *   list. When the Quote Builder hosts this tool (the `proposal` prop) the
 *   counts flow straight into the wizard, which prices the tier server-side.
 *
 * Layout: tool/product palette (left), photo design stage (center), itemized
 * estimate + customer/share (right).
 */
import { keepPreviousData, useMutation, useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";

import { estimatorApi } from "@/lib/api/estimator";
import { salesWizardApi } from "@/lib/api/sales-wizard";
import {
  buildBistroCatalog,
  buildCatalog,
  indexProducts,
} from "@/lib/estimator/catalog";
import {
  toEstimateCustomLines,
  type CustomLineDraft,
} from "@/lib/estimator/custom-lines";
import {
  designScale,
  designToEstimateInputs,
  hasDesign,
  sumEstimateInputs,
} from "@/lib/estimator/design";
import { exportDesignJpeg } from "@/lib/estimator/export";
import {
  FIXTURE_TYPES,
  buildFixturePalette,
  hasLandscapeFixtures,
  resolveTierFixtures,
  type FixtureType,
} from "@/lib/estimator/fixtures";
import {
  resolveSelectedPackage,
  packageName,
  seasonalTotal,
} from "@/lib/estimator/packages";
import { fileToPhoto } from "@/lib/estimator/photo";
import {
  SERVICES,
  clientThemeClass,
  type ServiceKey,
} from "@/lib/estimator/services";
import type { PhotoInfo } from "@/lib/estimator/types";
import { queryKeys } from "@/lib/query-keys";
import { getApiErrorMessage } from "@/lib/utils/errors";
import type {
  EstimateRenderRequest,
  LinearFeetEstimateRequest,
} from "@/types/estimate";

import { AIRenderModal } from "./ai-render";
import { ComparisonCard, type ComparisonView } from "./comparison-card";
import {
  EMPTY_DESIGN,
  editorReducer,
  initialEditorState,
  nextId,
} from "./editor-store";
import { EstimatePanel } from "./estimate-panel";
import { LightCanvas } from "./light-canvas";
import type { DesignerProposalHost, DesignerShot } from "./proposal-host";
import { ServiceValueProps } from "./service-value-props";
import { ToolPalette } from "./tool-palette";
import "./estimator.css";

type ViewMode = "rep" | "client";

/**
 * How many photos one design session can carry. Every shot rides into the saved
 * proposal as its own full-size composite, so this is the cap that keeps a
 * snapshot row sane rather than a limit on how the rep works.
 */
export const MAX_SHOTS = 6;

/** How the client's estimate link reaches them. */
type SendChannel = "email" | "sms";

interface LightDesignerProps {
  workspaceId: string;
  /**
   * Set when the Quote Builder hosts the designer: the drawing is saved onto the
   * in-progress proposal instead of shared as a standalone estimate.
   */
  proposal?: DesignerProposalHost;
}

// Params for the catalog probe: a feet=0 estimate that returns the workspace's
// decor catalog (and roofline rate) without needing a drawn design yet.
// Cents-exact rounding, matching the backend's ``round(value, 2)`` on money.
const round2 = (value: number) => Math.round(value * 100) / 100;

const CATALOG_PARAMS: LinearFeetEstimateRequest = {
  feet: 0,
  channels: 0,
  takedown: false,
  storage: false,
  per_ft_override: null,
  christmas_per_ft_override: null,
  christmas_items: {},
};

export function LightDesigner({ workspaceId, proposal }: LightDesignerProps) {
  const fileRef = useRef<HTMLInputElement>(null);
  const hosted = Boolean(proposal);

  // Every photo the rep has open, in the order they added them. The *active*
  // shot's drawing lives in the editor reducer (that's what the canvas, palette
  // and undo stack act on); the others hold theirs here until they're switched
  // back to. `liveShots` below is the one place both halves are read together.
  const [shots, setShots] = useState<DesignerShot[]>(
    () => proposal?.initial?.shots ?? [],
  );
  const [activeShotId, setActiveShotId] = useState<string | null>(
    () => proposal?.initial?.shots?.[0]?.id ?? null,
  );
  const [state, dispatch] = useReducer(editorReducer, undefined, () => {
    const base = initialEditorState();
    const first = proposal?.initial?.shots?.[0];
    return {
      ...base,
      design: first?.design ?? base.design,
      dusk: first?.dusk ?? base.dusk,
    };
  });
  const { design, dusk } = state;

  const activeShot =
    shots.find((shot) => shot.id === activeShotId) ?? shots[0] ?? null;
  const photo: PhotoInfo | null = activeShot?.photo ?? null;
  // Shots as they stand right now: the stored list with the active shot's
  // drawing swapped in from the reducer. Everything that has to see the whole
  // job — totals, the save, the strip's "drawn" dots — reads this, never `shots`.
  const liveShots = useMemo(
    () =>
      shots.map((shot) =>
        shot.id === activeShot?.id ? { ...shot, design, dusk } : shot,
      ),
    [shots, activeShot?.id, design, dusk],
  );

  const [viewMode, setViewMode] = useState<ViewMode>("rep");
  // Which services this design covers. Multi-select: one photo of a house can
  // carry landscape fixtures, permanent track, and Christmas at once, and the
  // customer should see each one argued on its own terms.
  const [services, setServices] = useState<ServiceKey[]>(
    () => proposal?.initial?.services ?? ["landscape"],
  );
  const sells = (key: ServiceKey) => services.includes(key);
  const toggleService = (key: ServiceKey) => {
    setServices((prev) => {
      // Never let the rep switch every service off — the palette would be empty
      // with no way back. The last one stays on until another is picked.
      if (prev.includes(key)) {
        return prev.length === 1 ? prev : prev.filter((s) => s !== key);
      }
      return SERVICES.filter((spec) => spec.key === key || prev.includes(spec.key)).map(
        (spec) => spec.key,
      );
    });
  };
  const [takedown, setTakedown] = useState(false);
  const [storage, setStorage] = useState(false);
  // The rep's chosen Good/Better/Best seasonal package (a ChristmasPackage key).
  // null = no explicit pick yet; the resolver falls back to the most-inclusive
  // package, matching the server so the preview and the shared page agree.
  const [selectedPackage, setSelectedPackage] = useState<string | null>(null);
  // Internal-only per-linear-foot rate overrides for this estimate. null = use
  // the workspace's standard configured rate. Never shown to the client.
  const [perFtOverride, setPerFtOverride] = useState<number | null>(null);
  const [christmasPerFtOverride, setChristmasPerFtOverride] = useState<
    number | null
  >(null);
  // Standalone lines the rep typed for work the price book doesn't carry. Held
  // as raw drafts; only complete rows are priced (see `toEstimateCustomLines`).
  const [customLines, setCustomLines] = useState<CustomLineDraft[]>([]);

  const [shareUrl, setShareUrl] = useState<string | null>(null);
  const [shareToken, setShareToken] = useState<string | null>(null);
  const [sentTo, setSentTo] = useState<string | null>(null);
  // Which rail carried it. A bare "Sent to +15551234567" doesn't say whether the
  // homeowner got a text or an email, which is the one thing the rep needs to
  // know before following up.
  const [sentVia, setSentVia] = useState<SendChannel | null>(null);
  // Which rail is mid-send, so only the pressed button shows "Sending…" while
  // both stay disabled — a rep can't fire the text and the email at once.
  const [sendingChannel, setSendingChannel] = useState<SendChannel | null>(null);
  const [clientName, setClientName] = useState("");
  const [clientEmail, setClientEmail] = useState("");
  const [clientPhone, setClientPhone] = useState("");
  const [savedToCustomer, setSavedToCustomer] = useState(false);
  // The draft quote just created from this design (its number is shown inline
  // with a link into Quotes). Cleared whenever the priced inputs change.
  const [quoteResult, setQuoteResult] = useState<{ number: string } | null>(
    null,
  );
  const [aiOpen, setAiOpen] = useState(false);
  const [savingProposal, setSavingProposal] = useState(false);
  // What was last written onto the proposal, kept with the exact drawings it was
  // rendered from: the confirmation then falls away on the next stroke instead
  // of vouching for stale images.
  const [saved, setSaved] = useState<{
    at: string;
    shots: DesignerShot[];
  } | null>(null);
  const [saveError, setSaveError] = useState(false);

  // ---- Catalog (drawable palette) ---------------------------------------
  // Independent of the current design, so products are available the moment a
  // photo loads and the design→estimate mapping never chases its own tail.
  const { data: catalog } = useQuery({
    queryKey: queryKeys.estimator.compute(workspaceId, CATALOG_PARAMS),
    queryFn: () => estimatorApi.estimate(workspaceId, CATALOG_PARAMS),
    enabled: Boolean(photo),
    staleTime: 5 * 60_000,
  });

  // The landscape half of the palette is the workspace price book, so a fixture
  // drawn on the photo is a real inventory item with a SKU behind it.
  const { data: priceBook } = useQuery({
    queryKey: queryKeys.salesWizard.catalog(workspaceId),
    queryFn: () => salesWizardApi.listCatalog(workspaceId),
    enabled: Boolean(photo),
    staleTime: 5 * 60_000,
  });

  // Pricing config drives both the fixture-type resolution and whether the
  // client-facing roofline comparison is shown.
  const { data: pricing } = useQuery({
    queryKey: queryKeys.salesWizard.pricing(workspaceId),
    queryFn: () => salesWizardApi.getPricing(workspaceId),
    staleTime: 5 * 60_000,
  });

  // Which package the fixture types resolve against: the tier the rep is
  // quoting when hosted, else the workspace's headline package. Change the
  // package and every drawn fixture re-resolves to that package's product —
  // no redrawing, and the SKUs follow.
  const tierKey =
    proposal?.tierKey ?? pricing?.tier_order?.[0] ?? pricing?.tiers?.[0]?.key ?? null;
  const tierLabel =
    (pricing?.tiers ?? []).find((t) => t.key === tierKey)?.tab ??
    (pricing?.tiers ?? []).find((t) => t.key === tierKey)?.label ??
    "this package";
  const fixtureResolution = useMemo(
    () => resolveTierFixtures(pricing, priceBook, tierKey),
    [pricing, priceBook, tierKey],
  );
  const sellsLandscape = hasLandscapeFixtures(fixtureResolution);

  // The palette carries only the selected services, so a Christmas-only quote
  // never shows uplights and a landscape-only quote never shows wreaths.
  const products = useMemo(() => {
    const landscape =
      sells("landscape") && sellsLandscape
        ? [...buildFixturePalette(fixtureResolution), ...buildBistroCatalog(priceBook)]
        : [];
    const holiday = buildCatalog(catalog).filter((product) =>
      product.style === "permanent" ? sells("permanent") : sells("christmas"),
    );
    return [...landscape, ...holiday];
  }, [services, sellsLandscape, fixtureResolution, priceBook, catalog]);
  const productById = useMemo(() => indexProducts(products), [products]);

  // ---- Design → server estimate inputs ----------------------------------
  // Totalled across every photo: front elevation plus back patio is one job and
  // one price. Each shot measures on its own calibration before it's summed, so
  // photos taken from different distances still add up correctly.
  const inputs = useMemo(
    () =>
      sumEstimateInputs(
        liveShots.map((shot) =>
          designToEstimateInputs(shot.design, productById, shot.photo.width),
        ),
      ),
    [liveShots, productById],
  );
  const feet = inputs.feet;
  /** Anything drawn on the photo that's on screen (gates the AI render). */
  const activeDesignHas = hasDesign(design);
  /** Anything drawn anywhere (gates the save — every drawn shot goes across). */
  const designHas = liveShots.some((shot) => hasDesign(shot.design));
  const { calibrated } = designScale(design, photo?.width ?? 0);

  // Placed fixtures, resolved through the current package into the product the
  // crew will actually pull. Counts only — the wizard prices them server-side.
  const fixtureLines = useMemo(
    () =>
      FIXTURE_TYPES.map((spec) => {
        const count = inputs.fixtures[spec.type] ?? 0;
        const resolved = fixtureResolution[spec.type];
        return {
          type: spec.type,
          label: spec.label,
          count,
          productName: resolved.item?.name ?? null,
          sku: resolved.itemId,
        };
      }).filter((line) => line.count > 0),
    [inputs.fixtures, fixtureResolution],
  );
  // Types the rep drew that this package doesn't sell. Never substituted with a
  // product from another package — the rep is told, and picks.
  const unresolvedFixtures = fixtureLines.filter((line) => !line.sku);
  const fixtureCount = fixtureLines.reduce((sum, line) => sum + line.count, 0);
  const hasLandscape = fixtureCount > 0 || inputs.bistro_feet > 0;

  const customLineInputs = useMemo(
    () => toEstimateCustomLines(customLines),
    [customLines],
  );

  const estimateParams = useMemo<LinearFeetEstimateRequest>(
    () => ({
      feet,
      channels: 0,
      takedown,
      storage,
      per_ft_override: perFtOverride,
      christmas_per_ft_override: christmasPerFtOverride,
      christmas_items: inputs.christmas_items,
      selected_package: selectedPackage,
      custom_lines: customLineInputs,
    }),
    [
      feet,
      takedown,
      storage,
      perFtOverride,
      christmasPerFtOverride,
      inputs.christmas_items,
      selectedPackage,
      customLineInputs,
    ],
  );

  // Holiday pricing only: a landscape-only design has nothing for the roofline
  // comparison endpoint to price, and the Quote Builder owns landscape money. A
  // standalone line item is priced on its own, with or without a drawing — that
  // is the point of it — so it counts as something to price, share, and quote.
  const hasHolidayDesign =
    feet > 0 ||
    Object.keys(inputs.christmas_items).length > 0 ||
    customLineInputs.length > 0;

  const { data: estimate, isFetching } = useQuery({
    queryKey: queryKeys.estimator.compute(workspaceId, estimateParams),
    queryFn: () => estimatorApi.estimate(workspaceId, estimateParams),
    enabled: Boolean(photo) && hasHolidayDesign,
    placeholderData: keepPreviousData,
    staleTime: 60_000,
  });

  // Which sides a line item can be billed on. Falls back to the catalog probe so
  // the editor is available before anything is drawn — the standalone case, and
  // the reason this reads from a query rather than from what's on the photo.
  const sides = {
    permanent: Boolean((estimate ?? catalog)?.permanent.enabled),
    seasonal: Boolean((estimate ?? catalog)?.christmas.enabled),
  };

  // Resolve the seasonal package the rep is selling (explicit pick, else the
  // most-inclusive one). When packages are active the client sees this package's
  // total as the seasonal price, so the preview and the persisted share both
  // adopt it in place of the à la carte roofline+decor total.
  const selectedPkg = resolveSelectedPackage(
    estimate?.christmas_packages ?? [],
    selectedPackage,
  );
  // The package's own total plus any standalone lines (which sit outside every
  // package); à la carte already includes them. Same rule the server applies.
  const christmasTotal = seasonalTotal(
    {
      total: estimate?.christmas.total ?? 0,
      custom_total: estimate?.christmas.custom_total,
    },
    selectedPkg,
  );

  // Mirror of the server's ``build_public_roofline_comparison`` so the preview
  // shows exactly what the shared page will render (same pattern as
  // ``resolveSelectedPackage`` mirroring the backend's recommended-package rule).
  // Roofline against roofline from the à la carte costs — never a package's,
  // which is $0 for a package that excludes the roofline.
  const rooflineView = useMemo(() => {
    if (!pricing?.roofline_comparison_enabled || !estimate) return null;
    if (!estimate.permanent.enabled || !estimate.christmas.enabled) return null;
    const seasonal = estimate.christmas.roofline_cost;
    const multiYear = round2(seasonal * estimate.years);
    return {
      permanent_total: estimate.permanent.roofline_cost,
      seasonal_total: seasonal,
      seasonal_multi_year: multiYear,
      savings: round2(multiYear - estimate.permanent.roofline_cost),
    };
  }, [pricing?.roofline_comparison_enabled, estimate]);

  // Any change to the priced inputs invalidates a previously saved link so the
  // "Saved to customer" confirmation can never read as current after an edit.
  const resetShare = useCallback(() => {
    setShareUrl(null);
    setShareToken(null);
    setSentTo(null);
    setSentVia(null);
    setSavedToCustomer(false);
    setQuoteResult(null);
  }, []);
  useEffect(() => {
    resetShare();
  }, [estimateParams, resetShare]);

  // ---- Shots (photos in this design) -------------------------------------
  /**
   * Park the active shot's drawing back in the list. Called before anything that
   * moves the reducer off it — switching, removing, adding — so a drawing is
   * never left behind in a reducer that's about to be reset.
   */
  const commitActive = useCallback(
    (list: DesignerShot[]) =>
      list.map((shot) =>
        shot.id === activeShot?.id ? { ...shot, design, dusk } : shot,
      ),
    [activeShot?.id, design, dusk],
  );

  /** Load a shot into the editor. History is per-shot, so it starts clean. */
  const openShot = (target: DesignerShot) => {
    dispatch({ type: "RESET", design: target.design });
    dispatch({ type: "SET_DUSK", dusk: target.dusk });
    setActiveShotId(target.id);
    setViewMode("rep");
  };

  const selectShot = (id: string) => {
    if (id === activeShot?.id) return;
    const target = shots.find((shot) => shot.id === id);
    if (!target) return;
    const next = commitActive(shots);
    setShots(next);
    proposal?.onShotsChange(next);
    openShot(next.find((shot) => shot.id === id) ?? target);
  };

  const removeShot = (id: string) => {
    const index = shots.findIndex((shot) => shot.id === id);
    if (index < 0) return;
    // Committing first keeps the *other* shots' edits: if the rep deletes a
    // photo they aren't on, the one they were drawing must not lose its work.
    const next = commitActive(shots).filter((shot) => shot.id !== id);
    setShots(next);
    proposal?.onShotsChange(next);
    if (id !== activeShot?.id) return;
    const fallback = next[index] ?? next[index - 1] ?? null;
    if (fallback) {
      openShot(fallback);
      return;
    }
    // Last photo gone: back to the welcome screen with a clean editor.
    setActiveShotId(null);
    dispatch({ type: "RESET" });
  };

  const atShotCap = shots.length >= MAX_SHOTS;

  // ---- Photo upload ------------------------------------------------------
  // Always *adds* a photo. The rep designs the front, adds the back, and both
  // stay — nothing they drew is traded away for the next angle.
  const onFile = async (ev: React.ChangeEvent<HTMLInputElement>) => {
    const file = ev.target.files?.[0];
    ev.target.value = "";
    if (!file || atShotCap) return;
    try {
      const info = await fileToPhoto(file);
      const shot: DesignerShot = {
        id: nextId("shot"),
        photo: info,
        design: EMPTY_DESIGN,
        dusk,
      };
      const next = [...commitActive(shots), shot];
      setShots(next);
      proposal?.onShotsChange(next);
      openShot(shot);
      // Only the first photo starts the estimate over. Later photos are more of
      // the same job, so the rep's takedown/rate/line-item work stays put.
      if (!shots.length) {
        setTakedown(false);
        setStorage(false);
        setPerFtOverride(null);
        setChristmasPerFtOverride(null);
        setSelectedPackage(null);
        setCustomLines([]);
      }
      resetShare();
    } catch {
      window.alert("Could not read that image file.");
    }
  };

  // ---- Save onto the proposal (Quote Builder host) -----------------------
  // Every drawn shot is composited and sent together, so the proposal shows the
  // whole job. Blank shots (a photo the rep added but never drew on) are left
  // out rather than shipped to the customer as an unlit snapshot.
  const saveToProposal = async () => {
    if (!proposal || savingProposal) return;
    const drawn = liveShots.filter((shot) => hasDesign(shot.design));
    if (!drawn.length) return;
    setSavingProposal(true);
    setSaveError(false);
    // Park the active shot's drawing in the list (and in the host) before the
    // await: what's saved to the proposal is what re-opens in the designer.
    setShots(liveShots);
    proposal.onShotsChange(liveShots);
    try {
      const rendered = await Promise.all(
        drawn.map(async (shot) => ({
          image: await exportDesignJpeg(shot.photo, shot.design, productById, {
            dusk: shot.dusk,
          }),
          design: shot.design,
          dusk: shot.dusk,
        })),
      );
      proposal.onSave({
        shots: rendered,
        services,
        fixtures: inputs.fixtures as Partial<Record<FixtureType, number>>,
        rooflineFeet: feet,
        bistroFeet: inputs.bistro_feet,
      });
      setSaved({
        at: new Date().toLocaleTimeString([], {
          hour: "numeric",
          minute: "2-digit",
        }),
        shots: drawn,
      });
    } catch {
      setSaveError(true);
    } finally {
      setSavingProposal(false);
    }
  };

  // ---- Save / share / email ---------------------------------------------
  const shareParams = {
    ...estimateParams,
    // Persist the concrete package key (resolved default included) so the public
    // page folds this package's total instead of falling back to à la carte.
    selected_package: selectedPkg?.key ?? null,
    client_name: clientName.trim() || null,
    client_email: clientEmail.trim() || null,
    client_phone: clientPhone.trim() || null,
  };
  const shareMutation = useMutation({
    mutationFn: () => estimatorApi.share(workspaceId, shareParams),
    onSuccess: (result) => {
      setShareUrl(result.url);
      setShareToken(result.token);
      setSavedToCustomer(result.saved_to_customer);
      setSentTo(null);
      setSentVia(null);
    },
  });

  const deliverMutation = useMutation({
    mutationFn: ({ token, channel }: { token: string; channel: SendChannel }) =>
      estimatorApi.deliver(
        workspaceId,
        token,
        (channel === "email" ? clientEmail : clientPhone).trim() || null,
        channel,
      ),
    onSuccess: (result) => {
      setSentTo(result.to);
      setSentVia(result.channel);
    },
  });

  // Convert the drawn design into a real draft quote. ``side`` picks which
  // priced option the customer is buying; the seasonal side carries the chosen
  // package. Every line is recomputed server-side, so this only sends inputs.
  const createQuoteMutation = useMutation({
    mutationFn: (side: "permanent" | "seasonal") =>
      estimatorApi.createQuote(workspaceId, { ...shareParams, side }),
    onSuccess: (quote) => setQuoteResult({ number: quote.number }),
  });
  const quotePending = createQuoteMutation.isPending;

  // One-click "send the estimate", by email or text. Both buttons are always
  // visible on every estimate. If the rep hasn't saved a share link yet we mint
  // one first, then deliver it — so sending never depends on remembering to
  // press "Save & share" beforehand.
  const sendPending = shareMutation.isPending || deliverMutation.isPending;
  // The server's own words, not a generic retry line: a failed text usually
  // means something the rep can fix right now ("add a number under Settings",
  // "this number has opted out"), and that is exactly what gets swallowed by a
  // hardcoded "couldn't send".
  const sendFailure = deliverMutation.error ?? shareMutation.error;
  const sendError = sendFailure
    ? getApiErrorMessage(sendFailure, "Couldn’t send the estimate — try again.")
    : null;
  const canSend = (channel: SendChannel) =>
    hasHolidayDesign &&
    (channel === "email" ? clientEmail : clientPhone).trim().length > 0;
  const sendEstimate = async (channel: SendChannel) => {
    if (!canSend(channel) || sendPending) return;
    setSendingChannel(channel);
    try {
      let token = shareToken;
      if (!token) {
        const shared = await shareMutation.mutateAsync();
        token = shared.token;
      }
      if (token) await deliverMutation.mutateAsync({ token, channel });
    } catch {
      // Surfaced to the rep via shareMutation/deliverMutation isError below.
    } finally {
      setSendingChannel(null);
    }
  };

  const editCustomer =
    (setter: (value: string) => void) => (value: string) => {
      setter(value);
      resetShare();
    };

  const makeRateHandler =
    (setRate: (v: number | null) => void) => (raw: string) => {
      const n = Number(raw);
      setRate(raw === "" || Number.isNaN(n) ? null : Math.max(0, n));
    };
  const onPermanentRateChange = makeRateHandler(setPerFtOverride);
  const onChristmasRateChange = makeRateHandler(setChristmasPerFtOverride);

  // The AI render prompt follows what was actually drawn: a landscape design
  // must never come back looking like a Christmas installation.
  const renderMode: EstimateRenderRequest["mode"] = hasLandscape
    ? "landscape"
    : estimate?.permanent.enabled && !estimate?.christmas.enabled
      ? "permanent"
      : "seasonal";

  const clientView: ComparisonView | null = estimate
    ? {
        currency: "USD",
        permanent: estimate.permanent,
        christmas: { enabled: estimate.christmas.enabled, total: christmasTotal },
        christmasName: selectedPkg ? packageName(selectedPkg) : null,
        difference: estimate.difference,
        years: estimate.years,
        temporary_multi_year: estimate.temporary_multi_year,
        permanent_one_time: estimate.permanent_one_time,
        multi_year_savings: estimate.multi_year_savings,
        permanent_perks: estimate.permanent_perks,
        christmas_perks: estimate.christmas_perks,
        // Feet-free ladder for the client preview: only each package's total
        // crosses over (never the roofline breakdown), so the rep sees exactly
        // the Good/Better/Best cards the homeowner gets, with their pick flagged.
        christmasPackages: (estimate.christmas_packages ?? []).map((pkg) => ({
          key: pkg.key,
          name: packageName(pkg),
          marker: pkg.marker,
          total: pkg.pricing.total,
          valueTag: pkg.value_tag,
          popular: pkg.popular,
          recommended: pkg.key === selectedPkg?.key,
          points: pkg.points,
          experience: pkg.experience,
        })),
        roofline: rooflineView,
        // Server-priced add-ons, itemized for the client exactly as the shared
        // page lists them — the preview is what the homeowner will see. A line
        // scoped to a tier they aren't being sold is already inside a different
        // card's total, so it is filtered out here the same way
        // ``get_public_comparison`` filters it, and the preview can't promise
        // work that isn't on this price.
        customLines: (estimate.custom_lines ?? [])
          .filter(
            (line) =>
              !line.package_key || line.package_key === selectedPkg?.key,
          )
          .map((line) => ({
            label: line.label,
            description: line.description,
            quantity: line.quantity,
            amount: line.amount,
            side: line.side,
            packageKey: line.package_key,
          })),
      }
    : null;

  const copyLink = () => {
    if (shareUrl) void navigator.clipboard?.writeText(shareUrl);
  };

  // Derived, not stored: drawings are replaced immutably on every edit, so a
  // reference match across the drawn shots means the saved composites still show
  // what's on the photos. Adding or removing a shot invalidates it too.
  const drawnShots = liveShots.filter((shot) => hasDesign(shot.design));
  const savedAt =
    saved &&
    saved.shots.length === drawnShots.length &&
    saved.shots.every(
      (shot, i) =>
        shot.id === drawnShots[i]?.id &&
        shot.design === drawnShots[i]?.design &&
        shot.dusk === drawnShots[i]?.dusk,
    )
      ? saved.at
      : null;

  return (
    <div className="cmp-view est-app">
      <div className="est-topbar">
        <div className="cmp-brand">Light Designer</div>
        <div className="est-topbar-actions">
          <button
            className="est-btn"
            type="button"
            disabled={atShotCap}
            title={
              atShotCap
                ? `Up to ${MAX_SHOTS} photos in one design`
                : "Add another photo of this job \u2014 the ones you\u2019ve drawn stay"
            }
            onClick={() => fileRef.current?.click()}
          >
            {photo ? "\uFF0B Add photo" : "Upload house photo"}
          </button>
          <input
            ref={fileRef}
            type="file"
            accept="image/*"
            hidden
            onChange={onFile}
          />
          {photo ? (
            <div
              className="est-service-toggle"
              role="group"
              aria-label="Services in this design"
            >
              {SERVICES.map((spec) => (
                <button
                  key={spec.key}
                  type="button"
                  className={sells(spec.key) ? "active" : ""}
                  aria-pressed={sells(spec.key)}
                  title={spec.summary}
                  onClick={() => toggleService(spec.key)}
                >
                  {spec.label}
                </button>
              ))}
            </div>
          ) : null}
          {photo && !hosted ? (
            <div className="est-mode-toggle" role="group" aria-label="View mode">
              <button
                type="button"
                className={viewMode === "rep" ? "active" : ""}
                aria-pressed={viewMode === "rep"}
                onClick={() => setViewMode("rep")}
              >
                Rep view
              </button>
              <button
                type="button"
                className={viewMode === "client" ? "active" : ""}
                aria-pressed={viewMode === "client"}
                onClick={() => setViewMode("client")}
              >
                Client preview
              </button>
            </div>
          ) : null}
          {photo ? (
            <button
              className="est-btn"
              type="button"
              disabled={!activeDesignHas}
              title={
                activeDesignHas
                  ? undefined
                  : "Draw the lights on this photo first, then render a photorealistic version"
              }
              onClick={() => setAiOpen(true)}
            >
              AI render
            </button>
          ) : null}
          {proposal ? (
            <>
              <button
                className="est-btn primary"
                type="button"
                disabled={!designHas || savingProposal}
                title={
                  designHas
                    ? `Save ${drawnShots.length} design${drawnShots.length === 1 ? "" : "s"} onto the proposal`
                    : "Add a photo and draw the design first"
                }
                onClick={() => void saveToProposal()}
              >
                {savingProposal
                  ? "Saving…"
                  : drawnShots.length > 1
                    ? `Save ${drawnShots.length} designs to proposal`
                    : "Save to proposal"}
              </button>
              <button
                className="est-btn"
                type="button"
                // Hand the drawings over on the way out so stepping back to the
                // quote and returning resumes every photo mid-design, saved or
                // not — the editor unmounts, and the host is where they live.
                onClick={() => {
                  proposal.onShotsChange(liveShots);
                  proposal.onClose();
                }}
              >
                Back to quote
              </button>
            </>
          ) : null}
        </div>
      </div>

      {shots.length ? (
        <div className="est-shotbar" aria-label="Photos in this design">
          {liveShots.map((shot, i) => {
            const drawn = hasDesign(shot.design);
            const isActive = shot.id === activeShot?.id;
            return (
              <div
                className={`est-shot${isActive ? " active" : ""}`}
                key={shot.id}
              >
                <button
                  type="button"
                  // Not a tablist: the canvas it switches isn't a tabpanel, and
                  // claiming the relationship would lie to a screen reader.
                  // `aria-current` is the honest read — which of the set is open.
                  aria-current={isActive}
                  className="est-shot-pick"
                  aria-label={`Photo ${i + 1}${drawn ? ", designed" : ", nothing drawn yet"}`}
                  onClick={() => selectShot(shot.id)}
                >
                  {/* eslint-disable-next-line @next/next/no-img-element -- in-memory data URL */}
                  <img src={shot.photo.dataUrl} alt="" />
                  <span className="est-shot-no">{i + 1}</span>
                  {drawn ? <span className="est-shot-dot" aria-hidden /> : null}
                </button>
                <button
                  type="button"
                  className="est-shot-del"
                  aria-label={`Remove photo ${i + 1}`}
                  onClick={() => removeShot(shot.id)}
                >
                  &times;
                </button>
              </div>
            );
          })}
          <button
            type="button"
            className="est-shot-add"
            disabled={atShotCap}
            onClick={() => fileRef.current?.click()}
          >
            <span aria-hidden>&#65291;</span>
            {atShotCap ? `Max ${MAX_SHOTS} photos` : "Add photo"}
          </button>
          <span className="est-shot-hint">
            Each photo keeps its own design. Measurements add up across all of
            them.
          </span>
        </div>
      ) : null}

      {hosted && (savedAt || saveError) ? (
        <div
          className={`est-hosted-status${saveError ? " error" : ""}`}
          role="status"
        >
          {saveError
            ? "Couldn’t save the design — try again."
            : `Saved ${drawnShots.length} design${drawnShots.length === 1 ? "" : "s"} to the proposal at ${savedAt}. ${drawnShots.length === 1 ? "It shows" : "They show"} on the presentation and the client’s page.`}
        </div>
      ) : null}

      {photo ? (
        <>
          <div className="est-main">
            <ToolPalette products={products} state={state} dispatch={dispatch} />
            <LightCanvas
              // Remount per shot: zoom, pan and any half-drawn run belong to the
              // photo they were made on and must not follow the rep to the next.
              key={activeShot?.id}
              photo={photo}
              products={products}
              state={state}
              dispatch={dispatch}
            />
            <div className="est-side">
              {hasLandscape ? (
                <div className="ep-panel">
                  <div className="ep-title">Landscape fixtures</div>
                  <div className="ep-lines">
                    {fixtureLines.map((line) => (
                      <div className="ep-line" key={line.type}>
                        <span className="ep-line-name">
                          {line.label}
                          <span
                            className={`ep-line-sku${line.sku ? "" : " missing"}`}
                          >
                            {line.sku
                              ? `${line.productName} · ${line.sku}`
                              : `Not sold in ${tierLabel}`}
                          </span>
                        </span>
                        <span className="ep-line-amount">×{line.count}</span>
                      </div>
                    ))}
                    {inputs.bistro_feet > 0 ? (
                      <div className="ep-line">
                        <span className="ep-line-name">
                          Bistro / string lighting
                        </span>
                        <span className="ep-line-amount">
                          {inputs.bistro_feet} ft
                        </span>
                      </div>
                    ) : null}
                  </div>
                  {unresolvedFixtures.length > 0 ? (
                    <p className="ep-pkg-warn">
                      {tierLabel} doesn’t include{" "}
                      {unresolvedFixtures.map((l) => l.label.toLowerCase()).join(" or ")}
                      . Pick a package that sells{" "}
                      {unresolvedFixtures.length > 1 ? "them" : "it"}, or remove{" "}
                      {unresolvedFixtures.length > 1 ? "those" : "that"} from the
                      photo.
                    </p>
                  ) : null}
                  <p className="ep-pkg-hint">
                    {hosted
                      ? `Priced as ${tierLabel}. Saving pushes these counts into the quote, where the server prices them and expands each fixture’s parts list for the crew.`
                      : `Showing ${tierLabel} products. Landscape fixtures are priced in the Quote Builder, which expands each fixture’s parts list for the crew.`}
                  </p>
                  {!hosted ? (
                    <Link
                      className="est-btn est-save-btn"
                      href="/sales-wizard?service=landscape"
                    >
                      Price these in Quote Builder
                    </Link>
                  ) : null}
                </div>
              ) : null}

              {hasHolidayDesign || !hasLandscape ? (
                <EstimatePanel
                  estimate={estimate}
                  isFetching={isFetching}
                  feet={feet}
                  calibrated={calibrated}
                  hasDesign={hasHolidayDesign}
                  selectedPackage={selectedPackage}
                  onSelectPackage={setSelectedPackage}
                  customLines={customLines}
                  onChangeCustomLines={setCustomLines}
                  sides={sides}
                  allowCustomLines={!hosted}
                />
              ) : null}

              {!hosted ? (
                <>
                  <div className="est-options">
                    <label className="est-opt-check">
                      <input
                        type="checkbox"
                        checked={takedown}
                        onChange={(e) => setTakedown(e.target.checked)}
                      />
                      Include seasonal takedown
                    </label>
                    <label className="est-opt-check">
                      <input
                        type="checkbox"
                        checked={storage}
                        onChange={(e) => setStorage(e.target.checked)}
                      />
                      Include off-season storage
                    </label>
                    {estimate?.permanent.enabled ? (
                      <label className="est-opt-rate">
                        <span>Permanent $/ft</span>
                        <input
                          className="est-input"
                          type="number"
                          min={0}
                          step={1}
                          inputMode="decimal"
                          value={perFtOverride ?? ""}
                          placeholder={String(estimate.permanent.per_ft)}
                          onChange={(e) => onPermanentRateChange(e.target.value)}
                          aria-label="Internal permanent linear-foot rate override"
                        />
                        <span className="est-internal-badge">Internal</span>
                      </label>
                    ) : null}
                    {estimate?.christmas.enabled ? (
                      <label className="est-opt-rate">
                        <span>Seasonal $/ft</span>
                        <input
                          className="est-input"
                          type="number"
                          min={0}
                          step={1}
                          inputMode="decimal"
                          value={christmasPerFtOverride ?? ""}
                          placeholder={String(estimate.christmas.per_ft)}
                          onChange={(e) => onChristmasRateChange(e.target.value)}
                          aria-label="Internal seasonal linear-foot rate override"
                        />
                        <span className="est-internal-badge">Internal</span>
                      </label>
                    ) : null}
                  </div>

                  <div className="est-customer">
                    <div className="est-customer-title">Save to customer</div>
                    <div className="est-customer-fields">
                      <input
                        className="est-input"
                        type="text"
                        placeholder="Customer name"
                        autoComplete="off"
                        value={clientName}
                        onChange={(e) =>
                          editCustomer(setClientName)(e.target.value)
                        }
                        aria-label="Customer name"
                      />
                      <input
                        className="est-input"
                        type="email"
                        placeholder="Email"
                        autoComplete="off"
                        value={clientEmail}
                        onChange={(e) =>
                          editCustomer(setClientEmail)(e.target.value)
                        }
                        aria-label="Customer email"
                      />
                      <input
                        className="est-input"
                        type="tel"
                        placeholder="Phone"
                        autoComplete="off"
                        value={clientPhone}
                        onChange={(e) =>
                          editCustomer(setClientPhone)(e.target.value)
                        }
                        aria-label="Customer phone"
                      />
                    </div>
                    <div className="est-customer-hint">
                      Add a phone number to save this estimate to a customer
                      record. Without one you can still share the link.
                    </div>
                    <div className="est-send-actions">
                      <button
                        className="est-btn primary est-save-btn"
                        type="button"
                        disabled={!canSend("email") || sendPending}
                        title={
                          canSend("email")
                            ? `Email the estimate to ${clientEmail.trim()}`
                            : "Draw the holiday design and add a customer email to send the estimate"
                        }
                        onClick={() => void sendEstimate("email")}
                      >
                        {sendingChannel === "email"
                          ? "Sending…"
                          : "\u2709 Email estimate"}
                      </button>
                      <button
                        className="est-btn primary est-save-btn"
                        type="button"
                        disabled={!canSend("sms") || sendPending}
                        title={
                          canSend("sms")
                            ? `Text the estimate to ${clientPhone.trim()}`
                            : "Draw the holiday design and add a customer phone to text the estimate"
                        }
                        onClick={() => void sendEstimate("sms")}
                      >
                        {sendingChannel === "sms"
                          ? "Sending…"
                          : "\u260e Text estimate"}
                      </button>
                    </div>
                    <button
                      className="est-btn est-save-btn"
                      type="button"
                      disabled={!hasHolidayDesign || shareMutation.isPending}
                      onClick={() => shareMutation.mutate()}
                    >
                      {shareMutation.isPending
                        ? "Saving…"
                        : "Save & share link only"}
                    </button>
                    {sendError ? (
                      <div className="est-send-row">
                        <span className="est-send-error">{sendError}</span>
                      </div>
                    ) : null}

                    {estimate &&
                    (estimate.permanent.enabled ||
                      estimate.christmas.enabled) ? (
                      <div className="est-quote-convert">
                        <div className="est-quote-convert-title">
                          Turn this design into a quote
                        </div>
                        {estimate.permanent.enabled ? (
                          <button
                            className="est-btn primary est-save-btn"
                            type="button"
                            disabled={!hasHolidayDesign || quotePending}
                            onClick={() =>
                              createQuoteMutation.mutate("permanent")
                            }
                          >
                            {quotePending
                              ? "Creating…"
                              : estimate.christmas.enabled
                                ? "Create permanent quote"
                                : "Create quote"}
                          </button>
                        ) : null}
                        {estimate.christmas.enabled ? (
                          <button
                            className="est-btn est-save-btn"
                            type="button"
                            disabled={!hasHolidayDesign || quotePending}
                            onClick={() =>
                              createQuoteMutation.mutate("seasonal")
                            }
                          >
                            {quotePending
                              ? "Creating…"
                              : estimate.permanent.enabled
                                ? "Create seasonal quote"
                                : "Create quote"}
                          </button>
                        ) : null}
                        <div className="est-customer-hint">
                          Creates a draft quote with itemized, server-priced
                          lines. Review and send it from Quotes.
                        </div>
                        {quoteResult ? (
                          <div className="est-saved-note">
                            Quote {quoteResult.number} created ·{" "}
                            <Link href="/quotes" className="est-quote-link">
                              Open in Quotes
                            </Link>
                          </div>
                        ) : null}
                        {createQuoteMutation.isError ? (
                          <div className="est-send-row">
                            <span className="est-send-error">
                              Couldn’t create the quote — draw a design, then try
                              again.
                            </span>
                          </div>
                        ) : null}
                      </div>
                    ) : null}
                  </div>

                  {shareUrl ? (
                    <div className="est-share">
                      {savedToCustomer ? (
                        <div className="est-saved-note">
                          Saved to customer
                          {clientName.trim() ? ` · ${clientName.trim()}` : ""}
                        </div>
                      ) : null}
                      <div className="est-share-link">
                        <input
                          value={shareUrl}
                          readOnly
                          aria-label="Client link"
                        />
                        <button
                          className="est-btn"
                          type="button"
                          onClick={copyLink}
                        >
                          Copy
                        </button>
                      </div>
                      {sentTo ? (
                        <div className="est-send-row">
                          <span className="est-sent-note">
                            {sentVia === "sms" ? "Texted to" : "Emailed to"}{" "}
                            {sentTo}
                          </span>
                        </div>
                      ) : null}
                    </div>
                  ) : null}
                </>
              ) : null}
            </div>
          </div>

          {viewMode === "client" && !hosted ? (
            // The client theme follows what's being sold: a Christmas quote gets
            // the holiday palette, a landscape quote stays brass-on-black. The
            // preview mirrors whatever the homeowner will actually see.
            <div
              className={`est-client-preview ${clientThemeClass(services)}`.trim()}
            >
              <ServiceValueProps
                services={services}
                pricing={pricing}
                tierKey={tierKey}
              />
              {clientView ? <ComparisonCard view={clientView} /> : null}
            </div>
          ) : null}

          {aiOpen && photo ? (
            <AIRenderModal
              workspaceId={workspaceId}
              photo={photo}
              design={design}
              productById={productById}
              mode={renderMode}
              onClose={() => setAiOpen(false)}
            />
          ) : null}
        </>
      ) : (
        <div className="est-welcome">
          <div className="est-welcome-card">
            <div className="est-welcome-bulbs" aria-hidden>
              <i style={{ background: "#ffd98a" }} />
              <i style={{ background: "#ff5252" }} />
              <i style={{ background: "#54ff77" }} />
              <i style={{ background: "#5aa2ff" }} />
            </div>
            <h1>Design their lights on a photo</h1>
            <p>
              Upload a straight-on photo of the home, set the scale, then place
              landscape fixtures and draw glowing roofline, mini-lights, and
              wreaths. Drag the dusk slider to show it lit.
            </p>
            <p>
              Add a photo for every angle you’re selling — front, back, walkway.
              Each keeps its own design, and the quote covers all of them.
            </p>
            <button
              className="est-btn primary"
              type="button"
              onClick={() => fileRef.current?.click()}
            >
              Upload house photo
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
