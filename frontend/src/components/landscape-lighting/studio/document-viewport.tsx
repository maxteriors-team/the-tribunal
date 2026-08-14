"use client";

import { Maximize2, Minus, Plus } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";

import { cn } from "@/lib/utils";

const MIN_ZOOM = 0.1;
const MAX_ZOOM = 2;
const ZOOM_STEP = 0.1;

function clampZoom(value: number) {
  return Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, value));
}

export function DocumentActionStrip({ children }: { children: ReactNode }) {
  return (
    <div className="ll-document-actions flex min-h-10 flex-wrap items-center justify-end gap-1 border-b border-white/10 bg-[#181918] px-3 py-1.5 text-white">
      {children}
    </div>
  );
}

export function DocumentActionButton({
  children,
  className,
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      type="button"
      className={cn(
        "inline-flex h-8 items-center gap-1.5 rounded border border-white/20 bg-[#202120] px-2.5 text-[11px] font-semibold text-[#eceae5] transition-[color,background-color,border-color] duration-150 hover:border-white/35 hover:bg-[#2a2b2a] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#e2b35f] disabled:cursor-not-allowed disabled:opacity-45 motion-reduce:transition-none",
        className,
      )}
      {...props}
    >
      {children}
    </button>
  );
}

export function DocumentViewport({
  label,
  paperWidth = 1050,
  minimumPaperHeight = 680,
  actions,
  children,
  className,
}: {
  label: string;
  paperWidth?: number;
  minimumPaperHeight?: number;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  const stageRef = useRef<HTMLDivElement>(null);
  const paperRef = useRef<HTMLDivElement>(null);
  const zoomRef = useRef(1);
  const [zoom, setZoom] = useState(1);
  const [paperHeight, setPaperHeight] = useState(minimumPaperHeight);
  const [fitActive, setFitActive] = useState(true);

  const updateZoom = useCallback((nextValue: number, preserveCenter = true) => {
    const nextZoom = clampZoom(nextValue);
    const stage = stageRef.current;
    const currentZoom = zoomRef.current;
    const center = stage
      ? {
          x: (stage.scrollLeft + stage.clientWidth / 2) / currentZoom,
          y: (stage.scrollTop + stage.clientHeight / 2) / currentZoom,
        }
      : null;

    zoomRef.current = nextZoom;
    setZoom(nextZoom);

    if (stage && center && preserveCenter) {
      requestAnimationFrame(() => {
        stage.scrollLeft = center.x * nextZoom - stage.clientWidth / 2;
        stage.scrollTop = center.y * nextZoom - stage.clientHeight / 2;
      });
    }
  }, []);

  const fitDocument = useCallback(() => {
    const stage = stageRef.current;
    const paper = paperRef.current;
    if (!stage || !paper || stage.clientWidth === 0 || stage.clientHeight === 0) return;
    const measuredHeight = Math.max(minimumPaperHeight, paper.scrollHeight, paper.offsetHeight);
    setPaperHeight(measuredHeight);
    const horizontalRoom = Math.max(1, stage.clientWidth - 32);
    const verticalRoom = Math.max(1, stage.clientHeight - 32);
    const fittedZoom = clampZoom(
      Math.min(horizontalRoom / paperWidth, verticalRoom / measuredHeight, 1),
    );
    updateZoom(fittedZoom, false);
    requestAnimationFrame(() => {
      stage.scrollLeft = 0;
      stage.scrollTop = 0;
    });
  }, [minimumPaperHeight, paperWidth, updateZoom]);

  useEffect(() => {
    const stage = stageRef.current;
    const paper = paperRef.current;
    if (!stage || !paper) return;
    const observer = new ResizeObserver(() => {
      const measuredHeight = Math.max(minimumPaperHeight, paper.scrollHeight, paper.offsetHeight);
      setPaperHeight(measuredHeight);
      if (fitActive) fitDocument();
    });
    observer.observe(stage);
    observer.observe(paper);
    const frame = fitActive ? requestAnimationFrame(fitDocument) : null;
    return () => {
      if (frame !== null) cancelAnimationFrame(frame);
      observer.disconnect();
    };
  }, [fitActive, fitDocument, minimumPaperHeight]);

  const setManualZoom = (nextZoom: number) => {
    setFitActive(false);
    updateZoom(nextZoom);
  };

  const percentage = Math.round(zoom * 100);

  return (
    <section
      className={cn("ll-document-viewport", className)}
      aria-label={`${label} document viewport`}
      data-document-zoom={percentage}
    >
      {actions ? <DocumentActionStrip>{actions}</DocumentActionStrip> : null}
      <div className="ll-document-viewport-body">
        <div
          ref={stageRef}
          className="ll-document-stage"
          role="region"
          aria-label={`${label} scrollable document`}
        >
          <div className="ll-document-stage-inner">
            <div
              className="ll-document-scale-frame"
              style={{
                width: paperWidth * zoom,
                height: paperHeight * zoom,
              }}
            >
              <div
                ref={paperRef}
                className="ll-document-paper"
                style={{
                  width: paperWidth,
                  minHeight: minimumPaperHeight,
                  transform: `scale(${zoom})`,
                }}
              >
                {children}
              </div>
            </div>
          </div>
        </div>
        <aside className="ll-document-zoom" aria-label={`${label} zoom controls`}>
          <button
            type="button"
            aria-label="Fit document"
            aria-pressed={fitActive}
            title="Fit document"
            onClick={() => {
              setFitActive(true);
              fitDocument();
            }}
          >
            <Maximize2 aria-hidden="true" />
            <span>Fit</span>
          </button>
          <button
            type="button"
            aria-label="Zoom in"
            disabled={zoom >= MAX_ZOOM}
            onClick={() => setManualZoom(zoom + ZOOM_STEP)}
          >
            <Plus aria-hidden="true" />
          </button>
          <input
            type="range"
            min={MIN_ZOOM * 100}
            max={MAX_ZOOM * 100}
            step={5}
            value={percentage}
            aria-label={`${label} zoom percentage`}
            onChange={(event) => setManualZoom(Number(event.target.value) / 100)}
          />
          <button
            type="button"
            aria-label="Zoom out"
            disabled={zoom <= MIN_ZOOM}
            onClick={() => setManualZoom(zoom - ZOOM_STEP)}
          >
            <Minus aria-hidden="true" />
          </button>
          <output aria-live="polite" aria-atomic="true">
            {percentage}%
          </output>
        </aside>
      </div>
    </section>
  );
}
