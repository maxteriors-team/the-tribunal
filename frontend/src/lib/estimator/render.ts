/**
 * Canvas glow engine for the light designer (pure canvas, no React).
 *
 * Ported from the in-house Maxteriors light-estimator. Renders traced runs
 * (C9 / mini / garland / stake / permanent / bistro) and placed items (wreath /
 * wrapped tree / landscape fixtures) as additively-blended glowing light on a
 * photo, plus the editor chrome (draft line, selection handles, calibration
 * ruler). Bulb sprites are pre-rendered per color and cached; gradients respect
 * the canvas transform, so the same code paths drive the on-screen editor and a
 * full-resolution export.
 *
 * Coordinates are image-space pixels. `pxPerFt` sizes bulbs to real-world scale.
 */
import { distance, jitter, pointsAlongPath } from "./geometry";
import type { Point } from "./measure";
import { beamAngleFor, clampBeamAngle, isLandscapeStyle } from "./types";
import type {
  Calibration,
  Design,
  PlacedItem,
  Product,
  RenderStyle,
  Run,
  Selection,
} from "./types";

/** Darkening applied at full dusk, matching the retired night-preview canvas. */
export const MAX_DUSK = 0.92;
/** Default dusk for a fresh design — dark enough to sell, light enough to place. */
export const DEFAULT_DUSK = 0.52;

// ---------------------------------------------------------------------------
// Bulb sprite cache — pre-rendered radial glow per color, drawn scaled.
// ---------------------------------------------------------------------------

const SPRITE = 64;
const spriteCache = new Map<string, HTMLCanvasElement>();

function hexToRgb(hex: string): [number, number, number] {
  const h = hex.replace("#", "");
  const v =
    h.length === 3
      ? h
          .split("")
          .map((c) => c + c)
          .join("")
      : h;
  const n = parseInt(v, 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

const rgba = (hex: string, a: number): string => {
  const [r, g, b] = hexToRgb(hex);
  return `rgba(${r},${g},${b},${a})`;
};

function bulbSprite(color: string): HTMLCanvasElement {
  const cached = spriteCache.get(color);
  if (cached) return cached;
  const c = document.createElement("canvas");
  c.width = c.height = SPRITE;
  const ctx = c.getContext("2d")!;
  const half = SPRITE / 2;

  let g = ctx.createRadialGradient(half, half, 0, half, half, half);
  g.addColorStop(0, rgba(color, 0.9));
  g.addColorStop(0.28, rgba(color, 0.5));
  g.addColorStop(1, rgba(color, 0));
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, SPRITE, SPRITE);

  g = ctx.createRadialGradient(half, half, 0, half, half, SPRITE * 0.17);
  g.addColorStop(0, "rgba(255,255,255,1)");
  g.addColorStop(0.5, rgba(color, 1));
  g.addColorStop(1, rgba(color, 0));
  ctx.fillStyle = g;
  ctx.beginPath();
  ctx.arc(half, half, SPRITE * 0.17, 0, Math.PI * 2);
  ctx.fill();

  spriteCache.set(color, c);
  return c;
}

/** Draw one glowing bulb. `r` is the core radius in current canvas units. */
function drawBulb(
  ctx: CanvasRenderingContext2D,
  p: Point,
  r: number,
  color: string,
): void {
  const glowR = r * 3.6;
  ctx.drawImage(bulbSprite(color), p.x - glowR, p.y - glowR, glowR * 2, glowR * 2);
}

function strokePath(
  ctx: CanvasRenderingContext2D,
  pts: readonly Point[],
  style: string,
  width: number,
  dash?: number[],
): void {
  if (pts.length < 2) return;
  ctx.save();
  ctx.strokeStyle = style;
  ctx.lineWidth = width;
  ctx.lineJoin = "round";
  ctx.lineCap = "round";
  if (dash) ctx.setLineDash(dash);
  ctx.beginPath();
  ctx.moveTo(pts[0].x, pts[0].y);
  for (let i = 1; i < pts.length; i += 1) ctx.lineTo(pts[i].x, pts[i].y);
  ctx.stroke();
  ctx.restore();
}

// ---------------------------------------------------------------------------
// Run + item rendering (image coordinate space)
// ---------------------------------------------------------------------------

export function drawRunLights(
  ctx: CanvasRenderingContext2D,
  points: readonly Point[],
  product: Product,
  pxPerFt: number,
  minR = 0,
): void {
  if (points.length < 2) return;
  const inch = Math.max(pxPerFt / 12, 0.2);
  const colors = product.colors.length > 0 ? product.colors : ["#ffd98a"];
  // Visual-only bulb-size multiplier (Small…Jumbo). Never touches spacing or the
  // measured feet, so pricing is unaffected — just how big the glow reads.
  const scale = product.bulbScale ?? 1;

  switch (product.style) {
    case "mini": {
      const spacing = Math.max(inch * (product.spacingIn || 4), 1.5);
      const r = Math.max(inch * 0.7, minR * 0.55, 0.8) * scale;
      pointsAlongPath(points, spacing).forEach((q, i) => {
        const off = jitter(i * 13 + 1) * inch * 3;
        const nx = -Math.sin(q.angle);
        const ny = Math.cos(q.angle);
        drawBulb(
          ctx,
          { x: q.p.x + nx * off, y: q.p.y + ny * off },
          r,
          colors[i % colors.length],
        );
      });
      break;
    }
    case "garland": {
      strokePath(ctx, points, "rgba(14,52,26,0.92)", Math.max(inch * 5, 4));
      strokePath(ctx, points, "rgba(32,92,46,0.85)", Math.max(inch * 3, 2.5));
      const spacing = Math.max(inch * (product.spacingIn || 8), 2);
      const r = Math.max(inch * 0.8, minR * 0.6, 0.9) * scale;
      pointsAlongPath(points, spacing).forEach((q, i) => {
        const off = jitter(i * 7 + 3) * inch * 1.8;
        const nx = -Math.sin(q.angle);
        const ny = Math.cos(q.angle);
        drawBulb(
          ctx,
          { x: q.p.x + nx * off, y: q.p.y + ny * off },
          r,
          colors[i % colors.length],
        );
      });
      break;
    }
    case "stake": {
      const spacing = Math.max(inch * (product.spacingIn || 30), 4);
      const r = Math.max(inch * 1.8, minR, 1.6) * scale;
      pointsAlongPath(points, spacing).forEach((q, i) => {
        drawBulb(ctx, q.p, r, colors[i % colors.length]);
      });
      break;
    }
    case "permanent": {
      // aluminum channel with evenly spaced LED pucks — clean, no jitter
      strokePath(ctx, points, "rgba(126,134,148,0.4)", Math.max(inch * 1.1, 1.4));
      const spacing = Math.max(inch * (product.spacingIn || 9), 2);
      const r = Math.max(inch * 1.5, minR, 1.4) * scale;
      pointsAlongPath(points, spacing).forEach((q, i) => {
        drawBulb(ctx, q.p, r, colors[i % colors.length]);
      });
      break;
    }
    case "bistro": {
      // Festoon hangs between the points the rep clicked, so each span sags
      // instead of following the traced line dead straight.
      const spacing = Math.max(inch * (product.spacingIn || 24), 2);
      const r = Math.max(inch * 1.5, minR, 1.4) * scale;
      let index = 0;
      for (let i = 1; i < points.length; i += 1) {
        const curve = sagPoints(points[i - 1], points[i], spacing);
        strokePath(ctx, curve, "rgba(20,26,38,0.45)", Math.max(inch * 0.5, 1));
        for (const p of curve.slice(0, -1)) {
          drawBulb(ctx, p, r, colors[index % colors.length]);
          index += 1;
        }
      }
      const last = points[points.length - 1];
      if (last) drawBulb(ctx, last, r, colors[index % colors.length]);
      break;
    }
    case "c9":
    default: {
      strokePath(ctx, points, "rgba(15,20,30,0.4)", Math.max(inch * 0.5, 1));
      const spacing = Math.max(inch * (product.spacingIn || 12), 2);
      const r = Math.max(inch * 1.6, minR, 1.4) * scale;
      pointsAlongPath(points, spacing).forEach((q, i) => {
        drawBulb(ctx, q.p, r, colors[i % colors.length]);
      });
      break;
    }
  }
}

/**
 * Sample a sagging span between two anchors as a quadratic curve, one sample
 * per `spacing` of arc. Sag depth scales with the span so a short jump between
 * two posts hangs shallow and a long run across a patio hangs deep.
 */
function sagPoints(a: Point, b: Point, spacing: number): Point[] {
  const len = distance(a, b);
  const sag = len * 0.14;
  const cx = (a.x + b.x) / 2;
  const cy = (a.y + b.y) / 2 + sag * 2;
  const steps = Math.max(2, Math.round(len / Math.max(spacing, 1)));
  const out: Point[] = [];
  for (let i = 0; i <= steps; i += 1) {
    const t = i / steps;
    const u = 1 - t;
    out.push({
      x: u * u * a.x + 2 * u * t * cx + t * t * b.x,
      y: u * u * a.y + 2 * u * t * cy + t * t * b.y,
    });
  }
  return out;
}

/**
 * Beam geometry for a landscape fixture, in image pixels.
 *
 * `sizePx` is always the **throw** the rep dragged: how far the light reaches.
 * `beamAngleDeg` is the lamp's spread; the width at the end of the throw is the
 * honest trigonometry of that cone (`2 · reach · tan(angle/2)`), so swapping a
 * 15° narrow spot for a 60° wide flood reads on the photo the way it will read
 * on the house. `dir` is -1 for fixtures that aim up from the ground and +1 for
 * a downlight throwing from a soffit or a tree, so one cone routine covers both.
 * Path lights have no cone (they pool on the ground) and return `null`.
 */
function beamGeometry(
  style: RenderStyle,
  sizePx: number,
  beamAngleDeg?: number,
): { reach: number; topW: number; dir: -1 | 1 } | null {
  const angle = beamAngleFor(style, beamAngleDeg);
  if (angle === null) return null;
  const spread = 2 * Math.tan((angle * Math.PI) / 360);
  return { reach: sizePx, topW: sizePx * spread, dir: style === "downlight" ? 1 : -1 };
}

/** Ground-pool geometry (path light, and the splash under a downlight). */
const POOL_SQUASH = 0.42;

function drawPool(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  r: number,
  color: string,
  peak: number,
): void {
  const radius = Math.max(r, 1);
  ctx.save();
  ctx.translate(x, y);
  ctx.scale(1, POOL_SQUASH);
  // The gradient must be built *inside* the translated/scaled space, centred on
  // the origin the arc is drawn at. A canvas gradient is transformed by the CTM
  // when it paints, so one created in the parent space lands at (2x, 2y) — the
  // pool then fills with its own transparent outer stop, i.e. a path light that
  // silently renders nothing while still being counted and billed.
  const g = ctx.createRadialGradient(0, 0, 0, 0, 0, radius);
  g.addColorStop(0, rgba(color, peak));
  g.addColorStop(0.4, rgba(color, peak * 0.42));
  g.addColorStop(1, rgba(color, 0));
  ctx.fillStyle = g;
  ctx.beginPath();
  ctx.arc(0, 0, radius, 0, Math.PI * 2);
  ctx.fill();
  ctx.restore();
}

/**
 * A landscape fixture's throw. `item.sizePx` is the throw distance — beam length
 * for uplight / in-grade / downlight, pool diameter for a path light — so the
 * rep resizes the *light*, which is what the customer is buying.
 */
function drawLandscapeFixture(
  ctx: CanvasRenderingContext2D,
  item: PlacedItem,
  product: Product,
): void {
  const color = product.colors[0] ?? "#ffd98a";
  const { x, y } = item.at;
  const size = Math.max(item.sizePx, 2);

  if (product.style === "pathlight") {
    drawPool(ctx, x, y, size / 2, color, 0.62);
    return;
  }

  const beam = beamGeometry(product.style, size, item.beamAngleDeg);
  if (!beam) return;
  const { reach, topW, dir } = beam;
  const baseW = Math.max(1.5, topW * 0.18);
  ctx.save();
  ctx.translate(x, y);
  const g = ctx.createLinearGradient(0, 0, 0, dir * reach);
  g.addColorStop(0, rgba(color, 0.5));
  g.addColorStop(1, rgba(color, 0));
  ctx.fillStyle = g;
  ctx.beginPath();
  ctx.moveTo(-baseW / 2, 0);
  ctx.lineTo(baseW / 2, 0);
  ctx.lineTo(topW / 2, dir * reach);
  ctx.lineTo(-topW / 2, dir * reach);
  ctx.closePath();
  ctx.fill();
  ctx.restore();

  // A downlight lands on something; show the splash where the beam hits.
  if (dir === 1) drawPool(ctx, x, y + reach, topW / 2, color, 0.34);

  const lensR = Math.max(2, topW * 0.34);
  const lens = ctx.createRadialGradient(x, y, 0, x, y, lensR);
  lens.addColorStop(0, rgba(color, 0.62));
  lens.addColorStop(1, rgba(color, 0));
  ctx.fillStyle = lens;
  ctx.beginPath();
  ctx.arc(x, y, lensR, 0, Math.PI * 2);
  ctx.fill();
}

export function drawPlacedItem(
  ctx: CanvasRenderingContext2D,
  item: PlacedItem,
  product: Product,
  pxPerFt: number,
  minR = 0,
): void {
  const inch = Math.max(pxPerFt / 12, 0.2);
  const colors = product.colors.length > 0 ? product.colors : ["#ffd98a"];

  if (isLandscapeStyle(product.style)) {
    drawLandscapeFixture(ctx, item, product);
    return;
  }

  if (product.style === "treewrap") {
    const h = item.sizePx;
    const topW = h * 0.09;
    const botW = h * 0.13;
    const top = { x: item.at.x, y: item.at.y - h / 2 };
    // soft ambient glow
    const g = ctx.createRadialGradient(
      item.at.x,
      item.at.y,
      0,
      item.at.x,
      item.at.y,
      h * 0.5,
    );
    g.addColorStop(0, rgba(colors[0], 0.25));
    g.addColorStop(1, rgba(colors[0], 0));
    ctx.fillStyle = g;
    ctx.beginPath();
    ctx.ellipse(item.at.x, item.at.y, botW * 3, h * 0.55, 0, 0, Math.PI * 2);
    ctx.fill();
    // wrapped rows of minis
    const rowStep = Math.max(inch * 4, 2);
    const r = Math.max(inch * 0.65, minR * 0.5, 0.8);
    let i = 0;
    for (let y = 0; y <= h; y += rowStep) {
      const w = topW + (botW - topW) * (y / h);
      const colStep = Math.max(inch * 3, 1.6);
      const phase = (i % 2) * (colStep / 2);
      for (let x = -w + phase; x <= w; x += colStep) {
        drawBulb(
          ctx,
          {
            x: top.x + x + jitter(i * 31 + x) * inch * 0.8,
            y: top.y + y + jitter(i * 7 + x * 3) * inch * 0.8,
          },
          r,
          colors[i % colors.length],
        );
      }
      i += 1;
    }
    return;
  }

  // wreath (default for 'each')
  const R = item.sizePx / 2;
  const ringR = R * 0.72;
  ctx.save();
  ctx.strokeStyle = "rgba(14,52,26,0.95)";
  ctx.lineWidth = R * 0.42;
  ctx.beginPath();
  ctx.arc(item.at.x, item.at.y, ringR, 0, Math.PI * 2);
  ctx.stroke();
  ctx.strokeStyle = "rgba(36,99,50,0.9)";
  ctx.lineWidth = R * 0.26;
  ctx.beginPath();
  ctx.arc(item.at.x, item.at.y, ringR, 0, Math.PI * 2);
  ctx.stroke();
  ctx.restore();

  const n = Math.max(10, Math.round((2 * Math.PI * ringR) / Math.max(inch * 4, 2)));
  const r = Math.max(inch * 0.7, minR * 0.55, 0.9);
  for (let i = 0; i < n; i += 1) {
    const a = (i / n) * Math.PI * 2;
    const rr = ringR + jitter(i * 17 + 5) * R * 0.12;
    drawBulb(
      ctx,
      { x: item.at.x + Math.cos(a) * rr, y: item.at.y + Math.sin(a) * rr },
      r,
      colors[i % colors.length],
    );
  }

  // red bow at top
  const bw = R * 0.34;
  const bx = item.at.x;
  const by = item.at.y - ringR;
  ctx.save();
  ctx.fillStyle = "#c62828";
  ctx.beginPath();
  ctx.ellipse(bx - bw * 0.62, by, bw * 0.6, bw * 0.38, -0.35, 0, Math.PI * 2);
  ctx.fill();
  ctx.beginPath();
  ctx.ellipse(bx + bw * 0.62, by, bw * 0.6, bw * 0.38, 0.35, 0, Math.PI * 2);
  ctx.fill();
  ctx.fillStyle = "#e53935";
  ctx.beginPath();
  ctx.arc(bx, by, bw * 0.26, 0, Math.PI * 2);
  ctx.fill();
  ctx.restore();
}

// ---------------------------------------------------------------------------
// Full scene
// ---------------------------------------------------------------------------

export interface DraftRun {
  points: Point[];
  product: Product;
}

export interface SceneOpts {
  /** screen px per image px — keeps UI chrome a constant screen size */
  viewScale: number;
  selection?: Selection;
  draftRun?: DraftRun | null;
  draftCalPoint?: Point | null;
  hoverPt?: Point | null;
  /**
   * How far past sunset the scene reads, 0 (daylight photo) to `MAX_DUSK`.
   * Continuous rather than a night on/off switch so the rep can drag the sun
   * down while the customer watches the house light up.
   */
  dusk?: number;
  showChrome?: boolean;
  calibrateTool?: boolean;
}

export function drawScene(
  ctx: CanvasRenderingContext2D,
  photo: HTMLImageElement,
  design: Design,
  productById: Map<string, Product>,
  pxPerFt: number,
  opts: SceneOpts,
): void {
  const vs = Math.max(opts.viewScale, 0.001);
  // keep bulbs readable (and sellable) even on wide photos / small houses
  const minR = photo.naturalWidth * 0.0024;

  ctx.drawImage(photo, 0, 0);

  const dusk = Math.min(Math.max(opts.dusk ?? 0, 0), MAX_DUSK);
  if (dusk > 0) {
    ctx.fillStyle = `rgba(4,10,32,${dusk})`;
    ctx.fillRect(0, 0, photo.naturalWidth, photo.naturalHeight);
  }

  // glow pass — additive blending so overlapping glows feel like real light
  ctx.save();
  ctx.globalCompositeOperation = "lighter";
  for (const run of design.runs) {
    const p = productById.get(run.productId);
    if (p) drawRunLights(ctx, run.points, withRunOverrides(p, run), pxPerFt, minR);
  }
  for (const item of design.items) {
    const p = productById.get(item.productId);
    if (!p) continue;
    // Decor (wreaths, wrapped trees) paints opaque greenery, so it draws over
    // the photo; a landscape fixture is pure light and stays additive.
    const additive = isLandscapeStyle(p.style);
    if (!additive) ctx.globalCompositeOperation = "source-over";
    drawPlacedItem(ctx, item, p, pxPerFt, minR);
    if (!additive) ctx.globalCompositeOperation = "lighter";
  }
  if (opts.draftRun && opts.draftRun.points.length > 0) {
    const pts = opts.hoverPt
      ? [...opts.draftRun.points, opts.hoverPt]
      : opts.draftRun.points;
    drawRunLights(ctx, pts, opts.draftRun.product, pxPerFt, minR);
  }
  ctx.restore();

  if (!opts.showChrome) return;

  // draft helper line + vertices
  if (opts.draftRun && opts.draftRun.points.length > 0) {
    const pts = opts.hoverPt
      ? [...opts.draftRun.points, opts.hoverPt]
      : opts.draftRun.points;
    strokePath(ctx, pts, "rgba(255,255,255,0.55)", 1.2 / vs, [5 / vs, 4 / vs]);
    for (const p of opts.draftRun.points) handleDot(ctx, p, 3 / vs);
  }

  // selection
  if (opts.selection?.kind === "run") {
    const run = design.runs.find((r) => r.id === opts.selection!.id);
    if (run) {
      strokePath(ctx, run.points, "rgba(245,200,66,0.9)", 1.6 / vs, [7 / vs, 5 / vs]);
      for (const p of run.points) handleSquare(ctx, p, 5 / vs);
    }
  } else if (opts.selection?.kind === "item") {
    const item = design.items.find((i) => i.id === opts.selection!.id);
    const product = item ? productById.get(item.productId) : undefined;
    if (item && product && isLandscapeStyle(product.style)) {
      // A beam is directional: ring the fixture itself and trace its throw,
      // rather than drawing a circle centred on a light that only goes up.
      drawFixtureSelection(ctx, item, product, vs);
      handleSquare(ctx, resizeHandlePos(item, product), 5 / vs);
      // Second, gold grip on the cone's edge: throw is white, spread is gold, so
      // the two grips can't be confused for each other mid-demo.
      const spreadGrip = beamHandlePos(item, product);
      if (spreadGrip) handleSquare(ctx, spreadGrip, 5 / vs, "#f5c842");
    } else if (item) {
      const r = item.sizePx / 2 + 6 / vs;
      ctx.save();
      ctx.strokeStyle = "rgba(245,200,66,0.9)";
      ctx.lineWidth = 1.6 / vs;
      ctx.setLineDash([7 / vs, 5 / vs]);
      ctx.beginPath();
      ctx.arc(item.at.x, item.at.y, r, 0, Math.PI * 2);
      ctx.stroke();
      ctx.restore();
      handleSquare(ctx, resizeHandlePos(item), 5 / vs);
    }
  }

  // calibration line — only while the scale tool is active
  const cal = design.calibration;
  if (cal && opts.calibrateTool) drawCalibration(ctx, cal, vs);
  if (opts.draftCalPoint) {
    handleSquare(ctx, opts.draftCalPoint, 5 / vs, "#4fd9ff");
    if (opts.hoverPt) {
      strokePath(
        ctx,
        [opts.draftCalPoint, opts.hoverPt],
        "rgba(79,217,255,0.9)",
        2 / vs,
        [6 / vs, 4 / vs],
      );
    }
  }
}

/** Apply a run's spacing/color overrides on top of its product. */
export function withRunOverrides(product: Product, run: Run): Product {
  if (run.spacingIn == null && run.colors == null && run.bulbScale == null) {
    return product;
  }
  return {
    ...product,
    spacingIn: run.spacingIn ?? product.spacingIn,
    colors: run.colors ?? product.colors,
    bulbScale: run.bulbScale ?? product.bulbScale,
  };
}

/**
 * Where the resize grip sits for a placed item. Decor is resized from its
 * lower-right corner; a landscape fixture is resized by its throw, so the grip
 * rides at the end of the beam (or the edge of the pool) it actually controls.
 */
export function resizeHandlePos(item: PlacedItem, product?: Product): Point {
  if (product && isLandscapeStyle(product.style)) {
    const beam = beamGeometry(product.style, item.sizePx, item.beamAngleDeg);
    if (!beam) {
      const r = item.sizePx / 2;
      return { x: item.at.x + r, y: item.at.y + r * POOL_SQUASH };
    }
    return { x: item.at.x, y: item.at.y + beam.dir * beam.reach };
  }
  const r = item.sizePx / 2;
  const d = r * Math.SQRT1_2 + 0.35 * r;
  return { x: item.at.x + d, y: item.at.y + d };
}

/**
 * Where the beam-spread grip sits: the outer edge of the cone at the end of the
 * throw. Dragging it opens or closes the beam, which is the one property of a
 * landscape fixture a rep argues about on site ("that's washing the whole wall,
 * I want it grazing the column"). `null` for anything without a cone — a path
 * light's spread *is* its pool, already dragged by the resize grip.
 */
export function beamHandlePos(
  item: PlacedItem,
  product?: Product,
): Point | null {
  if (!product) return null;
  const beam = beamGeometry(product.style, item.sizePx, item.beamAngleDeg);
  if (!beam) return null;
  return {
    x: item.at.x + beam.topW / 2,
    y: item.at.y + beam.dir * beam.reach,
  };
}

/**
 * The beam angle that puts the cone's edge under the pointer, in degrees.
 *
 * Only the sideways distance is read: the throw stays exactly where the rep set
 * it, so opening the beam never also stretches how far the light reaches.
 */
export function beamAngleAt(item: PlacedItem, p: Point): number {
  const reach = Math.max(item.sizePx, 1);
  const half = Math.atan2(Math.abs(p.x - item.at.x), reach);
  return clampBeamAngle((half * 360) / Math.PI);
}

/** Dashed outline of a landscape fixture's throw, drawn while it is selected. */
function drawFixtureSelection(
  ctx: CanvasRenderingContext2D,
  item: PlacedItem,
  product: Product,
  vs: number,
): void {
  const { x, y } = item.at;
  ctx.save();
  ctx.strokeStyle = "rgba(245,200,66,0.9)";
  ctx.lineWidth = 1.6 / vs;
  ctx.setLineDash([7 / vs, 5 / vs]);
  const beam = beamGeometry(product.style, item.sizePx, item.beamAngleDeg);
  if (!beam) {
    const r = item.sizePx / 2;
    ctx.beginPath();
    ctx.ellipse(x, y, r, r * POOL_SQUASH, 0, 0, Math.PI * 2);
    ctx.stroke();
  } else {
    const far = y + beam.dir * beam.reach;
    ctx.beginPath();
    ctx.moveTo(x - beam.topW / 2, far);
    ctx.lineTo(x, y);
    ctx.lineTo(x + beam.topW / 2, far);
    ctx.stroke();
  }
  ctx.setLineDash([]);
  ctx.beginPath();
  ctx.arc(x, y, 7 / vs, 0, Math.PI * 2);
  ctx.stroke();
  ctx.restore();
}

function handleSquare(
  ctx: CanvasRenderingContext2D,
  p: Point,
  r: number,
  color = "#ffffff",
): void {
  ctx.save();
  ctx.fillStyle = color;
  ctx.strokeStyle = "rgba(10,14,26,0.9)";
  ctx.lineWidth = r * 0.4;
  ctx.beginPath();
  ctx.rect(p.x - r, p.y - r, r * 2, r * 2);
  ctx.fill();
  ctx.stroke();
  ctx.restore();
}

function handleDot(ctx: CanvasRenderingContext2D, p: Point, r: number): void {
  ctx.save();
  ctx.fillStyle = "#ffffff";
  ctx.strokeStyle = "rgba(10,14,26,0.9)";
  ctx.lineWidth = r * 0.5;
  ctx.beginPath();
  ctx.arc(p.x, p.y, r, 0, Math.PI * 2);
  ctx.fill();
  ctx.stroke();
  ctx.restore();
}

export function drawCalibration(
  ctx: CanvasRenderingContext2D,
  cal: Calibration,
  vs: number,
): void {
  strokePath(ctx, [cal.a, cal.b], "rgba(79,217,255,0.95)", 2 / vs);
  // end ticks
  const ang = Math.atan2(cal.b.y - cal.a.y, cal.b.x - cal.a.x) + Math.PI / 2;
  const t = 7 / vs;
  for (const p of [cal.a, cal.b]) {
    strokePath(
      ctx,
      [
        { x: p.x + Math.cos(ang) * t, y: p.y + Math.sin(ang) * t },
        { x: p.x - Math.cos(ang) * t, y: p.y - Math.sin(ang) * t },
      ],
      "rgba(79,217,255,0.95)",
      2 / vs,
    );
  }
  handleSquare(ctx, cal.a, 4.5 / vs, "#4fd9ff");
  handleSquare(ctx, cal.b, 4.5 / vs, "#4fd9ff");

  const mid = { x: (cal.a.x + cal.b.x) / 2, y: (cal.a.y + cal.b.y) / 2 };
  const label = `${cal.feet} ft`;
  ctx.save();
  const fontPx = 12 / vs;
  ctx.font = `600 ${fontPx}px system-ui, sans-serif`;
  const w = ctx.measureText(label).width;
  const padX = 6 / vs;
  const padY = 4 / vs;
  const bx = mid.x - w / 2 - padX;
  const by = mid.y - fontPx - padY * 2 - 8 / vs;
  ctx.fillStyle = "rgba(8,14,30,0.85)";
  roundRect(ctx, bx, by, w + padX * 2, fontPx + padY * 2, 4 / vs);
  ctx.fill();
  ctx.fillStyle = "#4fd9ff";
  ctx.textBaseline = "middle";
  ctx.fillText(label, mid.x - w / 2, by + (fontPx + padY * 2) / 2);
  ctx.restore();
}

function roundRect(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  w: number,
  h: number,
  r: number,
): void {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}

/** Hit-test helper: an item's body radius in image pixels. */
/**
 * Grab radius for a placed item. Decor is grabbed anywhere inside it; a
 * landscape fixture is grabbed by the fixture, not by the beam — otherwise a
 * long throw would swallow every click across half the house.
 */
export function itemHitRadius(item: PlacedItem, product?: Product): number {
  if (product && isLandscapeStyle(product.style)) {
    if (product.style === "pathlight") {
      return Math.min(item.sizePx / 2, Math.max(14, item.sizePx * 0.22));
    }
    return Math.max(14, item.sizePx * 0.14);
  }
  return item.sizePx / 2;
}

export function itemHit(
  item: PlacedItem,
  p: Point,
  slack: number,
  product?: Product,
): boolean {
  return distance(item.at, p) <= itemHitRadius(item, product) + slack;
}
