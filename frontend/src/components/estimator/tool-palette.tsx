"use client";

/**
 * Left rail for the light designer: tools, the drawable product palette, and
 * the per-run styling controls (adapted from the in-house light-estimator
 * Toolbar + RunOptions).
 *
 * Products come from the server-derived catalog; their prices are display-only
 * rates. Picking a product arms the draw/place tool; selecting a run on the
 * canvas reveals its spacing/color overrides here.
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
  COLOR_PRESETS,
  SPACING_OPTIONS,
  presetNameFor,
} from "@/lib/estimator/catalog";
import {
  seasonalIconForStyle,
  tintSurface,
} from "@/lib/estimator/seasonal-icons";
import type { Product, Run } from "@/lib/estimator/types";
import { formatCurrency } from "@/lib/utils/number";

import type { EditorAction, EditorState } from "./editor-store";

interface ToolPaletteProps {
  products: Product[];
  state: EditorState;
  dispatch: Dispatch<EditorAction>;
}

function Swatch({ colors }: { colors: string[] }) {
  return (
    <span className="tp-swatch">
      {colors.slice(0, 5).map((c, i) => (
        <i key={`${c}-${i}`} style={{ background: c, boxShadow: `0 0 6px ${c}` }} />
      ))}
    </span>
  );
}

export function ToolPalette({ products, state, dispatch }: ToolPaletteProps) {
  const { tool, selection, design } = state;

  const linear = products.filter((p) => p.kind === "linear");
  const each = products.filter((p) => p.kind === "each");
  const canUndo = state.past.length > 0;
  const canRedo = state.future.length > 0;
  const hasDrawn = design.runs.length > 0 || design.items.length > 0;

  const isActiveProduct = (id: string) =>
    (tool.type === "draw" || tool.type === "place") && tool.productId === id;

  const selectedRun =
    selection?.kind === "run"
      ? design.runs.find((r) => r.id === selection.id)
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
        {linear.length > 0 ? <h2>Draw lights</h2> : null}
        {linear.map((p) => {
          const { Icon, tint } = seasonalIconForStyle(p.style);
          return (
            <button
              key={p.id}
              type="button"
              className={`tp-product ${isActiveProduct(p.id) ? "active" : ""}`}
              onClick={() =>
                dispatch({ type: "SET_TOOL", tool: { type: "draw", productId: p.id } })
              }
              title={`Trace along the photo — ${formatCurrency(p.price)}/ft`}
            >
              <span
                className="tp-cat-icon"
                style={{ color: tint, background: tintSurface(tint) }}
                aria-hidden="true"
              >
                <Icon className="tp-glyph" />
              </span>
              <Swatch colors={p.colors} />
              <span className="tp-product-name">{p.name}</span>
              <span className="tp-product-price">{formatCurrency(p.price)}/ft</span>
            </button>
          );
        })}

        {each.length > 0 ? <h2 className="tp-mt">Place decor</h2> : null}
        {each.map((p) => {
          const { Icon, tint } = seasonalIconForStyle(p.style);
          return (
            <button
              key={p.id}
              type="button"
              className={`tp-product ${isActiveProduct(p.id) ? "active" : ""}`}
              onClick={() =>
                dispatch({ type: "SET_TOOL", tool: { type: "place", productId: p.id } })
              }
              title={`Click the photo to place — ${formatCurrency(p.price)} each`}
            >
              <span
                className="tp-cat-icon"
                style={{ color: tint, background: tintSurface(tint) }}
                aria-hidden="true"
              >
                <Icon className="tp-glyph" />
              </span>
              <Swatch colors={p.colors} />
              <span className="tp-product-name">{p.name}</span>
              <span className="tp-product-price">{formatCurrency(p.price)}</span>
            </button>
          );
        })}

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
