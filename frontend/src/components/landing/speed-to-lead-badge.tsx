"use client";

import { useEffect, useState } from "react";

/** Shape returned by ``GET /api/v1/p/leads/{public_key}/proof``. */
export interface SpeedToLeadProof {
  enabled: boolean;
  sla_seconds: number;
  window_days: number;
  leads_measured: number;
  pct_within_sla: number | null;
  median_response_seconds: number | null;
  headline: string | null;
}

export interface SpeedToLeadBadgeProps {
  /** Public lead-source key (``ls_...``). */
  publicKey: string;
  /**
   * Absolute backend origin when embedded on a third-party site. Defaults to a
   * relative path so it works through the Next.js proxy inside the app.
   */
  apiBaseUrl?: string;
  className?: string;
}

/**
 * Public, embeddable proof badge that surfaces the workspace's
 * answered-within-target speed-to-lead stat on a lead-form widget.
 *
 * Renders nothing until the badge is enabled and has a published headline, so
 * it stays invisible for workspaces that opted out or lack enough data.
 */
export function SpeedToLeadBadge({
  publicKey,
  apiBaseUrl = "",
  className,
}: SpeedToLeadBadgeProps) {
  const [proof, setProof] = useState<SpeedToLeadProof | null>(null);

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();
    const url = `${apiBaseUrl}/api/v1/p/leads/${encodeURIComponent(
      publicKey
    )}/proof`;

    fetch(url, { signal: controller.signal })
      .then((res) => (res.ok ? (res.json() as Promise<SpeedToLeadProof>) : null))
      .then((data) => {
        if (!cancelled) setProof(data);
      })
      .catch(() => {
        if (!cancelled) setProof(null);
      });

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [publicKey, apiBaseUrl]);

  if (!proof || !proof.enabled || !proof.headline) return null;

  return (
    <div
      className={
        className ??
        "inline-flex items-center gap-2 rounded-full border border-emerald-200 bg-emerald-50 px-3 py-1.5 text-sm font-medium text-emerald-800"
      }
      role="status"
      aria-label="Speed-to-lead proof"
      data-testid="speed-to-lead-badge"
    >
      <span aria-hidden className="relative flex size-2">
        <span className="absolute inline-flex size-full animate-ping rounded-full bg-emerald-400 opacity-75" />
        <span className="relative inline-flex size-2 rounded-full bg-emerald-500" />
      </span>
      <span>{proof.headline}</span>
      <span className="text-emerald-600/70">
        · last {proof.window_days} days
      </span>
    </div>
  );
}
