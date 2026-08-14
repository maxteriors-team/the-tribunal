"use client";

/**
 * Left rail for the light designer: tools, the drawable product palette, and
 * the per-run styling controls (adapted from the in-house light-estimator
 * Toolbar + RunOptions).
 *
 * Products come from the server-derived catalog; their prices are display-only
 * rates. Picking a product arms the draw/place tool; selecting a run on the
 * canvas reveals its spacing/color overrides here.
 *
 * The rail is grouped by product line — landscape fixtures from the price book,
 * then holiday strands and decor — so one palette covers everything the rep
 * sells on a photo instead of a separate tool per product line.
 */
import { MousePointer2, Redo2, Ruler, Trash2, Undo2 } from "lucide-react";
import { type Dispatch } from "react";

import {
  BEAM_ANGLE_OPTIONS,
  BULB_SIZE_OPTIONS,
  COLOR_PRESETS,
  SPACING_OPTIONS,
  beamAngleNameFor,
  bulbSizeNameFor,
  presetNameFor,
} from "@/lib/estimator/catalog";
import { LANDSCAPE_WIRE_GAUGES, landscapeWireLabel } from "@/lib/estimator/fixtures";
import { FIXTURE_MARKER_COLORS } from "@/lib/estimator/marker-colors";
import { seasonalIconForStyle, tintSurface } from "@/lib/estimator/seasonal-icons";
import {
  MAX_BEAM_ANGLE_DEG,
  MIN_BEAM_ANGLE_DEG,
  beamAngleFor,
  beamRotationFor,
  clampBeamAngle,
  isLandscapePlanStyle,
  normalizeBeamRotation,
} from "@/lib/estimator/types";
import type { Design, PlacedItem, Product, Run } from "@/lib/estimator/types";
import { formatCurrency } from "@/lib/utils/number";

import type { EditorAction, EditorState } from "./editor-store";

function newPlacedItemId(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `item-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

interface ToolPaletteProps {
  products: Product[];
  state: EditorState;
  dispatch: Dispatch<EditorAction>;
}

/**
 * The colors a product installs in. Capped at four dots: past that the swatch
 * starts eating the name column, and "multicolor" reads the same at four dots
 * as at six — but a truncated product name does not.
 */
function Swatch({ colors }: { colors: string[] }) {
  return (
    <span className="tp-swatch">
      {colors.slice(0, 4).map((c, i) => (
        <i key={`${c}-${i}`} style={{ background: c, boxShadow: `0 0 6px ${c}` }} />
      ))}
    </span>
  );
}

export function ToolPalette({ products, state, dispatch }: ToolPaletteProps) {
  const { tool, selection, design } = state;

  const landscape = products.filter((p) => p.category === "landscape");
  const holiday = products.filter((p) => p.category !== "landscape");
  const linear = holiday.filter((p) => p.kind === "linear");
  const each = holiday.filter((p) => p.kind === "each");
  const canUndo = state.past.length > 0;
  const canRedo = state.future.length > 0;
  const hasDrawn = design.runs.length > 0 || design.items.length > 0;

  const isActiveProduct = (id: string) =>
    (tool.type === "draw" || tool.type === "place") && tool.productId === id;

  const selectedRun =
    selection?.kind === "run" ? design.runs.find((r) => r.id === selection.id) : undefined;
  const selectedItem =
    selection?.kind === "item" ? design.items.find((i) => i.id === selection.id) : undefined;
  const selectedItemProduct = selectedItem
    ? products.find((p) => p.id === selectedItem.productId)
    : undefined;
  const selectedRunProduct = selectedRun
    ? products.find((product) => product.id === selectedRun.productId)
    : undefined;

  return (
    <aside className="tp-rail">
      <div className="tp-section">
        <h2>Tools</h2>
        <button
          type="button"
          className={`tp-tool ${tool.type === "select" ? "active" : ""}`}
          onClick={() => dispatch({ type: "SET_TOOL", tool: { type: "select" } })}
        >
          <MousePointer2 className="tp-glyph" aria-hidden="true" /> Select &amp; edit
          <kbd>V</kbd>
        </button>
        <button
          type="button"
          className={`tp-tool ${tool.type === "calibrate" ? "active" : ""}`}
          onClick={() => dispatch({ type: "SET_TOOL", tool: { type: "calibrate" } })}
        >
          <Ruler className="tp-glyph" aria-hidden="true" /> Set scale
          <kbd>S</kbd>
        </button>
      </div>

      <div className="tp-section tp-grow">
        {landscape.length > 0 ? (
          <>
            <h2>Landscape fixtures</h2>
            {landscape.map((p) => (
              <ProductButton
                key={p.id}
                product={p}
                active={isActiveProduct(p.id)}
                dispatch={dispatch}
              />
            ))}
          </>
        ) : null}

        {linear.length > 0 ? (
          <>
            <h2 className={landscape.length > 0 ? "tp-mt" : undefined}>Draw lights</h2>
            {linear.map((p) => (
              <ProductButton
                key={p.id}
                product={p}
                active={isActiveProduct(p.id)}
                dispatch={dispatch}
              />
            ))}
          </>
        ) : null}

        {each.length > 0 ? (
          <>
            <h2 className="tp-mt">Place decor</h2>
            {each.map((p) => (
              <ProductButton
                key={p.id}
                product={p}
                active={isActiveProduct(p.id)}
                dispatch={dispatch}
              />
            ))}
          </>
        ) : null}

        {selectedRun ? (
          <div className="tp-run-options">
            <h2 className="tp-mt">
              {selectedRunProduct?.style === "wire" ? "Selected circuit" : "Selected strand"}
            </h2>
            <RunOptions run={selectedRun} products={products} design={design} dispatch={dispatch} />
          </div>
        ) : null}

        {selectedItem && selectedItemProduct ? (
          <FixtureOptions
            item={selectedItem}
            product={selectedItemProduct}
            products={products}
            design={design}
            dispatch={dispatch}
          />
        ) : null}
      </div>

      <div className="tp-section tp-actions">
        <button
          type="button"
          className="est-btn"
          disabled={!canUndo}
          onClick={() => dispatch({ type: "UNDO" })}
          title="Undo (⌘Z)"
        >
          <Undo2 className="tp-glyph" aria-hidden="true" /> Undo
        </button>
        <button
          type="button"
          className="est-btn"
          disabled={!canRedo}
          onClick={() => dispatch({ type: "REDO" })}
          title="Redo (⇧⌘Z)"
        >
          <Redo2 className="tp-glyph" aria-hidden="true" /> Redo
        </button>
        <button
          type="button"
          className="est-btn"
          disabled={!hasDrawn}
          onClick={() => dispatch({ type: "CLEAR_DESIGN" })}
          title="Remove all lights (keeps the photo scale)"
        >
          <Trash2 className="tp-glyph" aria-hidden="true" /> Clear
        </button>
      </div>
    </aside>
  );
}

/**
 * One drawable in the rail. Linear products arm the trace tool and price per
 * foot; placed products (landscape fixtures, wreaths, trees) arm the place tool
 * and price per unit. Prices are the catalog's display rate — the server still
 * prices the quote.
 */
function ProductButton({
  product,
  active,
  dispatch,
}: {
  product: Product;
  active: boolean;
  dispatch: Dispatch<EditorAction>;
}) {
  const { Icon, tint } = seasonalIconForStyle(product.style);
  const linear = product.kind === "linear";
  const planOnly = product.style === "wire";
  const price = planOnly
    ? "Plan only"
    : linear
      ? `${formatCurrency(product.price)}/ft`
      : formatCurrency(product.price);
  return (
    <button
      type="button"
      className={`tp-product ${active ? "active" : ""}`}
      aria-pressed={active}
      onClick={() =>
        dispatch({
          type: "SET_TOOL",
          tool: linear
            ? { type: "draw", productId: product.id }
            : { type: "place", productId: product.id },
        })
      }
      title={
        planOnly
          ? "Trace the wire circuit on the plan"
          : linear
            ? `Trace along the photo — ${price}`
            : `Click the photo to place — ${price} each`
      }
    >
      <span
        className="tp-cat-icon"
        style={{ color: tint, background: tintSurface(tint) }}
        aria-hidden="true"
      >
        <Icon className="tp-glyph" />
      </span>
      <Swatch colors={product.colors} />
      <span className="tp-product-name">{product.name}</span>
      <span className="tp-product-price">{price}</span>
    </button>
  );
}

/**
 * Type and beam controls for one selected landscape plan symbol. Switching type
 * preserves its anchor and scales the new symbol/throw from the same drawing
 * calibration, so an uplight can become a path light or transformer in place.
 */
function FixtureOptions({
  item,
  product,
  products,
  design,
  dispatch,
}: {
  item: PlacedItem;
  product: Product;
  products: Product[];
  design: Design;
  dispatch: Dispatch<EditorAction>;
}) {
  if (product.category !== "landscape" || !isLandscapePlanStyle(product.style)) {
    return null;
  }
  const choices = products.filter(
    (candidate) =>
      candidate.category === "landscape" &&
      candidate.kind === "each" &&
      isLandscapePlanStyle(candidate.style),
  );
  const circuits = design.runs.filter(
    (run) => products.find((candidate) => candidate.id === run.productId)?.style === "wire",
  );
  const angle = beamAngleFor(product.style, item.beamAngleDeg);
  const rotation = beamRotationFor(item.beamRotationDeg);
  const natural = product.style === "downlight" ? "down" : "up";

  const markerColorButton = (marker: (typeof FIXTURE_MARKER_COLORS)[number], index: number) => {
    const checked = item.markerColor?.toLowerCase() === marker.value.toLowerCase();
    return (
      <button
        key={marker.value}
        type="button"
        role="radio"
        className={checked ? "on" : ""}
        style={{ backgroundColor: marker.value }}
        aria-label={marker.name}
        aria-checked={checked}
        tabIndex={checked || (!item.markerColor && index === 0) ? 0 : -1}
        onClick={() =>
          dispatch({ type: "UPDATE_ITEM", id: item.id, patch: { markerColor: marker.value } })
        }
        onKeyDown={(event) => {
          if (!["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(event.key)) return;
          event.preventDefault();
          const direction = event.key === "ArrowLeft" || event.key === "ArrowUp" ? -1 : 1;
          const nextIndex =
            (index + direction + FIXTURE_MARKER_COLORS.length) % FIXTURE_MARKER_COLORS.length;
          const nextMarker = FIXTURE_MARKER_COLORS[nextIndex];
          dispatch({ type: "UPDATE_ITEM", id: item.id, patch: { markerColor: nextMarker.value } });
          const radios =
            event.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>(
              '[role="radio"]',
            );
          radios?.[nextIndex]?.focus();
        }}
      />
    );
  };

  const changeType = (next: Product) => {
    if (next.id === product.id) return;
    const pxPerFt = product.sizeFt > 0 ? item.sizePx / product.sizeFt : 1;
    dispatch({
      type: "UPDATE_ITEM",
      id: item.id,
      patch: {
        productId: next.id,
        sizePx: Math.max(12, next.sizeFt * pxPerFt),
        beamAngleDeg: undefined,
        beamRotationDeg: undefined,
        circuitId: next.style === "transformer" ? undefined : item.circuitId,
      },
    });
  };

  return (
    <div className="tp-run-options est-fixture-options">
      <h2 className="tp-mt">Selected symbol</h2>
      <div>
        <p className="tp-opt-label">Change fixture type</p>
        <div className="tp-symbol-grid" role="group" aria-label="Change selected fixture type">
          {choices.map((choice) => {
            const { Icon, tint } = seasonalIconForStyle(choice.style);
            const active = choice.id === product.id;
            return (
              <button
                key={choice.id}
                type="button"
                className={`tp-symbol-choice ${active ? "on" : ""}`}
                aria-pressed={active}
                title={`Change selected symbol to ${choice.name}`}
                onClick={() => changeType(choice)}
              >
                <span
                  className="tp-symbol-choice-icon"
                  style={{ color: tint, background: tintSurface(tint) }}
                  aria-hidden="true"
                >
                  <Icon className="tp-glyph" />
                </span>
                <span>{choice.name}</span>
              </button>
            );
          })}
        </div>
        {product.style === "transformer" ? (
          <p className="tp-opt-readout">
            Power equipment symbol — shown on the plan, not the quote.
          </p>
        ) : angle === null ? (
          <p className="tp-opt-readout">Ground-pool fixture — resize the pool on the photo.</p>
        ) : null}
      </div>

      <div className="tp-mt">
        <p className="tp-opt-label">CRM fixture specification</p>
        <dl className="tp-fixture-spec">
          <div>
            <dt>Product</dt>
            <dd>{product.productName ?? product.name}</dd>
          </div>
          <div>
            <dt>SKU</dt>
            <dd>{product.sku ?? "Not configured"}</dd>
          </div>
          <div>
            <dt>Lamp</dt>
            <dd>{product.lampLabel ?? "Use CRM price-book specification"}</dd>
          </div>
          <div>
            <dt>Accessories</dt>
            <dd>
              {product.accessoryLabels?.length
                ? product.accessoryLabels.join(", ")
                : "None configured in the CRM price book"}
            </dd>
          </div>
        </dl>
      </div>

      <div className="tp-mt">
        <p className="tp-opt-label">Plan marker color</p>
        <div className="tp-marker-colors" role="radiogroup" aria-label="Plan marker color">
          {FIXTURE_MARKER_COLORS.map(markerColorButton)}
        </div>
      </div>

      <div className="tp-mt tp-fixture-size-actions" role="group" aria-label="Fixture symbol size">
        <button
          type="button"
          className="tp-mini-btn"
          aria-label="Decrease fixture symbol size"
          onClick={() =>
            dispatch({
              type: "UPDATE_ITEM",
              id: item.id,
              patch: { sizePx: Math.max(12, item.sizePx * 0.85) },
            })
          }
        >
          Size −
        </button>
        <button
          type="button"
          className="tp-mini-btn"
          aria-label="Increase fixture symbol size"
          onClick={() =>
            dispatch({
              type: "UPDATE_ITEM",
              id: item.id,
              patch: { sizePx: Math.min(100_000, item.sizePx * 1.15) },
            })
          }
        >
          Size +
        </button>
      </div>

      {product.style !== "transformer" ? (
        <div className="tp-mt">
          <p className="tp-opt-label">Transformer circuit</p>
          <select
            className="est-select"
            value={item.circuitId ?? ""}
            aria-label="Assigned transformer circuit"
            onChange={(event) =>
              dispatch({
                type: "UPDATE_ITEM",
                id: item.id,
                patch: { circuitId: event.target.value || undefined },
              })
            }
          >
            <option value="">Unassigned</option>
            {circuits.map((circuit, index) => (
              <option key={circuit.id} value={circuit.id}>
                {circuit.circuitLabel ?? `C${index + 1}`}
              </option>
            ))}
          </select>
          <p className="tp-opt-readout">
            {circuits.length
              ? "Assign this fixture to the wire circuit that feeds it."
              : "Draw a wire circuit before assigning this fixture."}
          </p>
        </div>
      ) : null}

      {angle !== null ? (
        <>
          <div>
            <p className="tp-opt-label">Beam angle</p>
            <div className="tp-chip-row">
              {BEAM_ANGLE_OPTIONS.map((option) => (
                <button
                  key={option.deg}
                  type="button"
                  className={`tp-spacing-chip ${Math.round(angle) === option.deg ? "on" : ""}`}
                  aria-label={`${option.deg} degree beam — ${option.name}`}
                  aria-pressed={Math.round(angle) === option.deg}
                  onClick={() =>
                    dispatch({
                      type: "UPDATE_ITEM",
                      id: item.id,
                      patch: { beamAngleDeg: option.deg },
                    })
                  }
                  title={`${option.name} — ${option.blurb}`}
                >
                  {option.deg}&deg;
                </button>
              ))}
            </div>
            <input
              className="tp-range"
              type="range"
              min={MIN_BEAM_ANGLE_DEG}
              max={MAX_BEAM_ANGLE_DEG}
              step={1}
              value={Math.round(angle)}
              aria-label="Beam angle in degrees"
              aria-valuetext={`${Math.round(angle)} degrees — ${beamAngleNameFor(angle)}`}
              onChange={(event) =>
                dispatch({
                  type: "UPDATE_ITEM",
                  id: item.id,
                  patch: { beamAngleDeg: clampBeamAngle(Number(event.target.value)) },
                })
              }
            />
            <p className="tp-opt-readout">
              {beamAngleNameFor(angle)} · {Math.round(angle)}&deg; — drag the slider, or the gold
              grip on the photo, to fine-tune.
            </p>
          </div>
          <div className="tp-mt">
            <p className="tp-opt-label">Aim</p>
            <input
              className="tp-range"
              type="range"
              min={-180}
              max={180}
              step={1}
              value={Math.round(rotation)}
              aria-label="Beam aim in degrees"
              aria-valuetext={aimLabel(rotation, natural)}
              onChange={(event) =>
                dispatch({
                  type: "UPDATE_ITEM",
                  id: item.id,
                  patch: {
                    beamRotationDeg: normalizeBeamRotation(Number(event.target.value)),
                  },
                })
              }
            />
            <div className="tp-aim-foot">
              <p className="tp-opt-readout">{aimLabel(rotation, natural)}</p>
              <button
                type="button"
                className="tp-mini-btn"
                disabled={Math.round(rotation) === 0}
                onClick={() =>
                  dispatch({
                    type: "UPDATE_ITEM",
                    id: item.id,
                    patch: { beamRotationDeg: 0 },
                  })
                }
              >
                Reset
              </button>
            </div>
          </div>
        </>
      ) : null}

      <div className="tp-mt tp-fixture-item-actions">
        <button
          type="button"
          className="tp-mini-btn"
          onClick={() =>
            dispatch({
              type: "ADD_ITEM",
              item: {
                ...item,
                id: newPlacedItemId(),
                at: { x: item.at.x + 20, y: item.at.y + 20 },
              },
            })
          }
        >
          Duplicate fixture
        </button>
        <button
          type="button"
          className="tp-mini-btn danger"
          onClick={() => dispatch({ type: "DELETE_ITEM", id: item.id })}
        >
          Delete fixture
        </button>
      </div>
    </div>
  );
}

/**
 * Plain-English aim, e.g. "Straight up" or "20° clockwise".
 *
 * Deliberately "clockwise", not "left"/"right": the same rotation swings an
 * uplight's cone right and a downlight's cone left (it points the other way), so
 * a screen-side word would be wrong for half the fixtures on the photo.
 */
function aimLabel(rotationDeg: number, natural: "up" | "down"): string {
  const deg = Math.round(rotationDeg);
  if (deg === 0) return natural === "down" ? "Straight down" : "Straight up";
  if (Math.abs(deg) === 180) return `Flipped — pointing ${natural === "down" ? "up" : "down"}`;
  return `${Math.abs(deg)}\u00b0 ${deg > 0 ? "clockwise" : "counter-clockwise"}`;
}

function RunOptions({
  run,
  products,
  design,
  dispatch,
}: {
  run: Run;
  products: Product[];
  design: Design;
  dispatch: Dispatch<EditorAction>;
}) {
  const product = products.find((p) => p.id === run.productId);
  if (!product || product.kind !== "linear") return null;
  if (product.style === "wire") {
    return <WireCircuitOptions run={run} products={products} design={design} dispatch={dispatch} />;
  }

  const options = [...new Set([...SPACING_OPTIONS[product.style], product.spacingIn])].sort(
    (a, b) => a - b,
  );
  const effSpacing = run.spacingIn ?? product.spacingIn;
  const effColors = run.colors ?? product.colors;
  const effSize = bulbSizeNameFor(run.bulbScale ?? product.bulbScale ?? 1);

  return (
    <>
      {options.length > 1 ? (
        <div>
          <p className="tp-opt-label">Bulb spacing</p>
          <div className="tp-chip-row">
            {options.map((s) => (
              <button
                key={s}
                type="button"
                className={`tp-spacing-chip ${effSpacing === s ? "on" : ""}`}
                onClick={() =>
                  dispatch({ type: "UPDATE_RUN", id: run.id, patch: { spacingIn: s } })
                }
                title={s === product.spacingIn ? `${s}″ (product default)` : `${s}″`}
              >
                {s}″
              </button>
            ))}
          </div>
        </div>
      ) : null}
      <div>
        <p className="tp-opt-label">Bulb size</p>
        <div className="tp-chip-row">
          {Object.entries(BULB_SIZE_OPTIONS).map(([name, scale]) => (
            <button
              key={`bulb-${name}`}
              type="button"
              className={`tp-spacing-chip ${effSize === name ? "on" : ""}`}
              onClick={() =>
                dispatch({
                  type: "UPDATE_RUN",
                  id: run.id,
                  patch: { bulbScale: scale },
                })
              }
              title={`${name} bulbs`}
            >
              {name}
            </button>
          ))}
        </div>
      </div>
      <div>
        <p className="tp-opt-label">Colors</p>
        <select
          className="est-select"
          value={presetNameFor(effColors)}
          aria-label="Strand colors"
          onChange={(e) =>
            dispatch({
              type: "UPDATE_RUN",
              id: run.id,
              patch: { colors: COLOR_PRESETS[e.target.value] },
            })
          }
        >
          {Object.keys(COLOR_PRESETS).map((name) => (
            <option key={name}>{name}</option>
          ))}
        </select>
      </div>
    </>
  );
}

function WireCircuitOptions({
  run,
  products,
  design,
  dispatch,
}: {
  run: Run;
  products: Product[];
  design: Design;
  dispatch: Dispatch<EditorAction>;
}) {
  const transformers = design.items.filter(
    (item) => products.find((product) => product.id === item.productId)?.style === "transformer",
  );
  const assignedFixtures = design.items.filter((item) => item.circuitId === run.id).length;

  return (
    <div className="tp-wire-options">
      <p className="tp-opt-readout">
        <strong>{run.circuitLabel ?? "Circuit"}</strong> · {assignedFixtures} assigned fixture
        {assignedFixtures === 1 ? "" : "s"}
      </p>
      <label className="tp-field-label">
        <span>Transformer</span>
        <select
          className="est-select"
          value={run.transformerId ?? ""}
          onChange={(event) =>
            dispatch({
              type: "UPDATE_RUN",
              id: run.id,
              patch: { transformerId: event.target.value || undefined },
            })
          }
        >
          <option value="">Unassigned</option>
          {transformers.map((transformer, index) => (
            <option key={transformer.id} value={transformer.id}>
              Transformer {index + 1}
            </option>
          ))}
        </select>
      </label>
      <label className="tp-field-label">
        <span>Wire gauge</span>
        <select
          className="est-select"
          value={run.wireGauge ?? 12}
          onChange={(event) =>
            dispatch({
              type: "UPDATE_RUN",
              id: run.id,
              patch: { wireGauge: Number(event.target.value) as 8 | 10 | 12 | 14 },
            })
          }
        >
          {[
            ...LANDSCAPE_WIRE_GAUGES,
            ...(run.wireGauge === 8 || run.wireGauge === 14 ? [run.wireGauge] : []),
          ].map((gauge) => (
            <option key={gauge} value={gauge}>
              {landscapeWireLabel(gauge)}
            </option>
          ))}
        </select>
      </label>
      <label className="tp-field-label">
        <span>Transformer tap</span>
        <select
          className="est-select"
          value={run.sourceVoltage ?? 12}
          onChange={(event) =>
            dispatch({
              type: "UPDATE_RUN",
              id: run.id,
              patch: { sourceVoltage: Number(event.target.value) },
            })
          }
        >
          {[12, 13, 14, 15].map((voltage) => (
            <option key={voltage} value={voltage}>
              {voltage} V
            </option>
          ))}
        </select>
      </label>
      <p className="tp-opt-readout">
        Select fixtures on the plan to assign them to this circuit. Drag the circuit or its points
        to refine the route.
      </p>
    </div>
  );
}
