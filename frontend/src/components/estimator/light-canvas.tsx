"use client";

/**
 * Light-designer canvas (adapted from the in-house light-estimator CanvasEditor).
 *
 * The rep sets the photo scale, traces glowing runs (C9 roofline, mini lights,
 * garland), and places decor (wreaths, wrapped trees) directly on the house
 * photo. Every stroke renders through the ported `drawScene` glow engine; the
 * geometry it captures is fed back to the host, which prices it server-side.
 *
 * State (design/tool/selection/dusk + history) lives in the host's editor
 * reducer, passed in as `state`/`dispatch`, so the palette and estimate panel
 * stay in sync with what's on the canvas.
 */
import { AlertTriangle, ImagePlus, Moon, Sunrise } from "lucide-react";
import {
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
  type Dispatch,
  type DragEvent as ReactDragEvent,
  type PointerEvent as ReactPointerEvent,
} from "react";

import { fileToResizedDataUrl } from "@/components/sales-wizard/image-resize";
import { indexProducts } from "@/lib/estimator/catalog";
import { designScale, formatFeet } from "@/lib/estimator/design";
import { distance, distToPolyline, polylineLength, snapAngle } from "@/lib/estimator/geometry";
import { fileToPhoto, loadImage } from "@/lib/estimator/photo";
import {
  MAX_DUSK,
  beamAngleAt,
  beamHandlePos,
  beamRotationAt,
  drawScene,
  itemHit,
  planImageHit,
  planImageResizeHandlePos,
  resizeHandlePos,
  rotateHandlePos,
} from "@/lib/estimator/render";
import { isLandscapeStyle } from "@/lib/estimator/types";
import type { Design, PhotoInfo, Point, Product } from "@/lib/estimator/types";

import { EMPTY_DESIGN, nextId, type EditorAction, type EditorState } from "./editor-store";

interface View {
  scale: number;
  ox: number;
  oy: number;
}

type Drag =
  | { mode: "pan"; startX: number; startY: number; ox: number; oy: number }
  | { mode: "vertex"; runId: string; index: number; before: Design }
  | { mode: "run"; runId: string; start: Point; points: Point[]; before: Design }
  | { mode: "item"; itemId: string; offset: Point; before: Design }
  | { mode: "resize"; itemId: string; before: Design }
  | { mode: "beam"; itemId: string; before: Design }
  | { mode: "aim"; itemId: string; before: Design }
  | { mode: "plan-image"; imageId: string; offset: Point; before: Design }
  | { mode: "plan-image-resize"; imageId: string; before: Design }
  | { mode: "highlight"; before: Design }
  | { mode: "cal-a" | "cal-b"; before: Design };

const MAX_PLAN_IMAGES = 12;
const MAX_PLAN_IMAGE_BYTES = 2 * 1024 * 1024;
const ACCEPTED_PLAN_IMAGE_TYPES = new Set([
  "image/png",
  "image/jpeg",
  "image/gif",
  "image/webp",
  "image/avif",
]);

interface LightCanvasProps {
  photo: PhotoInfo;
  products: Product[];
  state: EditorState;
  dispatch: Dispatch<EditorAction>;
  planImageRequestToken?: number;
  onPlanImageRequestHandled?: () => void;
}

export function LightCanvas({
  photo,
  products,
  state,
  dispatch,
  planImageRequestToken = 0,
  onPlanImageRequestHandled,
}: LightCanvasProps) {
  const { design, tool, selection, dusk } = state;

  const containerRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const planImageInputRef = useRef<HTMLInputElement>(null);
  const imgRef = useRef<HTMLImageElement | null>(null);
  const dragRef = useRef<Drag | null>(null);
  const fittedRef = useRef(false);

  const [imgLoaded, setImgLoaded] = useState(false);
  const [planImageElements, setPlanImageElements] = useState<Map<string, HTMLImageElement>>(
    () => new Map(),
  );
  const [planImageError, setPlanImageError] = useState<string | null>(null);
  const [imageDragActive, setImageDragActive] = useState(false);
  const [view, setView] = useState<View>({ scale: 1, ox: 0, oy: 0 });
  const [draft, setDraft] = useState<Point[]>([]);
  const [draftHighlight, setDraftHighlight] = useState<Point[] | null>(null);
  const [calDraft, setCalDraft] = useState<Point | null>(null);
  const [hoverPt, setHoverPt] = useState<Point | null>(null);
  const [spaceDown, setSpaceDown] = useState(false);
  /** Live touch/mouse pointers on the canvas, for multi-touch gestures. */
  const pointersRef = useRef<Map<number, { x: number; y: number }>>(new Map());
  /** A touch press whose action is held until the finger lifts (see below). */
  const tapRef = useRef<{ id: number; x: number; y: number } | null>(null);
  const [panning, setPanning] = useState(false);
  const [pendingCal, setPendingCal] = useState<{ a: Point; b: Point } | null>(null);
  // "Before": the untouched daylight photo, for the side-by-side moment with the
  // customer. A toggle rather than a press-and-hold so it works from the
  // keyboard and on touch.
  const [showBefore, setShowBefore] = useState(false);
  const duskId = useId();
  const canvasHelpId = useId();

  const productById = useMemo(() => indexProducts(products), [products]);
  const { ftPerPx, pxPerFt, calibrated } = designScale(design, photo.width);

  const activeProduct =
    tool.type === "draw" || tool.type === "place"
      ? (productById.get(tool.productId) ?? null)
      : null;

  // ---- photo loading ------------------------------------------------------
  useEffect(() => {
    let cancelled = false;
    setImgLoaded(false);
    fittedRef.current = false;
    void loadImage(photo.dataUrl).then((img) => {
      if (cancelled) return;
      imgRef.current = img;
      setImgLoaded(true);
    });
    return () => {
      cancelled = true;
    };
  }, [photo.dataUrl]);

  const planImageSourceKey = useMemo(
    () =>
      JSON.stringify(
        (design.planImages ?? []).map((image) => ({ id: image.id, dataUrl: image.dataUrl })),
      ),
    [design.planImages],
  );

  useEffect(() => {
    let cancelled = false;
    const images = JSON.parse(planImageSourceKey) as Array<{ id: string; dataUrl: string }>;
    if (images.length === 0) {
      return () => {
        cancelled = true;
      };
    }
    void Promise.all(
      images.map(async (image) => [image.id, await loadImage(image.dataUrl)] as const),
    ).then(
      (loaded) => {
        if (cancelled) return;
        setPlanImageElements(new Map(loaded));
      },
      () => {
        if (!cancelled) setPlanImageError("One plan image could not be loaded.");
      },
    );
    return () => {
      cancelled = true;
    };
  }, [planImageSourceKey]);

  const fitView = useCallback(() => {
    const el = containerRef.current;
    if (!el) return;
    const { width: cw, height: ch } = el.getBoundingClientRect();
    if (cw === 0 || ch === 0) return;
    const scale = Math.min(cw / photo.width, ch / photo.height) * 0.96;
    setView({
      scale,
      ox: (cw - photo.width * scale) / 2,
      oy: (ch - photo.height * scale) / 2,
    });
    fittedRef.current = true;
  }, [photo.width, photo.height]);

  useEffect(() => {
    if (imgLoaded && !fittedRef.current) fitView();
  }, [imgLoaded, fitView]);

  // Reset interaction state when the tool changes.
  useEffect(() => {
    setDraft([]);
    setDraftHighlight(null);
    setCalDraft(null);
    setHoverPt(null);
  }, [tool]);

  // ---- drawing ------------------------------------------------------------
  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    const container = containerRef.current;
    const img = imgRef.current;
    if (!canvas || !container || !img) return;
    const { width: cw, height: ch } = container.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    const pw = Math.max(1, Math.round(cw * dpr));
    const ph = Math.max(1, Math.round(ch * dpr));
    if (canvas.width !== pw) canvas.width = pw;
    if (canvas.height !== ph) canvas.height = ph;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.fillStyle = "#05080f";
    ctx.fillRect(0, 0, pw, ph);
    ctx.setTransform(dpr * view.scale, 0, 0, dpr * view.scale, dpr * view.ox, dpr * view.oy);

    drawScene(ctx, img, showBefore ? EMPTY_DESIGN : design, productById, pxPerFt, {
      viewScale: view.scale,
      selection: showBefore ? null : selection,
      draftRun:
        !showBefore && draft.length > 0 && activeProduct
          ? { points: draft, product: activeProduct }
          : null,
      draftCalPoint: showBefore ? null : calDraft,
      hoverPt: !showBefore && (tool.type === "draw" || tool.type === "calibrate") ? hoverPt : null,
      dusk: showBefore ? 0 : dusk,
      showChrome: !showBefore,
      calibrateTool: tool.type === "calibrate",
      planImageElements,
      draftHighlight: showBefore ? null : draftHighlight,
    });

    if (!showBefore) {
      ctx.save();
      ctx.lineCap = "round";
      ctx.lineJoin = "round";
      ctx.globalAlpha = 1;
      ctx.font = "600 16px sans-serif";
      for (const measurement of design.measurements ?? []) {
        if (measurement.visible === false) continue;
        ctx.strokeStyle = "#22d3ee";
        ctx.lineWidth = 2 / Math.max(view.scale, 0.1);
        ctx.setLineDash([8 / view.scale, 5 / view.scale]);
        ctx.beginPath();
        ctx.moveTo(measurement.a.x, measurement.a.y);
        ctx.lineTo(measurement.b.x, measurement.b.y);
        ctx.stroke();
        if (measurement.label) {
          ctx.fillStyle = "#ffffff";
          ctx.fillText(measurement.label, (measurement.a.x + measurement.b.x) / 2, (measurement.a.y + measurement.b.y) / 2 - 8);
        }
      }
      ctx.setLineDash([]);
      for (const arrow of design.arrows ?? []) {
        const angle = Math.atan2(arrow.b.y - arrow.a.y, arrow.b.x - arrow.a.x);
        ctx.strokeStyle = "#f59e0b";
        ctx.lineWidth = 3 / Math.max(view.scale, 0.1);
        ctx.beginPath();
        ctx.moveTo(arrow.a.x, arrow.a.y);
        ctx.lineTo(arrow.b.x, arrow.b.y);
        ctx.lineTo(arrow.b.x - 14 * Math.cos(angle - Math.PI / 6), arrow.b.y - 14 * Math.sin(angle - Math.PI / 6));
        ctx.moveTo(arrow.b.x, arrow.b.y);
        ctx.lineTo(arrow.b.x - 14 * Math.cos(angle + Math.PI / 6), arrow.b.y - 14 * Math.sin(angle + Math.PI / 6));
        ctx.stroke();
      }
      for (const annotation of design.annotations ?? []) {
        ctx.fillStyle = "#fbbf24";
        ctx.strokeStyle = "#111827";
        ctx.lineWidth = 4 / Math.max(view.scale, 0.1);
        if (annotation.type === "tree") {
          ctx.beginPath();
          ctx.arc(annotation.at.x, annotation.at.y, annotation.sizePx ?? 18, 0, Math.PI * 2);
          ctx.stroke();
          ctx.fill();
        } else if (annotation.end) {
          ctx.beginPath();
          ctx.moveTo(annotation.at.x, annotation.at.y);
          ctx.lineTo(annotation.end.x, annotation.end.y);
          ctx.stroke();
        } else {
          ctx.strokeText(annotation.text || annotation.type.toUpperCase(), annotation.at.x, annotation.at.y);
          ctx.fillText(annotation.text || annotation.type.toUpperCase(), annotation.at.x, annotation.at.y);
        }
      }
      ctx.restore();
    }
  }, [
    view,
    design,
    productById,
    pxPerFt,
    selection,
    draft,
    draftHighlight,
    activeProduct,
    calDraft,
    hoverPt,
    dusk,
    showBefore,
    tool.type,
    planImageElements,
  ]);

  useEffect(() => {
    if (imgLoaded) draw();
  }, [imgLoaded, draw]);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => {
      if (!fittedRef.current) fitView();
      draw();
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [draw, fitView]);

  // ---- coordinate helpers -------------------------------------------------
  const toImage = useCallback(
    (clientX: number, clientY: number): Point => {
      const rect = canvasRef.current!.getBoundingClientRect();
      return {
        x: (clientX - rect.left - view.ox) / view.scale,
        y: (clientY - rect.top - view.oy) / view.scale,
      };
    },
    [view],
  );

  /**
   * Is this image-space point actually on the photo?
   *
   * The canvas is larger than the photo (letterboxing around it while panning
   * and zooming), and a click out there used to create a real, billed fixture
   * that rendered nowhere — the customer is quoted hardware they never see and
   * the crew gets parts for it. Geometry is only allowed on the photo.
   */
  const insidePhoto = useCallback(
    (pt: Point) => pt.x >= 0 && pt.y >= 0 && pt.x <= photo.width && pt.y <= photo.height,
    [photo.width, photo.height],
  );

  /** Keep a dragged point on the photo so an existing item can't be lost. */
  const clampToPhoto = useCallback(
    (pt: Point): Point => ({
      x: Math.min(Math.max(pt.x, 0), photo.width),
      y: Math.min(Math.max(pt.y, 0), photo.height),
    }),
    [photo.width, photo.height],
  );

  const addPlanImage = useCallback(
    async (file: File, requestedAt?: Point) => {
      setPlanImageError(null);
      if ((design.planImages ?? []).length >= MAX_PLAN_IMAGES) {
        setPlanImageError(`A plan can contain up to ${MAX_PLAN_IMAGES} inset images.`);
        return;
      }
      if (!ACCEPTED_PLAN_IMAGE_TYPES.has(file.type)) {
        setPlanImageError("Use a PNG, JPEG, GIF, WebP, or AVIF image.");
        return;
      }
      try {
        const uploaded =
          file.size > MAX_PLAN_IMAGE_BYTES
            ? await (async () => {
                const dataUrl = await fileToResizedDataUrl(file);
                const image = await loadImage(dataUrl);
                return { dataUrl, width: image.naturalWidth, height: image.naturalHeight };
              })()
            : await fileToPhoto(file);
        const maxWidth = photo.width * 0.34;
        const maxHeight = photo.height * 0.34;
        const scale = Math.min(1, maxWidth / uploaded.width, maxHeight / uploaded.height);
        const widthPx = Math.max(24, uploaded.width * scale);
        const heightPx = Math.max(24, uploaded.height * scale);
        const preferred =
          requestedAt && insidePhoto(requestedAt)
            ? requestedAt
            : { x: photo.width / 2, y: photo.height / 2 };
        const at = {
          x: Math.min(Math.max(preferred.x, widthPx / 2), photo.width - widthPx / 2),
          y: Math.min(Math.max(preferred.y, heightPx / 2), photo.height - heightPx / 2),
        };
        dispatch({
          type: "ADD_PLAN_IMAGE",
          image: {
            id: nextId("plan-image"),
            dataUrl: uploaded.dataUrl,
            name: file.name.trim().slice(0, 200) || "Plan image",
            at,
            widthPx,
            heightPx,
          },
        });
      } catch {
        setPlanImageError("That image could not be read or compressed.");
      }
    },
    [design.planImages, dispatch, insidePhoto, photo.height, photo.width],
  );

  const onPlanImageInput = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (file) void addPlanImage(file);
  };

  useEffect(() => {
    if (planImageRequestToken <= 0) return;
    planImageInputRef.current?.click();
    onPlanImageRequestHandled?.();
  }, [onPlanImageRequestHandled, planImageRequestToken]);

  const onPlanImageDrop = (event: ReactDragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setImageDragActive(false);
    const file = event.dataTransfer.files?.[0];
    if (!file) return;
    void addPlanImage(file, toImage(event.clientX, event.clientY));
  };

  const zoomAt = useCallback((clientX: number, clientY: number, factor: number) => {
    setView((v) => {
      const rect = canvasRef.current?.getBoundingClientRect();
      const cx = rect ? clientX - rect.left : 0;
      const cy = rect ? clientY - rect.top : 0;
      const scale = Math.min(40, Math.max(0.02, v.scale * factor));
      const k = scale / v.scale;
      return { scale, ox: cx - (cx - v.ox) * k, oy: cy - (cy - v.oy) * k };
    });
  }, []);

  const zoomCenter = useCallback(
    (factor: number) => {
      const rect = canvasRef.current?.getBoundingClientRect();
      if (!rect) return;
      zoomAt(rect.left + rect.width / 2, rect.top + rect.height / 2, factor);
    },
    [zoomAt],
  );

  // Non-passive wheel listener (React's is passive, so preventDefault fails).
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      if (e.ctrlKey || e.metaKey) {
        const factor = Math.min(1.25, Math.max(0.8, Math.exp(-e.deltaY * 0.01)));
        zoomAt(e.clientX, e.clientY, factor);
      } else {
        setView((v) => ({ ...v, ox: v.ox - e.deltaX, oy: v.oy - e.deltaY }));
      }
    };
    canvas.addEventListener("wheel", onWheel, { passive: false });
    return () => canvas.removeEventListener("wheel", onWheel);
  }, [zoomAt]);

  // ---- draft commit / cancel ----------------------------------------------
  const commitDraft = useCallback(() => {
    if (tool.type !== "draw") return;
    const eps = 3 / view.scale;
    const pts: Point[] = [];
    for (const p of draft) {
      const last = pts[pts.length - 1];
      if (!last || distance(last, p) > eps) pts.push(p);
    }
    if (pts.length >= 2) {
      const wireCircuitNumber =
        design.runs.filter((run) => productById.get(run.productId)?.style === "wire").length + 1;
      dispatch({
        type: "ADD_RUN",
        run: {
          id: nextId("run"),
          productId: tool.productId,
          points: pts,
          ...(activeProduct?.style === "wire"
            ? {
                circuitLabel: `C${wireCircuitNumber}`,
                wireGauge: 12 as const,
                sourceVoltage: 12,
              }
            : {}),
        },
      });
    }
    setDraft([]);
    setHoverPt(null);
  }, [tool, draft, view.scale, dispatch, design.runs, productById, activeProduct]);

  // ---- keyboard -----------------------------------------------------------
  const kbRef = useRef({ draft, calDraft, selection, tool, commitDraft, design, photo });
  kbRef.current = { draft, calDraft, selection, tool, commitDraft, design, photo };

  useEffect(() => {
    const isTyping = () => {
      const el = document.activeElement;
      return (
        el instanceof HTMLInputElement ||
        el instanceof HTMLTextAreaElement ||
        el instanceof HTMLSelectElement
      );
    };
    const onKeyDown = (e: KeyboardEvent) => {
      if (isTyping()) return;
      const k = kbRef.current;
      if (e.key === " ") {
        e.preventDefault();
        setSpaceDown(true);
        return;
      }
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "z") {
        e.preventDefault();
        dispatch({ type: e.shiftKey ? "REDO" : "UNDO" });
        return;
      }
      if (e.key.startsWith("Arrow") && k.selection?.kind === "planImage") {
        const image = (k.design.planImages ?? []).find(
          (candidate) => candidate.id === k.selection?.id,
        );
        if (!image) return;
        e.preventDefault();
        const direction = e.key === "ArrowLeft" || e.key === "ArrowUp" ? -1 : 1;
        const step = e.shiftKey ? 10 : 1;
        if (e.altKey) {
          const aspect = image.widthPx / image.heightPx;
          const maxWidth = Math.min(
            k.photo.width,
            k.photo.height * aspect,
            Math.max(24, Math.min(image.at.x, k.photo.width - image.at.x) * 2),
            Math.max(24, Math.min(image.at.y, k.photo.height - image.at.y) * 2 * aspect),
          );
          const widthPx = Math.min(maxWidth, Math.max(24, image.widthPx + direction * step));
          dispatch({
            type: "UPDATE_PLAN_IMAGE",
            id: image.id,
            patch: { widthPx, heightPx: widthPx / aspect },
          });
        } else {
          const dx = e.key === "ArrowLeft" ? -step : e.key === "ArrowRight" ? step : 0;
          const dy = e.key === "ArrowUp" ? -step : e.key === "ArrowDown" ? step : 0;
          dispatch({
            type: "UPDATE_PLAN_IMAGE",
            id: image.id,
            patch: {
              at: {
                x: Math.min(
                  Math.max(image.at.x + dx, image.widthPx / 2),
                  k.photo.width - image.widthPx / 2,
                ),
                y: Math.min(
                  Math.max(image.at.y + dy, image.heightPx / 2),
                  k.photo.height - image.heightPx / 2,
                ),
              },
            },
          });
        }
        return;
      }
      switch (e.key) {
        case "Escape":
          if (k.draft.length > 0) setDraft([]);
          else if (k.calDraft) setCalDraft(null);
          else if (k.selection) dispatch({ type: "SET_SELECTION", selection: null });
          else dispatch({ type: "SET_TOOL", tool: { type: "select" } });
          setHoverPt(null);
          break;
        case "Enter":
          k.commitDraft();
          break;
        case "Backspace":
        case "Delete":
          e.preventDefault();
          if (k.draft.length > 0) {
            setDraft((d) => d.slice(0, -1));
          } else if (k.selection?.kind === "run") {
            dispatch({ type: "DELETE_RUN", id: k.selection.id });
          } else if (k.selection?.kind === "item") {
            dispatch({ type: "DELETE_ITEM", id: k.selection.id });
          } else if (k.selection?.kind === "planImage") {
            dispatch({ type: "DELETE_PLAN_IMAGE", id: k.selection.id });
          }
          break;
        case "v":
        case "V":
          dispatch({ type: "SET_TOOL", tool: { type: "select" } });
          break;
        case "s":
        case "S":
          dispatch({ type: "SET_TOOL", tool: { type: "calibrate" } });
          break;
        case "+":
        case "=":
          zoomCenter(1.25);
          break;
        case "-":
          zoomCenter(0.8);
          break;
        case "0":
          fitView();
          break;
      }
    };
    const onKeyUp = (e: KeyboardEvent) => {
      if (e.key === " ") setSpaceDown(false);
    };
    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("keyup", onKeyUp);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("keyup", onKeyUp);
    };
  }, [dispatch, fitView, zoomCenter]);

  // ---- touch gestures -----------------------------------------------------
  // A tablet has no middle mouse button and no spacebar, so without this a rep
  // on an iPad can zoom (via the on-screen buttons) but can never pan — leaving
  // them stuck looking at one corner of a zoomed photo. Two fingers pinch to
  // zoom and drag to pan, which is what a touch user already expects; one
  // finger keeps drawing.
  const gestureRef = useRef<{
    dist: number;
    cx: number;
    cy: number;
    ox: number;
    oy: number;
    scale: number;
  } | null>(null);

  const beginGesture = useCallback(() => {
    const pts = [...pointersRef.current.values()];
    if (pts.length !== 2) return;
    const [a, b2] = pts;
    gestureRef.current = {
      dist: Math.max(1, Math.hypot(b2.x - a.x, b2.y - a.y)),
      cx: (a.x + b2.x) / 2,
      cy: (a.y + b2.y) / 2,
      ox: view.ox,
      oy: view.oy,
      scale: view.scale,
    };
  }, [view]);

  const updateGesture = useCallback(() => {
    const g = gestureRef.current;
    const pts = [...pointersRef.current.values()];
    if (!g || pts.length !== 2) return;
    const [a, b2] = pts;
    const dist = Math.max(1, Math.hypot(b2.x - a.x, b2.y - a.y));
    const cx = (a.x + b2.x) / 2;
    const cy = (a.y + b2.y) / 2;
    const rect = canvasRef.current?.getBoundingClientRect();
    if (!rect) return;

    const scale = Math.min(Math.max(g.scale * (dist / g.dist), 0.05), 12);
    const k = scale / g.scale;
    // Zoom about the pinch midpoint, then follow the midpoint as it travels, so
    // the photo stays under the fingers instead of sliding away from them.
    const gx = g.cx - rect.left;
    const gy = g.cy - rect.top;
    setView({
      scale,
      ox: gx - (gx - g.ox) * k + (cx - g.cx),
      oy: gy - (gy - g.oy) * k + (cy - g.cy),
    });
  }, []);

  // ---- pointer events -----------------------------------------------------
  const onPointerDown = (e: ReactPointerEvent<HTMLCanvasElement>) => {
    if (pendingCal) return;
    canvasRef.current?.setPointerCapture(e.pointerId);
    pointersRef.current.set(e.pointerId, { x: e.clientX, y: e.clientY });

    // Second finger down: abandon whatever the first finger started (an
    // accidental dot or a stray vertex) and treat it as a pinch instead.
    if (pointersRef.current.size === 2) {
      const drag = dragRef.current;
      if (drag && drag.mode !== "pan") {
        dispatch({ type: "REVERT_TRANSIENT", design: drag.before });
      }
      dragRef.current = null;
      tapRef.current = null;
      setPanning(false);
      beginGesture();
      return;
    }
    if (pointersRef.current.size > 2) return;

    if (e.button === 1 || spaceDown) {
      dragRef.current = {
        mode: "pan",
        startX: e.clientX,
        startY: e.clientY,
        ox: view.ox,
        oy: view.oy,
      };
      setPanning(true);
      return;
    }
    if (e.button !== 0) return;

    // Touch: creation waits for the finger to lift.
    //
    // A pinch starts as one finger touching a frame or two before the second.
    // If "place" fired on touch-down, every attempt to zoom would leave a stray
    // fixture on the photo — counted, priced, and sent to the crew. Deferring
    // to release lets a second finger cancel it. Mouse and pen keep acting on
    // press, where there is no such ambiguity and the immediacy is the feel.
    if (e.pointerType === "touch" && tool.type !== "select" && tool.type !== "highlight") {
      tapRef.current = { id: e.pointerId, x: e.clientX, y: e.clientY };
      return;
    }

    applyToolPress(e.clientX, e.clientY, e.shiftKey);
  };

  /**
   * Act on a press at a client point: extend a calibration, add a trace point,
   * or place a fixture. Shared by the immediate (mouse) and deferred (touch)
   * paths so both behave identically once the intent is unambiguous.
   */
  const applyToolPress = (clientX: number, clientY: number, shift: boolean) => {
    let p = toImage(clientX, clientY);
    const slack = 8 / view.scale;

    switch (tool.type) {
      case "calibrate": {
        if (!insidePhoto(p)) return;
        const cal = design.calibration;
        if (cal && distance(p, cal.a) < slack * 1.5) {
          dragRef.current = { mode: "cal-a", before: design };
          return;
        }
        if (cal && distance(p, cal.b) < slack * 1.5) {
          dragRef.current = { mode: "cal-b", before: design };
          return;
        }
        if (!calDraft) {
          setCalDraft(p);
        } else {
          if (shift) p = snapAngle(calDraft, p);
          setPendingCal({ a: calDraft, b: p });
          setCalDraft(null);
        }
        return;
      }
      case "draw": {
        if (!insidePhoto(p)) return;
        if (shift && draft.length > 0) {
          p = snapAngle(draft[draft.length - 1], p);
        }
        setDraft((d) => [...d, p]);
        return;
      }
      case "place": {
        if (!activeProduct || !insidePhoto(p)) return;
        const sizePx = Math.max(12, activeProduct.sizeFt * pxPerFt);
        dispatch({
          type: "ADD_ITEM",
          item: { id: nextId("item"), productId: tool.productId, at: p, sizePx },
        });
        return;
      }
      case "highlight": {
        if (!insidePhoto(p)) return;
        setDraftHighlight([p]);
        dragRef.current = { mode: "highlight", before: design };
        return;
      }
      case "select": {
        // 1) handles of current selection
        if (selection?.kind === "run") {
          const run = design.runs.find((r) => r.id === selection.id);
          if (run) {
            const idx = run.points.findIndex((v) => distance(v, p) < slack * 1.4);
            if (idx >= 0) {
              dragRef.current = {
                mode: "vertex",
                runId: run.id,
                index: idx,
                before: design,
              };
              return;
            }
          }
        }
        if (selection?.kind === "planImage") {
          const image = (design.planImages ?? []).find(
            (candidate) => candidate.id === selection.id,
          );
          if (image && distance(planImageResizeHandlePos(image), p) < slack * 1.6) {
            dragRef.current = { mode: "plan-image-resize", imageId: image.id, before: design };
            return;
          }
        }
        if (selection?.kind === "item") {
          const item = design.items.find((i) => i.id === selection.id);
          const itemProduct = item ? productById.get(item.productId) : undefined;
          if (
            item &&
            itemProduct?.style !== "transformer" &&
            distance(resizeHandlePos(item, itemProduct), p) < slack * 1.6
          ) {
            dragRef.current = { mode: "resize", itemId: item.id, before: design };
            return;
          }
          // Throw first, then spread: on a tight beam the two grips crowd each
          // other, and resizing the throw is the gesture a rep reaches for more.
          const spreadGrip = item ? beamHandlePos(item, itemProduct) : null;
          if (item && spreadGrip && distance(spreadGrip, p) < slack * 1.6) {
            dragRef.current = { mode: "beam", itemId: item.id, before: design };
            return;
          }
          // Aim last: it floats a constant gap beyond the throw grip, so it is
          // never the one a rep grabs by accident reaching for the other two.
          const aimGrip = item ? rotateHandlePos(item, itemProduct, view.scale) : null;
          if (item && aimGrip && distance(aimGrip, p) < slack * 1.6) {
            dragRef.current = { mode: "aim", itemId: item.id, before: design };
            return;
          }
        }
        // 2) items (topmost first)
        for (let i = design.items.length - 1; i >= 0; i -= 1) {
          const item = design.items[i];
          if (itemHit(item, p, slack, productById.get(item.productId))) {
            dispatch({
              type: "SET_SELECTION",
              selection: { kind: "item", id: item.id },
            });
            dragRef.current = {
              mode: "item",
              itemId: item.id,
              offset: { x: p.x - item.at.x, y: p.y - item.at.y },
              before: design,
            };
            return;
          }
        }
        // 3) plan images (fixtures remain topmost because their symbols render above images)
        const planImages = design.planImages ?? [];
        for (let i = planImages.length - 1; i >= 0; i -= 1) {
          const image = planImages[i];
          if (planImageHit(image, p, slack)) {
            dispatch({
              type: "SET_SELECTION",
              selection: { kind: "planImage", id: image.id },
            });
            dragRef.current = {
              mode: "plan-image",
              imageId: image.id,
              offset: { x: p.x - image.at.x, y: p.y - image.at.y },
              before: design,
            };
            return;
          }
        }
        // 4) runs
        const hitDist = Math.max(10 / view.scale, pxPerFt * 0.5);
        for (let i = design.runs.length - 1; i >= 0; i -= 1) {
          const run = design.runs[i];
          if (distToPolyline(p, run.points) < hitDist) {
            dispatch({
              type: "SET_SELECTION",
              selection: { kind: "run", id: run.id },
            });
            dragRef.current = {
              mode: "run",
              runId: run.id,
              start: p,
              points: run.points,
              before: design,
            };
            return;
          }
        }
        dispatch({ type: "SET_SELECTION", selection: null });
        return;
      }
    }
  };

  const onPointerMove = (e: ReactPointerEvent<HTMLCanvasElement>) => {
    if (pointersRef.current.has(e.pointerId)) {
      pointersRef.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
    }
    if (gestureRef.current) {
      updateGesture();
      return;
    }
    const drag = dragRef.current;
    let p = toImage(e.clientX, e.clientY);

    if (!drag) {
      if (tool.type === "draw" && draft.length > 0 && e.shiftKey) {
        p = snapAngle(draft[draft.length - 1], p);
      } else if (tool.type === "calibrate" && calDraft && e.shiftKey) {
        p = snapAngle(calDraft, p);
      }
      if (tool.type === "draw" || tool.type === "calibrate") setHoverPt(p);
      return;
    }

    switch (drag.mode) {
      case "pan": {
        setView({
          scale: view.scale,
          ox: drag.ox + (e.clientX - drag.startX),
          oy: drag.oy + (e.clientY - drag.startY),
        });
        return;
      }
      case "highlight": {
        if (!insidePhoto(p)) return;
        setDraftHighlight((points) => {
          if (!points?.length) return [p];
          const previous = points[points.length - 1];
          return distance(previous, p) >= 2 / Math.max(view.scale, 0.1)
            ? [...points, p]
            : points;
        });
        return;
      }
      case "vertex": {
        const run = design.runs.find((r) => r.id === drag.runId);
        if (!run) return;
        const at = clampToPhoto(p);
        const points = run.points.map((v, i) => (i === drag.index ? at : v));
        dispatch({
          type: "UPDATE_RUN",
          id: drag.runId,
          patch: { points },
          transient: true,
        });
        return;
      }
      case "run": {
        const xs = drag.points.map((v) => v.x);
        const ys = drag.points.map((v) => v.y);
        const dx = Math.min(
          Math.max(p.x - drag.start.x, -Math.min(...xs)),
          photo.width - Math.max(...xs),
        );
        const dy = Math.min(
          Math.max(p.y - drag.start.y, -Math.min(...ys)),
          photo.height - Math.max(...ys),
        );
        const points = drag.points.map((v) => ({ x: v.x + dx, y: v.y + dy }));
        dispatch({
          type: "UPDATE_RUN",
          id: drag.runId,
          patch: { points },
          transient: true,
        });
        return;
      }
      case "item": {
        dispatch({
          type: "UPDATE_ITEM",
          id: drag.itemId,
          patch: {
            at: clampToPhoto({
              x: p.x - drag.offset.x,
              y: p.y - drag.offset.y,
            }),
          },
          transient: true,
        });
        return;
      }
      case "plan-image": {
        const image = (design.planImages ?? []).find((candidate) => candidate.id === drag.imageId);
        if (!image) return;
        dispatch({
          type: "UPDATE_PLAN_IMAGE",
          id: image.id,
          patch: {
            at: {
              x: Math.min(
                Math.max(p.x - drag.offset.x, image.widthPx / 2),
                photo.width - image.widthPx / 2,
              ),
              y: Math.min(
                Math.max(p.y - drag.offset.y, image.heightPx / 2),
                photo.height - image.heightPx / 2,
              ),
            },
          },
          transient: true,
        });
        return;
      }
      case "plan-image-resize": {
        const image = (design.planImages ?? []).find((candidate) => candidate.id === drag.imageId);
        if (!image) return;
        const left = image.at.x - image.widthPx / 2;
        const top = image.at.y - image.heightPx / 2;
        const aspect = image.widthPx / image.heightPx;
        let widthPx = Math.max(24, p.x - left);
        let heightPx = widthPx / aspect;
        if (top + heightPx > photo.height) {
          heightPx = Math.max(24, photo.height - top);
          widthPx = heightPx * aspect;
        }
        widthPx = Math.min(widthPx, photo.width - left);
        heightPx = widthPx / aspect;
        dispatch({
          type: "UPDATE_PLAN_IMAGE",
          id: image.id,
          patch: {
            at: { x: left + widthPx / 2, y: top + heightPx / 2 },
            widthPx,
            heightPx,
          },
          transient: true,
        });
        return;
      }
      case "resize": {
        const item = design.items.find((i) => i.id === drag.itemId);
        if (!item) return;
        const resized = productById.get(item.productId);
        // A landscape beam is sized by its throw (the grip sits at the far end),
        // decor by its diameter (the grip sits on its bounding corner).
        const sizePx =
          resized && isLandscapeStyle(resized.style)
            ? Math.max(10, distance(item.at, p))
            : Math.max(10, distance(item.at, p) * 2 * 0.82);
        dispatch({
          type: "UPDATE_ITEM",
          id: drag.itemId,
          patch: { sizePx },
          transient: true,
        });
        return;
      }
      case "beam": {
        const item = design.items.find((i) => i.id === drag.itemId);
        if (!item) return;
        dispatch({
          type: "UPDATE_ITEM",
          id: drag.itemId,
          patch: { beamAngleDeg: beamAngleAt(item, p) },
          transient: true,
        });
        return;
      }
      case "aim": {
        const item = design.items.find((i) => i.id === drag.itemId);
        if (!item) return;
        dispatch({
          type: "UPDATE_ITEM",
          id: drag.itemId,
          patch: {
            beamRotationDeg: beamRotationAt(item, p, productById.get(item.productId)),
          },
          transient: true,
        });
        return;
      }
      case "cal-a":
      case "cal-b": {
        const cal = design.calibration;
        if (!cal) return;
        const at = clampToPhoto(p);
        const calibration = drag.mode === "cal-a" ? { ...cal, a: at } : { ...cal, b: at };
        dispatch({ type: "SET_CALIBRATION", calibration, transient: true });
        return;
      }
    }
  };

  const onPointerUp = (e: ReactPointerEvent<HTMLCanvasElement>) => {
    pointersRef.current.delete(e.pointerId);

    const tap = tapRef.current;
    if (tap && tap.id === e.pointerId) {
      tapRef.current = null;
      // A finger that slid was a scroll/gesture attempt, not a placement.
      const moved = Math.hypot(e.clientX - tap.x, e.clientY - tap.y);
      if (!gestureRef.current && moved < 12) {
        applyToolPress(e.clientX, e.clientY, e.shiftKey);
      }
    }

    if (gestureRef.current) {
      // Lifting one finger of a pinch ends the gesture rather than handing the
      // remaining finger a half-finished drag.
      if (pointersRef.current.size < 2) gestureRef.current = null;
      else beginGesture();
      return;
    }
    const drag = dragRef.current;
    dragRef.current = null;
    setPanning(false);
    if (drag?.mode === "highlight") {
      const points = draftHighlight ?? [];
      setDraftHighlight(null);
      if (points.length > 1) {
        dispatch({
          type: "ADD_HIGHLIGHT",
          highlight: {
            id: nextId("highlight"),
            points,
            color: "rgba(255, 226, 74, 0.55)",
            widthPx: 34,
          },
        });
      }
      return;
    }
    if (drag && drag.mode !== "pan") {
      dispatch({ type: "COMMIT_HISTORY", before: drag.before });
    }
  };

  const onDoubleClick = () => commitDraft();
  const onContextMenu = (e: React.MouseEvent) => {
    e.preventDefault();
    if (draft.length > 0) commitDraft();
  };

  // ---- hint text ----------------------------------------------------------
  let hint = "";
  if (tool.type === "calibrate") {
    hint = calDraft
      ? "Click the other end of your reference object · Shift = straight line"
      : design.calibration
        ? "Drag the cyan handles to adjust — or click two new points to re-measure"
        : "Click both ends of something with a known size (garage door = 16 ft)";
  } else if (tool.type === "draw") {
    const liveFt =
      draft.length > 0 ? polylineLength(hoverPt ? [...draft, hoverPt] : draft) * ftPerPx : 0;
    hint =
      draft.length > 0
        ? `${formatFeet(liveFt)} — Enter / double-click to finish · Backspace undoes a point · Esc cancels`
        : "Click along the roofline to add points · Shift snaps angles";
  } else if (tool.type === "place") {
    hint = `Click to place ${activeProduct?.name ?? "item"} · then switch to Select (V) to move or resize`;
  } else if (tool.type === "highlight") {
    hint = "Drag across the plan to highlight · choose Highlight again or Select when finished";
  } else if (selection?.kind === "planImage") {
    hint = "Drag or arrow keys move · corner handle or Alt + arrows resize · Delete removes";
  } else if (selection) {
    hint = "Drag to move · drag handles to adjust · Delete removes";
  }

  const cursor =
    spaceDown || panning
      ? panning
        ? "grabbing"
        : "grab"
      : tool.type === "select"
        ? "default"
        : "crosshair";

  const duskPercent = Math.round(dusk * 100);

  return (
    <div
      ref={containerRef}
      className={`lc-wrap${imageDragActive ? " lc-image-drag-active" : ""}`}
      onDragEnter={(event) => {
        if (event.dataTransfer.types.includes("Files")) {
          event.preventDefault();
          setImageDragActive(true);
        }
      }}
      onDragOver={(event) => {
        if (event.dataTransfer.types.includes("Files")) {
          event.preventDefault();
          event.dataTransfer.dropEffect = "copy";
          setImageDragActive(true);
        }
      }}
      onDragLeave={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
          setImageDragActive(false);
        }
      }}
      onDrop={onPlanImageDrop}
    >
      <p id={canvasHelpId} className="sr-only">
        Interactive lighting design canvas. Choose a fixture or tool from the left rail, then use
        the pointer on the property photo. Press V for Select, S for Set scale, Delete to remove a
        selected fixture, plus or minus to zoom, and 0 to fit. Drop an image file onto the plan, or
        use Add plan image, to place a movable reference inset.
      </p>
      <input
        ref={planImageInputRef}
        type="file"
        accept="image/png,image/jpeg,image/gif,image/webp,image/avif"
        hidden
        onChange={onPlanImageInput}
      />
      <canvas
        ref={canvasRef}
        className="lc-canvas"
        tabIndex={0}
        aria-label="Property photo lighting design canvas"
        aria-describedby={canvasHelpId}
        style={{ cursor }}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
        onDoubleClick={onDoubleClick}
        onContextMenu={onContextMenu}
      />

      <div className="lc-overlay top-left lc-plan-actions">
        <button
          type="button"
          className={`lc-chip ${calibrated ? "lc-chip-ok" : "lc-chip-warn"}`}
          onClick={() => dispatch({ type: "SET_TOOL", tool: { type: "calibrate" } })}
          title="Set the photo scale from a known measurement"
        >
          {!calibrated ? <AlertTriangle className="lc-chip-glyph" aria-hidden="true" /> : null}
          {calibrated && design.calibration
            ? `Scale set: ${design.calibration.feet} ft reference`
            : "Not to scale. Select to set scale."}
        </button>
        <button
          type="button"
          className="lc-chip"
          disabled={(design.planImages ?? []).length >= MAX_PLAN_IMAGES}
          onClick={() => planImageInputRef.current?.click()}
          title="Place a movable detail or reference image on this plan"
        >
          <ImagePlus className="lc-chip-glyph" aria-hidden="true" />
          Add plan image
        </button>
      </div>

      {imageDragActive ? (
        <div className="lc-image-drop-target" aria-hidden="true">
          <ImagePlus />
          <strong>Drop image onto plan</strong>
          <span>It will stay movable and resizable.</span>
        </div>
      ) : null}

      {planImageError ? (
        <div className="lc-overlay lc-plan-image-error" role="alert">
          {planImageError}
        </div>
      ) : null}

      <div className="lc-overlay top-right">
        <button
          type="button"
          className={`lc-chip ${showBefore ? "lc-chip-on" : ""}`}
          aria-pressed={showBefore}
          onClick={() => setShowBefore((v) => !v)}
          title="Show the untouched daylight photo"
        >
          <Sunrise className="lc-chip-glyph" aria-hidden="true" />
          Before
        </button>
        <div className="lc-dusk">
          <label className="lc-dusk-label" htmlFor={duskId}>
            <Moon className="lc-chip-glyph" aria-hidden="true" />
            Dusk
          </label>
          <input
            id={duskId}
            className="lc-dusk-slider"
            type="range"
            min={0}
            max={Math.round(MAX_DUSK * 100)}
            step={1}
            value={duskPercent}
            disabled={showBefore}
            onChange={(e) => dispatch({ type: "SET_DUSK", dusk: Number(e.target.value) / 100 })}
          />
          <output className="lc-dusk-value" htmlFor={duskId}>
            {duskPercent}%
          </output>
        </div>
      </div>

      <div className="lc-overlay bottom-right">
        <button
          type="button"
          className="lc-zoom-btn"
          onClick={() => zoomCenter(0.8)}
          title="Zoom out (-)"
        >
          −
        </button>
        <span className="lc-zoom-label">{Math.round(view.scale * 100)}%</span>
        <button
          type="button"
          className="lc-zoom-btn"
          onClick={() => zoomCenter(1.25)}
          title="Zoom in (+)"
        >
          +
        </button>
        <button
          type="button"
          className="lc-zoom-btn lc-zoom-fit"
          onClick={fitView}
          title="Fit to screen (0)"
        >
          Fit
        </button>
      </div>

      {hint ? (
        <div className="lc-overlay bottom-center">
          <div className="lc-hint-bar">{hint}</div>
        </div>
      ) : null}

      {pendingCal ? (
        <FeetModal
          onCancel={() => setPendingCal(null)}
          onApply={(feet) => {
            dispatch({
              type: "SET_CALIBRATION",
              calibration: { a: pendingCal.a, b: pendingCal.b, feet },
            });
            setPendingCal(null);
            dispatch({ type: "SET_TOOL", tool: { type: "select" } });
          }}
        />
      ) : null}
    </div>
  );
}

function FeetModal({
  onApply,
  onCancel,
}: {
  onApply: (feet: number) => void;
  onCancel: () => void;
}) {
  const [value, setValue] = useState("16");
  const feet = parseFloat(value);
  const valid = Number.isFinite(feet) && feet > 0;

  return (
    <div className="lc-modal-backdrop">
      <button
        type="button"
        className="lc-modal-scrim"
        aria-label="Cancel setting the scale"
        onClick={onCancel}
      />
      <div className="lc-modal" role="dialog" aria-modal="true" aria-label="Set photo scale">
        <h3>How long is that line in real life?</h3>
        <p className="lc-modal-sub">
          Measure off something you know — a garage door, front door, or siding panel.
        </p>
        <div className="lc-feet-row">
          <input
            // eslint-disable-next-line jsx-a11y/no-autofocus -- focus the sole input when the scale modal opens
            autoFocus
            type="number"
            min="0.5"
            step="0.5"
            value={value}
            aria-label="Reference length in feet"
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && valid) onApply(feet);
              if (e.key === "Escape") onCancel();
            }}
          />
          <span className="lc-feet-unit">feet</span>
        </div>
        <div className="lc-quick-row">
          <button type="button" onClick={() => setValue("16")}>
            2-car garage · 16
          </button>
          <button type="button" onClick={() => setValue("9")}>
            1-car garage · 9
          </button>
          <button type="button" onClick={() => setValue("3")}>
            Front door · 3
          </button>
        </div>
        <div className="lc-modal-actions">
          <button type="button" className="est-btn" onClick={onCancel}>
            Cancel
          </button>
          <button
            type="button"
            className="est-btn primary"
            disabled={!valid}
            onClick={() => valid && onApply(feet)}
          >
            Set scale
          </button>
        </div>
      </div>
    </div>
  );
}
