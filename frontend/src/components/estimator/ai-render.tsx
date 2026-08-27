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
import { Download, RefreshCw, Sparkles } from "lucide-react";
import { useId, useState } from "react";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { estimatorApi } from "@/lib/api/estimator";
import { exportDesignJpeg } from "@/lib/estimator/export";
import type { Design, Mode, PhotoInfo, Product } from "@/lib/estimator/types";

interface AIRenderModalProps {
  workspaceId: string;
  photo: PhotoInfo;
  design: Design;
  productById: Map<string, Product>;
  mode?: Mode;
  onGenerated?: (image: string) => void;
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
  onGenerated,
  onClose,
}: AIRenderModalProps) {
  const [image, setImage] = useState<string | null>(null);
  const [prompt, setPrompt] = useState(mode === "landscape" ? "Make this look real." : "");
  const [showOriginal, setShowOriginal] = useState(false);
  const promptId = useId();
  const promptCountId = useId();
  const render = useMutation({
    mutationFn: async (): Promise<string> => {
      const composited = await exportDesignJpeg(photo, design, productById);
      const result = await estimatorApi.render(workspaceId, {
        image: composited,
        mode,
        prompt: prompt.trim() || null,
      });
      return result.image;
    },
    onSuccess: (rendered) => {
      setImage(rendered);
      setShowOriginal(false);
      onGenerated?.(rendered);
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
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open && !working) onClose();
      }}
    >
      <DialogContent
        className="ai-modal"
        showCloseButton={!working}
        onEscapeKeyDown={(event) => {
          if (working) event.preventDefault();
        }}
        onPointerDownOutside={(event) => {
          if (working) event.preventDefault();
        }}
      >
        <DialogHeader className="ai-modal-head">
          <DialogTitle>
            <Sparkles aria-hidden="true" />
            {isAerial ? "AI aerial render" : "AI realistic render"}
          </DialogTitle>
          <DialogDescription className="ai-modal-note">
            {isAerial
              ? "Turn the active lighting plan into a realistic nighttime aerial without changing its viewpoint or fixture layout."
              : "Turn the drawn design into a realistic nighttime photo while preserving the home and planned light positions."}{" "}
            Each generation uses your workspace’s OpenAI account.
          </DialogDescription>
        </DialogHeader>

        <div className="ai-prompt-field">
          <label htmlFor={promptId}>Describe the finish</label>
          <textarea
            id={promptId}
            value={prompt}
            maxLength={180}
            rows={2}
            placeholder="Make this look real."
            disabled={working}
            aria-describedby={promptCountId}
            onChange={(event) => setPrompt(event.target.value)}
          />
          <small id={promptCountId}>{prompt.length}/180 characters</small>
        </div>

        <div className="ai-stage">
          {image ? (
            // eslint-disable-next-line @next/next/no-img-element -- render is a data URL, not a static asset
            <img
              src={showOriginal ? photo.dataUrl : image}
              alt={
                showOriginal
                  ? `Original ${isAerial ? "aerial" : "property photo"}`
                  : isAerial
                    ? "AI aerial night render"
                    : "AI night render"
              }
            />
          ) : working ? (
            <div className="ai-progress" role="status" aria-live="polite">
              <div className="ai-spinner" aria-hidden="true" />
              <p>{isAerial ? "Rendering the aerial night plan…" : "Rendering the night scene…"}</p>
            </div>
          ) : (
            <div className="ai-placeholder">
              <Sparkles aria-hidden="true" />
              <p>Generate a client-ready concept from the current mockup.</p>
            </div>
          )}
        </div>

        {image ? (
          <div className="ai-compare-controls">
            <div role="group" aria-label="Compare AI render with original">
              <button
                type="button"
                className={!showOriginal ? "active" : ""}
                aria-pressed={!showOriginal}
                onClick={() => setShowOriginal(false)}
              >
                AI render
              </button>
              <button
                type="button"
                className={showOriginal ? "active" : ""}
                aria-pressed={showOriginal}
                onClick={() => setShowOriginal(true)}
              >
                Original
              </button>
            </div>
            <p role="status">
              {onGenerated ? "Added to this session’s client preview." : "Ready to download."}
            </p>
          </div>
        ) : null}

        <p className="ai-disclosure">
          AI renders are visual concepts, not installation guarantees. Review placement, brightness,
          and property details before sharing.
        </p>

        {render.isError ? (
          <p className="ai-error" role="alert">
            {errorMessage(render.error)}
          </p>
        ) : null}

        <div className="ai-actions">
          <button className="est-btn" type="button" onClick={onClose} disabled={working}>
            Close
          </button>
          {image ? (
            <button className="est-btn" type="button" onClick={download}>
              <Download aria-hidden="true" />
              Download
            </button>
          ) : null}
          <button
            className="est-btn primary"
            type="button"
            disabled={working}
            onClick={() => render.mutate()}
          >
            {working ? (
              "Rendering…"
            ) : image ? (
              <>
                <RefreshCw aria-hidden="true" />
                Regenerate
              </>
            ) : (
              <>
                <Sparkles aria-hidden="true" />
                {isAerial ? "Generate client render" : "Generate realistic photo"}
              </>
            )}
          </button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
