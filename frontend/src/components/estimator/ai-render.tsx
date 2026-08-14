"use client";

/**
 * AI photorealistic night-render modal — the visual "closer".
 *
 * Flattens the rep's drawn design over the photo (`exportDesignJpeg`) and sends
 * it to the server render endpoint, which calls the workspace's OpenAI image
 * model. The browser never handles a key and never sees a price — only the
 * composited design image crosses the wire. Generation is explicit (a button),
 * because each render spends on the workspace's OpenAI account.
 */
import { useMutation } from "@tanstack/react-query";
import { useState } from "react";

import { estimatorApi } from "@/lib/api/estimator";
import { exportDesignJpeg } from "@/lib/estimator/export";
import type { Design, Mode, PhotoInfo, Product } from "@/lib/estimator/types";

interface AIRenderModalProps {
  workspaceId: string;
  photo: PhotoInfo;
  design: Design;
  productById: Map<string, Product>;
  mode?: Mode;
  onClose: () => void;
}

function errorMessage(error: unknown): string {
  const res = (error as { response?: { data?: { message?: unknown } } })?.response;
  const message = res?.data?.message;
  if (typeof message === "string" && message.trim()) return message;
  return "The AI render couldn’t be generated. Please try again.";
}

export function AIRenderModal({
  workspaceId,
  photo,
  design,
  productById,
  mode = "seasonal",
  onClose,
}: AIRenderModalProps) {
  const [image, setImage] = useState<string | null>(null);
  const [showOriginal, setShowOriginal] = useState(false);

  const render = useMutation({
    mutationFn: async (): Promise<string> => {
      const composited = await exportDesignJpeg(photo, design, productById);
      const result = await estimatorApi.render(workspaceId, {
        image: composited,
        mode,
        prompt: null,
      });
      return result.image;
    },
    onSuccess: (rendered) => {
      setImage(rendered);
      setShowOriginal(false);
    },
  });

  const working = render.isPending;
  const isAerial = mode === "landscape";

  const download = () => {
    if (!image) return;
    const a = document.createElement("a");
    a.href = image;
    a.download = `ai-render-${mode}.jpg`;
    a.click();
  };

  return (
    <div className="ai-backdrop">
      <button
        type="button"
        className="ai-scrim"
        aria-label="Close AI render"
        disabled={working}
        onClick={onClose}
      />
      <div
        className="ai-modal"
        role="dialog"
        aria-modal="true"
        aria-label={isAerial ? "AI aerial render" : "AI realistic render"}
      >
        <div className="ai-modal-head">
          <h3>{isAerial ? "✨ AI aerial render" : "✨ AI realistic render"}</h3>
          <button
            className="ai-close"
            type="button"
            aria-label="Close"
            disabled={working}
            onClick={onClose}
          >
            ×
          </button>
        </div>

        <p className="ai-modal-note">
          {isAerial
            ? "Turns the top-down lighting plan into a nighttime aerial visualization without changing viewpoint."
            : "Turns the drawn design into a photorealistic night photo of this home — the closer for skeptical customers."}{" "}
          Each render uses your workspace’s OpenAI account.
        </p>

        <div className="ai-stage">
          {image ? (
            // eslint-disable-next-line @next/next/no-img-element -- render is a data URL, not a static asset
            <img
              src={showOriginal ? photo.dataUrl : image}
              alt={isAerial ? "AI aerial night render" : "AI night render"}
              onPointerDown={() => setShowOriginal(true)}
              onPointerUp={() => setShowOriginal(false)}
              onPointerLeave={() => setShowOriginal(false)}
            />
          ) : working ? (
            <div className="ai-progress">
              <div className="ai-spinner" aria-hidden />
              <p>
                {isAerial ? "Rendering the aerial night plan…" : "Painting the night scene…"}{" "}
                (~15–40s)
              </p>
            </div>
          ) : (
            <div className="ai-placeholder">
              <p>
                {isAerial
                  ? "Generate a top-down nighttime version of the aerial plan."
                  : "Generate a photorealistic version of the drawn design."}
              </p>
            </div>
          )}
        </div>

        {image ? (
          <p className="ai-compare-hint">
            Press and hold the image to compare with the original {isAerial ? "aerial" : "photo"}.
          </p>
        ) : null}

        {render.isError ? (
          <p className="ai-error">{errorMessage(render.error)}</p>
        ) : null}

        <div className="ai-actions">
          <button className="est-btn" type="button" onClick={onClose} disabled={working}>
            Close
          </button>
          {image ? (
            <button className="est-btn" type="button" onClick={download}>
              ⬇ Download
            </button>
          ) : null}
          <button
            className="est-btn primary"
            type="button"
            disabled={working}
            onClick={() => render.mutate()}
          >
            {working
              ? "Rendering…"
              : image
                ? "↻ Regenerate"
                : isAerial
                  ? "✨ Generate aerial render"
                  : "✨ Generate realistic photo"}
          </button>
        </div>
      </div>
    </div>
  );
}
