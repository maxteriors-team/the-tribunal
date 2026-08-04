/**
 * Beam controls for a selected landscape fixture.
 *
 * The spread is the thing a rep argues about in the driveway, and the palette
 * offers three ways to set it: stock-lamp chips, a continuous slider, and the
 * grip on the cone (covered in `light-canvas.test.tsx`). These tests pin the
 * slider, because it is the only one that can express an angle no lamp ships
 * with — and the only one a rep can hit precisely on a trackpad.
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import {
  MAX_BEAM_ANGLE_DEG,
  MIN_BEAM_ANGLE_DEG,
  type PlacedItem,
  type Product,
} from "@/lib/estimator/types";

import { EMPTY_DESIGN, type EditorState } from "./editor-store";
import { ToolPalette } from "./tool-palette";

const UPLIGHT: Product = {
  id: "uplight",
  name: "Uplight",
  category: "landscape",
  kind: "each",
  price: 411,
  style: "uplight",
  colors: ["#ffd9a0"],
  spacingIn: 24,
  sizeFt: 1,
  target: { field: "landscape", fixtureType: "uplight" },
};

// A path light pools light on the ground instead of throwing a cone, so it has
// no beam to tune — the panel must stay off the rail entirely.
const PATH_LIGHT: Product = {
  ...UPLIGHT,
  id: "path",
  name: "Path light",
  style: "stake",
  target: { field: "landscape", fixtureType: "path" },
};

function stateWith(item: PlacedItem): EditorState {
  return {
    design: { ...EMPTY_DESIGN, items: [item] },
    tool: { type: "select" },
    selection: { kind: "item", id: item.id },
    dusk: 0,
    past: [],
    future: [],
  };
}

function renderPalette(item: PlacedItem, products: Product[] = [UPLIGHT]) {
  const dispatch = vi.fn();
  render(
    <ToolPalette
      products={products}
      state={stateWith(item)}
      dispatch={dispatch}
    />,
  );
  return dispatch;
}

const placed = (over: Partial<PlacedItem> = {}): PlacedItem => ({
  id: "item-1",
  productId: "uplight",
  at: { x: 100, y: 100 },
  sizePx: 40,
  ...over,
});

describe("FixtureOptions beam slider", () => {
  it("starts at the fixture's current spread", () => {
    renderPalette(placed({ beamAngleDeg: 42 }));

    expect(screen.getByLabelText(/Beam angle in degrees/i)).toHaveValue("42");
  });

  it("falls back to the lamp the fixture type ships with", () => {
    // No override yet: an uplight is a 30° spot out of the box.
    renderPalette(placed());

    expect(screen.getByLabelText(/Beam angle in degrees/i)).toHaveValue("30");
  });

  it("sets an angle no preset chip offers", () => {
    // The whole point of the slider: the chips are 10/15/24/36/60, and a rep
    // who wants 42° can't say so by tapping one of them.
    const dispatch = renderPalette(placed({ beamAngleDeg: 30 }));

    fireEvent.change(screen.getByLabelText(/Beam angle in degrees/i), {
      target: { value: "42" },
    });

    expect(dispatch).toHaveBeenCalledWith({
      type: "UPDATE_ITEM",
      id: "item-1",
      patch: { beamAngleDeg: 42 },
    });
  });

  it("clamps a value outside the lamp range", () => {
    // Keyboard input and non-conforming browsers can push a range past its
    // min/max; a 0° cone renders as nothing at all.
    const dispatch = renderPalette(placed());
    const slider = screen.getByLabelText(/Beam angle in degrees/i);

    fireEvent.change(slider, { target: { value: "0" } });
    expect(dispatch).toHaveBeenLastCalledWith(
      expect.objectContaining({ patch: { beamAngleDeg: MIN_BEAM_ANGLE_DEG } }),
    );

    fireEvent.change(slider, { target: { value: "999" } });
    expect(dispatch).toHaveBeenLastCalledWith(
      expect.objectContaining({ patch: { beamAngleDeg: MAX_BEAM_ANGLE_DEG } }),
    );
  });

  it("keeps the chips and the readout in step with the slider", () => {
    renderPalette(placed({ beamAngleDeg: 24 }));

    // Both controls drive one field, so the readout names the nearest lamp.
    expect(screen.getByRole("button", { name: /24 degree beam/i })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByText(/Spot · 24°/)).toBeInTheDocument();
  });

  it("shows no beam control for a fixture that throws no cone", () => {
    renderPalette(placed({ productId: "path" }), [PATH_LIGHT]);

    expect(screen.queryByLabelText(/Beam angle in degrees/i)).toBeNull();
  });
});
