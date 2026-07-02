"use client";

/**
 * Screen 3 — Night Mode: canvas light-painting over a photo of the home.
 * Direct port of the uploaded wizard's night-mode engine (pointer add/drag,
 * dusk darkening, additive light rendering, hold-to-compare). "Save to
 * Proposal" composites the canvas to a JPEG data-URL stored in the wizard's
 * `night_preview`, which the presentation and public proposal render.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import type { NightLight, UseSalesWizardReturn } from "./use-sales-wizard";

const NIGHT_TYPES = [
  { key: "uplight", label: "Uplight" },
  { key: "spot", label: "Spot" },
  { key: "path", label: "Path" },
  { key: "wash", label: "Wash" },
  { key: "bistro", label: "Bistro" },
] as const;

const DEFAULTS = { glow: 160, intensity: 0.6, spread: 90, warmth: 0.18 };

function warmthColor(w: number): [number, number, number] {
  const warm = [255, 176, 94];
  const cool = [208, 224, 255];
  return [
    Math.round(warm[0] + (cool[0] - warm[0]) * w),
    Math.round(warm[1] + (cool[1] - warm[1]) * w),
    Math.round(warm[2] + (cool[2] - warm[2]) * w),
  ];
}

function rgba(c: [number, number, number], a: number): string {
  return `rgba(${c[0]},${c[1]},${c[2]},${a})`;
}

function drawImageCover(
  ctx: CanvasRenderingContext2D,
  img: HTMLImageElement,
  W: number,
  H: number,
) {
  const s = Math.max(W / img.width, H / img.height);
  const dw = img.width * s;
  const dh = img.height * s;
  ctx.drawImage(img, (W - dw) / 2, (H - dh) / 2, dw, dh);
}

const clamp01 = (v: number) => Math.min(1, Math.max(0, v));

/** Quadratic bezier interpolation along one axis. */
function bez(t: number, p0: number, pc: number, p1: number): number {
  const u = 1 - t;
  return u * u * p0 + 2 * u * t * pc + t * t * p1;
}

/** Endpoints + sagging control point for a bistro string, in canvas px. */
function bistroGeometry(l: NightLight, W: number, H: number) {
  const x1 = l.nx * W;
  const y1 = l.ny * H;
  const x2 = (l.nx2 ?? l.nx) * W;
  const y2 = (l.ny2 ?? l.ny) * H;
  const sc = H / 600;
  const len = Math.hypot(x2 - x1, y2 - y1);
  // Spread doubles as sag depth for strings (slider stays meaningful).
  const sag = (l.spread / 90) * Math.max(8, Math.min(130 * sc, len * 0.3));
  return {
    x1,
    y1,
    x2,
    y2,
    mx: (x1 + x2) / 2,
    my: (y1 + y2) / 2 + sag,
    len,
    sc,
  };
}

/** Sagging strand of glowing bulbs between the two anchors. */
function drawBistro(
  ctx: CanvasRenderingContext2D,
  l: NightLight,
  W: number,
  H: number,
) {
  const { x1, y1, x2, y2, mx, my, len, sc } = bistroGeometry(l, W, H);
  if (len < 2) return;
  const col = warmthColor(l.warmth);
  const a = l.intensity;
  // Wire — drawn additively, so keep it a faint warm glowline.
  ctx.strokeStyle = rgba(col, 0.16 * a);
  ctx.lineWidth = Math.max(1, 1.2 * sc);
  ctx.beginPath();
  ctx.moveTo(x1, y1);
  ctx.quadraticCurveTo(mx, my, x2, y2);
  ctx.stroke();
  // Bulbs every ~26px along the curve, hanging just under the wire.
  const count = Math.max(3, Math.round(len / (26 * sc)));
  const drop = 5 * sc;
  const r = Math.max(4, l.glow * 0.16 * sc);
  for (let i = 0; i <= count; i++) {
    const t = i / count;
    const bx = bez(t, x1, mx, x2);
    const by = bez(t, y1, my, y2) + drop;
    const g = ctx.createRadialGradient(bx, by, 0, bx, by, r);
    g.addColorStop(0, rgba(col, 0.8 * a));
    g.addColorStop(0.35, rgba(col, 0.28 * a));
    g.addColorStop(1, rgba(col, 0));
    ctx.fillStyle = g;
    ctx.beginPath();
    ctx.arc(bx, by, r, 0, 7);
    ctx.fill();
    // Bright filament core.
    ctx.fillStyle = rgba([255, 244, 214], Math.min(1, 0.9 * a + 0.1));
    ctx.beginPath();
    ctx.arc(bx, by, Math.max(1.2, 1.8 * sc), 0, 7);
    ctx.fill();
  }
}

function drawLight(
  ctx: CanvasRenderingContext2D,
  l: NightLight,
  W: number,
  H: number,
) {
  if (l.type === "bistro") {
    drawBistro(ctx, l, W, H);
    return;
  }
  const x = l.nx * W;
  const y = l.ny * H;
  const sc = H / 600;
  const col = warmthColor(l.warmth);
  const a = l.intensity;
  if (l.type === "path" || l.type === "wash") {
    const r = (l.type === "wash" ? l.glow * 1.7 : l.glow) * sc;
    const g = ctx.createRadialGradient(x, y, 0, x, y, Math.max(2, r));
    g.addColorStop(0, rgba(col, 0.6 * a));
    g.addColorStop(0.4, rgba(col, 0.26 * a));
    g.addColorStop(1, rgba(col, 0));
    ctx.fillStyle = g;
    ctx.beginPath();
    if (l.type === "path") {
      ctx.save();
      ctx.translate(x, y);
      ctx.scale(1, 0.5);
      ctx.arc(0, 0, Math.max(2, r), 0, 7);
      ctx.restore();
    } else {
      ctx.arc(x, y, Math.max(2, r), 0, 7);
    }
    ctx.fill();
  } else {
    const reach = l.glow * sc * 1.45;
    const topW = (l.type === "spot" ? l.spread * 0.42 : l.spread) * sc;
    const baseW = Math.max(5, topW * 0.18);
    const g = ctx.createLinearGradient(0, 0, 0, -reach);
    g.addColorStop(0, rgba(col, 0.5 * a));
    g.addColorStop(1, rgba(col, 0));
    ctx.save();
    ctx.translate(x, y);
    ctx.fillStyle = g;
    ctx.beginPath();
    ctx.moveTo(-baseW / 2, 0);
    ctx.lineTo(baseW / 2, 0);
    ctx.lineTo(topW / 2, -reach);
    ctx.lineTo(-topW / 2, -reach);
    ctx.closePath();
    ctx.fill();
    ctx.restore();
    const r = l.spread * sc * 0.6;
    const g2 = ctx.createRadialGradient(x, y, 0, x, y, Math.max(2, r));
    g2.addColorStop(0, rgba(col, 0.5 * a));
    g2.addColorStop(1, rgba(col, 0));
    ctx.fillStyle = g2;
    ctx.beginPath();
    ctx.arc(x, y, Math.max(2, r), 0, 7);
    ctx.fill();
  }
}

type DragPart = "p1" | "p2" | "body";

interface NightPreviewScreenProps {
  wizard: UseSalesWizardReturn;
  onClose: () => void;
}

export function NightPreviewScreen({ wizard, onClose }: NightPreviewScreenProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const stageRef = useRef<HTMLDivElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const imgRef = useRef<HTMLImageElement | null>(null);
  const draggingRef = useRef<{
    part: DragPart;
    lastNx: number;
    lastNy: number;
  } | null>(null);

  const [lights, setLights] = useState<NightLight[]>(wizard.night.lights);
  const [selected, setSelected] = useState(-1);
  const [hasImage, setHasImage] = useState(false);
  const [before, setBefore] = useState(false);
  const [dusk, setDusk] = useState(wizard.night.dusk);
  const [type, setType] = useState<string>("uplight");
  const [sliders, setSliders] = useState({ ...DEFAULTS });

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return;
    const W = canvas.width;
    const H = canvas.height;
    ctx.clearRect(0, 0, W, H);
    ctx.fillStyle = "#05060c";
    ctx.fillRect(0, 0, W, H);
    const img = imgRef.current;
    if (!img) return;
    drawImageCover(ctx, img, W, H);
    if (before) return;
    ctx.save();
    ctx.fillStyle = rgba([6, 10, 30], dusk);
    ctx.fillRect(0, 0, W, H);
    ctx.restore();
    ctx.save();
    ctx.globalCompositeOperation = "lighter";
    for (const light of lights) drawLight(ctx, light, W, H);
    ctx.restore();
    if (selected >= 0 && lights[selected]) {
      const l = lights[selected];
      ctx.save();
      ctx.strokeStyle = "rgba(212,175,90,0.9)";
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.arc(l.nx * W, l.ny * H, 12 * (H / 600), 0, 7);
      ctx.stroke();
      if (l.type === "bistro") {
        ctx.beginPath();
        ctx.arc((l.nx2 ?? l.nx) * W, (l.ny2 ?? l.ny) * H, 12 * (H / 600), 0, 7);
        ctx.stroke();
      }
      ctx.restore();
    }
  }, [lights, selected, before, dusk]);

  const setupCanvas = useCallback(() => {
    const canvas = canvasRef.current;
    const stage = stageRef.current;
    if (!canvas || !stage) return;
    const w = Math.max(280, stage.clientWidth);
    const h = Math.max(280, stage.clientHeight);
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = Math.round(w * dpr);
    canvas.height = Math.round(h * dpr);
    canvas.style.width = `${w}px`;
    canvas.style.height = `${h}px`;
  }, []);

  useEffect(() => {
    setupCanvas();
    draw();
    const onResize = () => {
      setupCanvas();
      draw();
    };
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [setupCanvas, draw]);

  useEffect(() => {
    draw();
  }, [draw, hasImage]);

  const point = (ev: React.PointerEvent): { nx: number; ny: number } => {
    const canvas = canvasRef.current!;
    const r = canvas.getBoundingClientRect();
    const px = (ev.clientX - r.left) * (canvas.width / r.width);
    const py = (ev.clientY - r.top) * (canvas.height / r.height);
    return { nx: px / canvas.width, ny: py / canvas.height };
  };

  const hitTest = (
    p: { nx: number; ny: number },
  ): { i: number; part: DragPart } | null => {
    const canvas = canvasRef.current!;
    const W = canvas.width;
    const H = canvas.height;
    const rad = 26 * (window.devicePixelRatio || 1);
    const px = p.nx * W;
    const py = p.ny * H;
    for (let i = lights.length - 1; i >= 0; i--) {
      const l = lights[i];
      if (Math.hypot(l.nx * W - px, l.ny * H - py) <= rad) {
        return { i, part: "p1" };
      }
      if (l.type === "bistro") {
        const x2 = (l.nx2 ?? l.nx) * W;
        const y2 = (l.ny2 ?? l.ny) * H;
        if (Math.hypot(x2 - px, y2 - py) <= rad) return { i, part: "p2" };
        // Body: sample points along the sagging curve.
        const g = bistroGeometry(l, W, H);
        for (let s = 1; s < 12; s++) {
          const t = s / 12;
          const bx = bez(t, g.x1, g.mx, g.x2);
          const by = bez(t, g.y1, g.my, g.y2);
          if (Math.hypot(bx - px, by - py) <= rad) return { i, part: "body" };
        }
      }
    }
    return null;
  };

  const onPointerDown = (ev: React.PointerEvent) => {
    if (!imgRef.current) {
      toast("Add a photo first");
      return;
    }
    ev.preventDefault();
    const p = point(ev);
    const hit = hitTest(p);
    if (hit) {
      setSelected(hit.i);
      const l = lights[hit.i];
      setSliders({
        glow: l.glow,
        intensity: l.intensity,
        spread: l.spread,
        warmth: l.warmth,
      });
      setType(l.type);
      draggingRef.current = { part: hit.part, lastNx: p.nx, lastNy: p.ny };
    } else if (type === "bistro") {
      // Press starts the strand; dragging stretches its far end.
      setLights((prev) => [
        ...prev,
        { nx: p.nx, ny: p.ny, nx2: p.nx, ny2: p.ny, type, ...sliders },
      ]);
      setSelected(lights.length);
      draggingRef.current = { part: "p2", lastNx: p.nx, lastNy: p.ny };
    } else {
      setLights((prev) => [...prev, { nx: p.nx, ny: p.ny, type, ...sliders }]);
      setSelected(lights.length);
      draggingRef.current = { part: "p1", lastNx: p.nx, lastNy: p.ny };
    }
  };

  const onPointerMove = (ev: React.PointerEvent) => {
    const drag = draggingRef.current;
    if (!drag || selected < 0) return;
    ev.preventDefault();
    const p = point(ev);
    const nx = clamp01(p.nx);
    const ny = clamp01(p.ny);
    setLights((prev) =>
      prev.map((l, i) => {
        if (i !== selected) return l;
        if (drag.part === "p2") return { ...l, nx2: nx, ny2: ny };
        if (drag.part === "body") {
          const dnx = p.nx - drag.lastNx;
          const dny = p.ny - drag.lastNy;
          return {
            ...l,
            nx: clamp01(l.nx + dnx),
            ny: clamp01(l.ny + dny),
            nx2: clamp01((l.nx2 ?? l.nx) + dnx),
            ny2: clamp01((l.ny2 ?? l.ny) + dny),
          };
        }
        return { ...l, nx, ny };
      }),
    );
    if (drag.part === "body") {
      drag.lastNx = p.nx;
      drag.lastNy = p.ny;
    }
  };

  const onPointerUp = () => {
    draggingRef.current = null;
    // A bare tap in bistro mode leaves a zero-length strand — give it a
    // sensible default span so the tap still hangs visible lights.
    setLights((prev) =>
      prev.map((l, i) => {
        if (i !== selected || l.type !== "bistro") return l;
        const len = Math.hypot(
          (l.nx2 ?? l.nx) - l.nx,
          (l.ny2 ?? l.ny) - l.ny,
        );
        if (len >= 0.02) return l;
        return {
          ...l,
          nx: clamp01(l.nx - 0.12),
          nx2: clamp01(l.nx + 0.12),
          ny2: l.ny,
        };
      }),
    );
  };

  const loadFile = (input: HTMLInputElement) => {
    const file = input.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (e) => {
      const img = new Image();
      img.onload = () => {
        imgRef.current = img;
        setHasImage(true);
        setupCanvas();
        draw();
        toast.success("Photo loaded — tap to add lights");
      };
      img.onerror = () => toast.error("Could not read that image");
      img.src = String(e.target?.result ?? "");
    };
    reader.onerror = () => toast.error("Could not read that file");
    reader.readAsDataURL(file);
  };

  const applySliders = (patch: Partial<typeof DEFAULTS>) => {
    const next = { ...sliders, ...patch };
    setSliders(next);
    if (selected >= 0) {
      setLights((prev) =>
        prev.map((l, i) => (i === selected ? { ...l, ...next } : l)),
      );
    }
  };

  const applyType = (key: string) => {
    setType(key);
    if (selected >= 0) {
      setLights((prev) =>
        prev.map((l, i) => {
          if (i !== selected) return l;
          // Converting a point light into a string needs a second anchor.
          if (key === "bistro" && l.nx2 == null) {
            return {
              ...l,
              type: key,
              nx: clamp01(l.nx - 0.12),
              nx2: clamp01(l.nx + 0.12),
              ny2: l.ny,
            };
          }
          return { ...l, type: key };
        }),
      );
    }
  };

  const compositeDataURL = (): string | null => {
    const canvas = canvasRef.current;
    if (!canvas || !imgRef.current) return null;
    const wasSelected = selected;
    // Draw once without the selection ring for a clean composite.
    setSelected(-1);
    const ctx = canvas.getContext("2d");
    if (!ctx) return null;
    // Synchronous redraw with selection cleared.
    const W = canvas.width;
    const H = canvas.height;
    ctx.clearRect(0, 0, W, H);
    ctx.fillStyle = "#05060c";
    ctx.fillRect(0, 0, W, H);
    drawImageCover(ctx, imgRef.current, W, H);
    ctx.save();
    ctx.fillStyle = rgba([6, 10, 30], dusk);
    ctx.fillRect(0, 0, W, H);
    ctx.restore();
    ctx.save();
    ctx.globalCompositeOperation = "lighter";
    for (const light of lights) drawLight(ctx, light, W, H);
    ctx.restore();
    let url: string | null = null;
    try {
      url = canvas.toDataURL("image/jpeg", 0.85);
    } catch {
      url = null;
    }
    setSelected(wasSelected);
    return url;
  };

  const saveToProposal = () => {
    if (!imgRef.current) {
      toast("Add a photo first");
      return;
    }
    const url = compositeDataURL();
    if (url) {
      wizard.setNight({ image: url, lights, dusk });
      toast.success("Night preview saved to proposal");
    } else {
      toast.error("Could not save image");
    }
  };

  const exportImage = () => {
    if (!imgRef.current) {
      toast("Add a photo first");
      return;
    }
    const url = compositeDataURL();
    if (!url) {
      toast.error("Export failed");
      return;
    }
    const a = document.createElement("a");
    a.href = url;
    a.download = "night-preview.jpg";
    document.body.appendChild(a);
    a.click();
    a.remove();
  };

  const clearLights = () => {
    if (!lights.length) return;
    setLights([]);
    setSelected(-1);
  };

  const undo = () => {
    if (!lights.length) return;
    setLights((prev) => prev.slice(0, -1));
    setSelected(lights.length - 2);
  };

  const warmthLabel =
    sliders.warmth < 0.33 ? "Warm" : sliders.warmth < 0.66 ? "Neutral" : "Cool";
  const activeType =
    selected >= 0 && lights[selected] ? lights[selected].type : type;

  return (
    <div className="screen active" id="screen-night">
      <div className="night-nav">
        <div className="night-nav-brand">
          Night Mode &#8212; Lit-at-Night Preview
        </div>
        <div className="night-nav-actions">
          <button
            type="button"
            className="back-btn"
            onPointerDown={() => setBefore(true)}
            onPointerUp={() => setBefore(false)}
            onPointerLeave={() => setBefore(false)}
          >
            &#128065; Hold: Before
          </button>
          <button type="button" className="back-btn" onClick={exportImage}>
            &#8615; Export Image
          </button>
          <button type="button" className="back-btn" onClick={saveToProposal}>
            &#9733; Save to Proposal
          </button>
          <button type="button" className="back-btn" onClick={onClose}>
            &#8592; Done
          </button>
        </div>
      </div>
      <div className="night-stage" ref={stageRef}>
        <canvas
          id="night-canvas"
          ref={canvasRef}
          width={800}
          height={500}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
        />
        {!hasImage ? (
          <div className="night-empty">
            Add a photo of the home, then tap to drop lights.
          </div>
        ) : null}
      </div>
      <div className="night-toolbar">
        <div className="night-row">
          <input
            type="file"
            ref={fileRef}
            accept="image/*"
            style={{ display: "none" }}
            onChange={(e) => loadFile(e.currentTarget)}
          />
          <button
            type="button"
            className="night-file-btn"
            onClick={() => fileRef.current?.click()}
          >
            &#128247; Add / Change Photo
          </button>
          <div className="night-types">
            {NIGHT_TYPES.map((t) => (
              <button
                key={t.key}
                type="button"
                className={`night-type-btn${t.key === type ? " active" : ""}`}
                onClick={() => applyType(t.key)}
              >
                {t.label}
              </button>
            ))}
          </div>
          <button type="button" className="night-mini-btn" onClick={undo}>
            &#8630; Undo
          </button>
          <button type="button" className="night-mini-btn" onClick={clearLights}>
            &#10005; Clear Lights
          </button>
        </div>
        <div className="night-sliders">
          <div className="night-slider-wrap">
            <div className="night-slider-label">
              Dusk <span>{Math.round(dusk * 100)}%</span>
            </div>
            <input
              className="night-slider"
              type="range"
              min={0}
              max={92}
              value={Math.round(dusk * 100)}
              onChange={(e) => setDusk(Number(e.target.value) / 100)}
            />
          </div>
          <div className="night-slider-wrap">
            <div className="night-slider-label">
              Glow Size <span>{sliders.glow}</span>
            </div>
            <input
              className="night-slider"
              type="range"
              min={40}
              max={420}
              value={sliders.glow}
              onChange={(e) => applySliders({ glow: Number(e.target.value) })}
            />
          </div>
          <div className="night-slider-wrap">
            <div className="night-slider-label">
              Intensity <span>{Math.round(sliders.intensity * 100)}%</span>
            </div>
            <input
              className="night-slider"
              type="range"
              min={10}
              max={100}
              value={Math.round(sliders.intensity * 100)}
              onChange={(e) =>
                applySliders({ intensity: Number(e.target.value) / 100 })
              }
            />
          </div>
          <div className="night-slider-wrap">
            <div className="night-slider-label">
              {activeType === "bistro" ? "String Sag" : "Spread"}{" "}
              <span>{sliders.spread}</span>
            </div>
            <input
              className="night-slider"
              type="range"
              min={20}
              max={320}
              value={sliders.spread}
              onChange={(e) => applySliders({ spread: Number(e.target.value) })}
            />
          </div>
          <div className="night-slider-wrap">
            <div className="night-slider-label">
              Warmth <span>{warmthLabel}</span>
            </div>
            <input
              className="night-slider"
              type="range"
              min={0}
              max={100}
              value={Math.round(sliders.warmth * 100)}
              onChange={(e) =>
                applySliders({ warmth: Number(e.target.value) / 100 })
              }
            />
          </div>
        </div>
        <div className="night-hint">
          Tap the photo to drop a light &middot; Bistro: press &amp; drag to
          hang a string, drag its ends to re-span &middot; sliders adjust the
          selected light &middot; hold &ldquo;Before&rdquo; to compare.
        </div>
      </div>
    </div>
  );
}
