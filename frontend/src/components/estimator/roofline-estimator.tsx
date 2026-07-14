"use client";

/**
 * Roofline linear-feet estimator (authenticated rep tool).
 *
 * The rep uploads a photo of the home, marks a known reference (front/garage
 * door) to set the scale, then traces the roofline. Feet is computed locally and
 * sent to the server, which returns what we'd charge for permanent vs seasonal
 * lighting. The rep sees the footage; a "Client view" toggle renders the exact
 * feet-free comparison the homeowner gets, and "Share" mints a public link.
 */
import { keepPreviousData, useMutation, useQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { estimatorApi } from "@/lib/api/estimator";
import {
  polylineLength,
  pxPerFoot,
  REFERENCE_PRESETS,
  rooflineFeet,
  type Point,
} from "@/lib/estimator/measure";
import { queryKeys } from "@/lib/query-keys";
import { formatCurrency } from "@/lib/utils/number";

import { ComparisonCard, type ComparisonView } from "./comparison-card";
import "./estimator.css";

type DrawMode = "reference" | "roofline";
type ViewMode = "rep" | "client";

interface RooflineEstimatorProps {
  workspaceId: string;
}

const MAX_CANVAS_W = 960;

export function RooflineEstimator({ workspaceId }: RooflineEstimatorProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const imgRef = useRef<HTMLImageElement | null>(null);

  const [hasImage, setHasImage] = useState(false);
  const [drawMode, setDrawMode] = useState<DrawMode>("reference");
  const [viewMode, setViewMode] = useState<ViewMode>("rep");
  const [referenceKey, setReferenceKey] = useState(REFERENCE_PRESETS[0].key);
  const [referencePts, setReferencePts] = useState<Point[]>([]);
  const [rooflinePts, setRooflinePts] = useState<Point[]>([]);
  const [takedown, setTakedown] = useState(false);
  const [storage, setStorage] = useState(false);
  // Internal-only per-linear-foot rate for this estimate. null = use the
  // workspace's standard configured rate. Never shown to the client.
  const [perFtOverride, setPerFtOverride] = useState<number | null>(null);
  const [shareUrl, setShareUrl] = useState<string | null>(null);

  const referenceFeet = useMemo(
    () => REFERENCE_PRESETS.find((p) => p.key === referenceKey)?.feet ?? 0,
    [referenceKey],
  );

  const feet = useMemo(
    () => rooflineFeet(rooflinePts, referencePts, referenceFeet),
    [rooflinePts, referencePts, referenceFeet],
  );

  const calibrated = pxPerFoot(polylineLength(referencePts), referenceFeet) > 0;

  // ---- Canvas rendering -------------------------------------------------
  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext("2d");
    const img = imgRef.current;
    if (!canvas || !ctx) return;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    if (!img) return;
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height);

    const drawPath = (pts: Point[], color: string) => {
      if (pts.length === 0) return;
      ctx.save();
      ctx.strokeStyle = color;
      ctx.fillStyle = color;
      ctx.lineWidth = 3;
      ctx.lineJoin = "round";
      ctx.beginPath();
      pts.forEach((p, i) => (i === 0 ? ctx.moveTo(p.x, p.y) : ctx.lineTo(p.x, p.y)));
      ctx.stroke();
      pts.forEach((p) => {
        ctx.beginPath();
        ctx.arc(p.x, p.y, 5, 0, Math.PI * 2);
        ctx.fill();
      });
      ctx.restore();
    };

    // Reference in gold, roofline in green.
    drawPath(referencePts, "#d4af5a");
    drawPath(rooflinePts, "#4ade80");
  }, [referencePts, rooflinePts]);

  useEffect(() => {
    draw();
  }, [draw, hasImage]);

  const onFile = (ev: React.ChangeEvent<HTMLInputElement>) => {
    const file = ev.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      const img = new Image();
      img.onload = () => {
        const canvas = canvasRef.current;
        if (!canvas) return;
        const scale = Math.min(1, MAX_CANVAS_W / img.width);
        canvas.width = Math.round(img.width * scale);
        canvas.height = Math.round(img.height * scale);
        imgRef.current = img;
        setReferencePts([]);
        setRooflinePts([]);
        setPerFtOverride(null);
        setShareUrl(null);
        setDrawMode("reference");
        setHasImage(true);
      };
      img.src = reader.result as string;
    };
    reader.readAsDataURL(file);
  };

  const canvasPoint = (ev: React.MouseEvent): Point => {
    const canvas = canvasRef.current!;
    const r = canvas.getBoundingClientRect();
    return {
      x: (ev.clientX - r.left) * (canvas.width / r.width),
      y: (ev.clientY - r.top) * (canvas.height / r.height),
    };
  };

  const onCanvasClick = (ev: React.MouseEvent) => {
    if (!hasImage) return;
    const p = canvasPoint(ev);
    setShareUrl(null);
    if (drawMode === "reference") {
      // Reference is exactly two points; a third click restarts it.
      setReferencePts((prev) => (prev.length >= 2 ? [p] : [...prev, p]));
    } else {
      setRooflinePts((prev) => [...prev, p]);
    }
  };

  const undo = () => {
    setShareUrl(null);
    if (drawMode === "reference") setReferencePts((p) => p.slice(0, -1));
    else setRooflinePts((p) => p.slice(0, -1));
  };

  const clearAll = () => {
    setReferencePts([]);
    setRooflinePts([]);
    setPerFtOverride(null);
    setShareUrl(null);
  };

  // ---- Server pricing ----------------------------------------------------
  const estimateParams = {
    feet,
    channels: 0,
    takedown,
    storage,
    per_ft_override: perFtOverride,
  };
  const { data: estimate, isFetching } = useQuery({
    queryKey: queryKeys.estimator.compute(workspaceId, estimateParams),
    queryFn: () => estimatorApi.estimate(workspaceId, estimateParams),
    enabled: feet > 0,
    placeholderData: keepPreviousData,
    staleTime: 60_000,
  });

  const shareMutation = useMutation({
    mutationFn: () => estimatorApi.share(workspaceId, estimateParams),
    onSuccess: (result) => setShareUrl(result.url),
  });

  const onRateChange = (raw: string) => {
    const n = Number(raw);
    setPerFtOverride(raw === "" || Number.isNaN(n) ? null : Math.max(0, n));
    setShareUrl(null);
  };

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
    <div className="cmp-view">
      <div className="est-shell">
        <div className="cmp-brand">Roofline Estimator</div>
        <div className="est-toolbar">
          <button
            className="est-btn"
            type="button"
            onClick={() => fileRef.current?.click()}
          >
            {hasImage ? "Change photo" : "Upload house photo"}
          </button>
          <input
            ref={fileRef}
            type="file"
            accept="image/*"
            hidden
            onChange={onFile}
          />

          {hasImage ? (
            <>
              <div className="est-mode-toggle" role="group" aria-label="Draw mode">
                <button
                  type="button"
                  className={drawMode === "reference" ? "active" : ""}
                  onClick={() => setDrawMode("reference")}
                >
                  1. Reference
                </button>
                <button
                  type="button"
                  className={drawMode === "roofline" ? "active" : ""}
                  onClick={() => setDrawMode("roofline")}
                >
                  2. Roofline
                </button>
              </div>

              <select
                className="est-select"
                value={referenceKey}
                onChange={(e) => setReferenceKey(e.target.value)}
                aria-label="Reference object"
              >
                {REFERENCE_PRESETS.map((p) => (
                  <option key={p.key} value={p.key}>
                    {p.label} ({p.feet} ft)
                  </option>
                ))}
              </select>

              <button className="est-btn" type="button" onClick={undo}>
                Undo
              </button>
              <button className="est-btn" type="button" onClick={clearAll}>
                Clear
              </button>
            </>
          ) : null}
        </div>

        {hasImage ? (
          <p className="est-hint">
            {drawMode === "reference"
              ? calibrated
                ? "Reference set. Switch to Roofline and trace the roof edge."
                : `Click the two ends of the ${
                    REFERENCE_PRESETS.find((p) => p.key === referenceKey)?.label
                  } to set the scale.`
              : "Click along the roofline to trace it. Add a point at every corner."}
          </p>
        ) : null}

        <div className="est-canvas-wrap">
          {hasImage ? (
            <canvas ref={canvasRef} onClick={onCanvasClick} />
          ) : (
            <div className="est-empty">
              Upload a straight-on photo of the home to start measuring.
            </div>
          )}
        </div>

        {hasImage ? (
          <>
            <div className="est-readout">
              <div className="est-metric">
                <span className="est-metric-value">
                  {calibrated ? `${feet} ft` : "—"}
                  <span className="est-internal-badge">Internal only</span>
                </span>
                <span className="est-metric-label">Measured roofline</span>
              </div>
              {estimate?.permanent.enabled ? (
                <div className="est-metric">
                  <span className="est-metric-value">
                    {formatCurrency(estimate.permanent.total)}
                  </span>
                  <span className="est-metric-label">Permanent</span>
                </div>
              ) : null}
              {estimate?.christmas.enabled ? (
                <div className="est-metric">
                  <span className="est-metric-value">
                    {formatCurrency(estimate.christmas.total)}
                  </span>
                  <span className="est-metric-label">Seasonal / yr</span>
                </div>
              ) : null}
            </div>

            <div className="est-toolbar">
              <label className="est-hint" style={{ display: "flex", gap: 6 }}>
                <input
                  type="checkbox"
                  checked={takedown}
                  onChange={(e) => setTakedown(e.target.checked)}
                />
                Include seasonal takedown
              </label>
              <label className="est-hint" style={{ display: "flex", gap: 6 }}>
                <input
                  type="checkbox"
                  checked={storage}
                  onChange={(e) => setStorage(e.target.checked)}
                />
                Include off-season storage
              </label>

              {estimate?.permanent.enabled ? (
                <label
                  className="est-hint"
                  style={{ display: "flex", gap: 6, alignItems: "center" }}
                >
                  <span>Linear-ft rate $</span>
                  <input
                    className="est-input"
                    style={{ width: 84 }}
                    type="number"
                    min={0}
                    step={1}
                    inputMode="decimal"
                    value={perFtOverride ?? ""}
                    placeholder={String(estimate.permanent.per_ft)}
                    onChange={(e) => onRateChange(e.target.value)}
                    aria-label="Internal linear-foot rate override"
                  />
                  <span className="est-internal-badge">Internal only</span>
                </label>
              ) : null}

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
                  Client view
                </button>
              </div>

              <button
                className="est-btn primary"
                type="button"
                disabled={feet <= 0 || shareMutation.isPending}
                onClick={() => shareMutation.mutate()}
              >
                {shareMutation.isPending ? "Creating link…" : "Share with client"}
              </button>
            </div>

            {shareUrl ? (
              <div className="est-share-link">
                <input value={shareUrl} readOnly aria-label="Client link" />
                <button className="est-btn" type="button" onClick={copyLink}>
                  Copy
                </button>
              </div>
            ) : null}

            {viewMode === "client" && clientView ? (
              <ComparisonCard view={clientView} />
            ) : null}
            {isFetching && !estimate ? (
              <p className="est-hint">Pricing…</p>
            ) : null}
          </>
        ) : null}
      </div>
    </div>
  );
}
