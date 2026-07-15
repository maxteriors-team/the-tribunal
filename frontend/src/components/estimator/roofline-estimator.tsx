"use client";

/**
 * Holiday-Home-Concepts-style light designer (authenticated rep tool).
 *
 * The rep uploads a house photo, sets the scale from a known measurement, then
 * draws glowing C9 roofline, mini-lights on bushes/trees, and places wreaths
 * directly on the photo. The drawn design is mapped to feet/counts and priced
 * **server-side** into a live permanent-vs-seasonal comparison — the canvas
 * never computes money. A "Client preview" renders the exact feet-free
 * comparison the homeowner gets; "Save & share" mints a public link and can
 * email it to the customer.
 *
 * Layout: tool/product palette (left), photo design stage (center), itemized
 * estimate + customer/share (right).
 */
import { keepPreviousData, useMutation, useQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";

import { estimatorApi } from "@/lib/api/estimator";
import { buildCatalog, indexProducts } from "@/lib/estimator/catalog";
import {
  designScale,
  designToEstimateInputs,
  hasDesign,
} from "@/lib/estimator/design";
import { fileToPhoto } from "@/lib/estimator/photo";
import type { PhotoInfo } from "@/lib/estimator/types";
import { queryKeys } from "@/lib/query-keys";
import type { LinearFeetEstimateRequest } from "@/types/estimate";

import { ComparisonCard, type ComparisonView } from "./comparison-card";
import { editorReducer, initialEditorState } from "./editor-store";
import { EstimatePanel } from "./estimate-panel";
import { LightCanvas } from "./light-canvas";
import { ToolPalette } from "./tool-palette";
import "./estimator.css";

type ViewMode = "rep" | "client";

interface RooflineEstimatorProps {
  workspaceId: string;
}

// Params for the catalog probe: a feet=0 estimate that returns the workspace's
// decor catalog (and roofline rate) without needing a drawn design yet.
const CATALOG_PARAMS: LinearFeetEstimateRequest = {
  feet: 0,
  channels: 0,
  takedown: false,
  storage: false,
  per_ft_override: null,
  christmas_per_ft_override: null,
  christmas_items: {},
};

export function RooflineEstimator({ workspaceId }: RooflineEstimatorProps) {
  const fileRef = useRef<HTMLInputElement>(null);

  const [photo, setPhoto] = useState<PhotoInfo | null>(null);
  const [state, dispatch] = useReducer(editorReducer, undefined, initialEditorState);
  const { design } = state;

  const [viewMode, setViewMode] = useState<ViewMode>("rep");
  const [takedown, setTakedown] = useState(false);
  const [storage, setStorage] = useState(false);
  // Internal-only per-linear-foot rate overrides for this estimate. null = use
  // the workspace's standard configured rate. Never shown to the client.
  const [perFtOverride, setPerFtOverride] = useState<number | null>(null);
  const [christmasPerFtOverride, setChristmasPerFtOverride] = useState<
    number | null
  >(null);

  const [shareUrl, setShareUrl] = useState<string | null>(null);
  const [shareToken, setShareToken] = useState<string | null>(null);
  const [sentTo, setSentTo] = useState<string | null>(null);
  const [clientName, setClientName] = useState("");
  const [clientEmail, setClientEmail] = useState("");
  const [clientPhone, setClientPhone] = useState("");
  const [savedToCustomer, setSavedToCustomer] = useState(false);

  // ---- Catalog (drawable palette) ---------------------------------------
  // Independent of the current design, so products are available the moment a
  // photo loads and the design→estimate mapping never chases its own tail.
  const { data: catalog } = useQuery({
    queryKey: queryKeys.estimator.compute(workspaceId, CATALOG_PARAMS),
    queryFn: () => estimatorApi.estimate(workspaceId, CATALOG_PARAMS),
    enabled: Boolean(photo),
    staleTime: 5 * 60_000,
  });
  const products = useMemo(() => buildCatalog(catalog), [catalog]);
  const productById = useMemo(() => indexProducts(products), [products]);

  // ---- Design → server estimate inputs ----------------------------------
  const inputs = useMemo(
    () =>
      photo
        ? designToEstimateInputs(design, productById, photo.width)
        : { feet: 0, christmas_items: {} },
    [design, productById, photo],
  );
  const feet = inputs.feet;
  const designHas = hasDesign(design);
  const { calibrated } = designScale(design, photo?.width ?? 0);

  const estimateParams = useMemo<LinearFeetEstimateRequest>(
    () => ({
      feet,
      channels: 0,
      takedown,
      storage,
      per_ft_override: perFtOverride,
      christmas_per_ft_override: christmasPerFtOverride,
      christmas_items: inputs.christmas_items,
    }),
    [
      feet,
      takedown,
      storage,
      perFtOverride,
      christmasPerFtOverride,
      inputs.christmas_items,
    ],
  );

  const { data: estimate, isFetching } = useQuery({
    queryKey: queryKeys.estimator.compute(workspaceId, estimateParams),
    queryFn: () => estimatorApi.estimate(workspaceId, estimateParams),
    enabled: Boolean(photo) && designHas,
    placeholderData: keepPreviousData,
    staleTime: 60_000,
  });

  // Any change to the priced inputs invalidates a previously saved link so the
  // "Saved to customer" confirmation can never read as current after an edit.
  const resetShare = useCallback(() => {
    setShareUrl(null);
    setShareToken(null);
    setSentTo(null);
    setSavedToCustomer(false);
  }, []);
  useEffect(() => {
    resetShare();
  }, [estimateParams, resetShare]);

  // ---- Photo upload ------------------------------------------------------
  const onFile = async (ev: React.ChangeEvent<HTMLInputElement>) => {
    const file = ev.target.files?.[0];
    ev.target.value = "";
    if (!file) return;
    try {
      const info = await fileToPhoto(file);
      dispatch({ type: "RESET" });
      setPhoto(info);
      setViewMode("rep");
      setTakedown(false);
      setStorage(false);
      setPerFtOverride(null);
      setChristmasPerFtOverride(null);
      resetShare();
    } catch {
      window.alert("Could not read that image file.");
    }
  };

  // ---- Save / share / email ---------------------------------------------
  const shareParams = {
    ...estimateParams,
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
    },
  });

  const deliverMutation = useMutation({
    mutationFn: () =>
      estimatorApi.deliver(workspaceId, shareToken ?? "", clientEmail.trim() || null),
    onSuccess: (result) => setSentTo(result.to),
  });

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

  const clientView: ComparisonView | null = estimate
    ? {
        currency: "USD",
        permanent: estimate.permanent,
        christmas: estimate.christmas,
        difference: estimate.difference,
        years: estimate.years,
        temporary_multi_year: estimate.temporary_multi_year,
        permanent_one_time: estimate.permanent_one_time,
        multi_year_savings: estimate.multi_year_savings,
        permanent_perks: estimate.permanent_perks,
        christmas_perks: estimate.christmas_perks,
      }
    : null;

  const copyLink = () => {
    if (shareUrl) void navigator.clipboard?.writeText(shareUrl);
  };

  return (
    <div className="cmp-view est-app">
      <div className="est-topbar">
        <div className="cmp-brand">Light Designer</div>
        <div className="est-topbar-actions">
          <button
            className="est-btn"
            type="button"
            onClick={() => fileRef.current?.click()}
          >
            {photo ? "Change photo" : "Upload house photo"}
          </button>
          <input
            ref={fileRef}
            type="file"
            accept="image/*"
            hidden
            onChange={onFile}
          />
          {photo ? (
            <div className="est-mode-toggle" role="group" aria-label="View mode">
              <button
                type="button"
                className={viewMode === "rep" ? "active" : ""}
                onClick={() => setViewMode("rep")}
              >
                Rep view
              </button>
              <button
                type="button"
                className={viewMode === "client" ? "active" : ""}
                onClick={() => setViewMode("client")}
              >
                Client preview
              </button>
            </div>
          ) : null}
        </div>
      </div>

      {photo ? (
        <>
          <div className="est-main">
            <ToolPalette products={products} state={state} dispatch={dispatch} />
            <LightCanvas
              photo={photo}
              products={products}
              state={state}
              dispatch={dispatch}
            />
            <div className="est-side">
              <EstimatePanel
                estimate={estimate}
                isFetching={isFetching}
                feet={feet}
                calibrated={calibrated}
                hasDesign={designHas}
              />

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
                    onChange={(e) => editCustomer(setClientName)(e.target.value)}
                    aria-label="Customer name"
                  />
                  <input
                    className="est-input"
                    type="email"
                    placeholder="Email"
                    autoComplete="off"
                    value={clientEmail}
                    onChange={(e) => editCustomer(setClientEmail)(e.target.value)}
                    aria-label="Customer email"
                  />
                  <input
                    className="est-input"
                    type="tel"
                    placeholder="Phone"
                    autoComplete="off"
                    value={clientPhone}
                    onChange={(e) => editCustomer(setClientPhone)(e.target.value)}
                    aria-label="Customer phone"
                  />
                </div>
                <div className="est-customer-hint">
                  Add a phone number to save this estimate to a customer record.
                  Without one you can still share the link.
                </div>
                <button
                  className="est-btn primary est-save-btn"
                  type="button"
                  disabled={!designHas || shareMutation.isPending}
                  onClick={() => shareMutation.mutate()}
                >
                  {shareMutation.isPending ? "Saving…" : "Save & share"}
                </button>
              </div>

              {shareUrl ? (
                <div className="est-share">
                  {savedToCustomer ? (
                    <div className="est-saved-note">
                      ✓ Saved to customer
                      {clientName.trim() ? ` · ${clientName.trim()}` : ""}
                    </div>
                  ) : null}
                  <div className="est-share-link">
                    <input value={shareUrl} readOnly aria-label="Client link" />
                    <button className="est-btn" type="button" onClick={copyLink}>
                      Copy
                    </button>
                  </div>
                  <div className="est-send-row">
                    <button
                      className="est-btn primary"
                      type="button"
                      disabled={!clientEmail.trim() || deliverMutation.isPending}
                      title={
                        clientEmail.trim()
                          ? undefined
                          : "Add a customer email above to send the estimate"
                      }
                      onClick={() => deliverMutation.mutate()}
                    >
                      {deliverMutation.isPending
                        ? "Sending…"
                        : `✉ Email estimate to ${clientEmail.trim() || "customer"}`}
                    </button>
                    {sentTo ? (
                      <span className="est-sent-note">✓ Sent to {sentTo}</span>
                    ) : null}
                    {deliverMutation.isError ? (
                      <span className="est-send-error">
                        Couldn’t send — check the email and try again.
                      </span>
                    ) : null}
                  </div>
                </div>
              ) : null}
            </div>
          </div>

          {viewMode === "client" && clientView ? (
            <div className="est-client-preview">
              <ComparisonCard view={clientView} />
            </div>
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
              Upload a straight-on photo of the home, set the scale, then draw
              glowing roofline, mini-lights, and wreaths. Pricing updates live.
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
