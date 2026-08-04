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
import {
  MousePointer2,
  Redo2,
  Ruler,
  Trash2,
  Undo2,
} from "lucide-react";
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
import {
  seasonalIconForStyle,
  tintSurface,
} from "@/lib/estimator/seasonal-icons";
import { beamAngleFor } from "@/lib/estimator/types";
import type { PlacedItem, Product, Run } from "@/lib/estimator/types";
import { formatCurrency } from "@/lib/utils/number";

import type { EditorAction, EditorState } from "./editor-store";

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
    selection?.kind === "run"
      ? design.runs.find((r) => r.id === selection.id)
      : undefined;
  const selectedItem =
    selection?.kind === "item"
      ? design.items.find((i) => i.id === selection.id)
      : undefined;
  const selectedItemProduct = selectedItem
    ? products.find((p) => p.id === selectedItem.productId)
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
            <h2 className={landscape.length > 0 ? "tp-mt" : undefined}>
              Draw lights
            </h2>
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
            <h2 className="tp-mt">Selected strand</h2>
            <RunOptions
              run={selectedRun}
              products={products}
              dispatch={dispatch}
            />
          </div>
        ) : null}

        {selectedItem && selectedItemProduct ? (
          <FixtureOptions
            item={selectedItem}
            product={selectedItemProduct}
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
  const price = linear
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
        linear
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
 * Beam controls for the selected landscape fixture.
 *
 * The spread is what a rep argues about standing in the driveway — "that's
 * washing the whole wall, I want it grazing the column" — so it is editable per
 * fixture here and by dragging the gold grip on the cone's edge. Renders nothing
 * for a fixture that throws no cone (a path light pools on the ground) or for
 * placed holiday decor, which has no beam at all.
 */
function FixtureOptions({
  item,
  product,
  dispatch,
}: {
  item: PlacedItem;
  product: Product;
  dispatch: Dispatch<EditorAction>;
}) {
  const angle = beamAngleFor(product.style, item.beamAngleDeg);
  if (angle === null) return null;

  return (
    <div className="tp-run-options">
      <h2 className="tp-mt">Selected fixture</h2>
      <div>
        <p className="tp-opt-label">Beam angle</p>
        <div className="tp-chip-row">
          {BEAM_ANGLE_OPTIONS.map((option) => (
            <button
              key={option.deg}
              type="button"
              className={`tp-spacing-chip ${
                Math.round(angle) === option.deg ? "on" : ""
              }`}
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
        <p className="tp-opt-readout">
          {beamAngleNameFor(angle)} · {Math.round(angle)}&deg; — drag the gold grip
          on the photo to fine-tune.
        </p>
      </div>
    </div>
  );
}

function RunOptions({
  run,
  products,
  dispatch,
}: {
  run: Run;
  products: Product[];
  dispatch: Dispatch<EditorAction>;
}) {
  const product = products.find((p) => p.id === run.productId);
  if (!product || product.kind !== "linear") return null;

  const options = [
    ...new Set([...SPACING_OPTIONS[product.style], product.spacingIn]),
  ].sort((a, b) => a - b);
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
