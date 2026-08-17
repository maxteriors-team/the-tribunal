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
  productName: "ZDC Color Uplight",
  sku: "FX-ZDC-UP",
  lampLabel: "2700K LED",
  accessoryLabels: ["Long shroud", "Ground stake"],
  target: { field: "landscape", fixtureType: "uplight" },
};

// A path light pools light on the ground instead of throwing a cone, so it has
// no beam to tune — the panel must stay off the rail entirely.
const PATH_LIGHT: Product = {
  ...UPLIGHT,
  id: "path",
  name: "Path light",
  style: "pathlight",
  target: { field: "landscape", fixtureType: "pathlight" },
};

const TRANSFORMER: Product = {
  ...UPLIGHT,
  id: "transformer",
  name: "Transformer",
  style: "transformer",
  sizeFt: 3,
  target: { field: "annotation", annotationType: "transformer" },
};

const WIRE: Product = {
  ...UPLIGHT,
  id: "landscape-wire",
  name: "Wire circuit",
  kind: "linear",
  style: "wire",
  price: 0,
  sizeFt: 0,
  target: { field: "annotation", annotationType: "wire" },
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
  render(<ToolPalette products={products} state={stateWith(item)} dispatch={dispatch} />);
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
  it("keeps the price-book specification and per-fixture marker, size, duplicate, and delete controls", () => {
    const dispatch = renderPalette(placed());

    expect(screen.getByText("ZDC Color Uplight")).toBeInTheDocument();
    expect(screen.getByText("FX-ZDC-UP")).toBeInTheDocument();
    expect(screen.getByText("2700K LED")).toBeInTheDocument();
    expect(screen.getByText("Long shroud, Ground stake")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Set marker color #f2c94c" }));
    expect(dispatch).toHaveBeenCalledWith({
      type: "UPDATE_ITEM",
      id: "item-1",
      patch: { markerColor: "#f2c94c" },
    });

    expect(screen.getByText("100%")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Increase fixture symbol size" }));
    expect(dispatch).toHaveBeenCalledWith({
      type: "UPDATE_ITEM",
      id: "item-1",
      patch: { iconScale: 1.2 },
    });
    expect(screen.getByText(/Beam throw stays unchanged/i)).toBeInTheDocument();
    expect(screen.queryByLabelText(/Beam aim in degrees/i)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Duplicate fixture" }));
    expect(dispatch).toHaveBeenCalledWith({
      type: "ADD_ITEM",
      item: expect.objectContaining({
        id: expect.any(String),
        at: { x: 120, y: 120 },
      }),
    });

    fireEvent.click(screen.getByRole("button", { name: "Delete fixture" }));
    expect(dispatch).toHaveBeenCalledWith({ type: "DELETE_ITEM", id: "item-1" });
  });

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

  it("changes a placed fixture to another icon without moving its anchor", () => {
    const dispatch = renderPalette(placed(), [UPLIGHT, PATH_LIGHT, TRANSFORMER]);

    fireEvent.click(screen.getByTitle("Change selected symbol to Transformer"));

    expect(dispatch).toHaveBeenCalledWith({
      type: "UPDATE_ITEM",
      id: "item-1",
      patch: {
        productId: "transformer",
        sizePx: 120,
        beamAngleDeg: undefined,
        beamRotationDeg: undefined,
        circuitId: undefined,
        catalogItemId: undefined,
        catalogSku: undefined,
        lampCatalogItemId: undefined,
        accessoryCatalogItemIds: undefined,
      },
    });
  });

  it("shows transformer as plan-only equipment with no beam controls", () => {
    renderPalette(placed({ productId: "transformer" }), [UPLIGHT, TRANSFORMER]);

    expect(screen.getByText(/Power equipment symbol/i)).toBeInTheDocument();
    expect(screen.getByTitle("Change selected symbol to Transformer")).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.queryByLabelText(/Beam angle in degrees/i)).toBeNull();
  });
});

describe("landscape wire circuit controls", () => {
  const circuit = {
    id: "circuit-1",
    productId: WIRE.id,
    points: [
      { x: 10, y: 10 },
      { x: 100, y: 100 },
    ],
    circuitLabel: "C1",
    transformerId: "transformer-1",
    wireGauge: 12 as const,
    sourceVoltage: 12,
  };
  const transformer = placed({ id: "transformer-1", productId: TRANSFORMER.id });

  it("assigns a selected fixture to a drawn circuit", () => {
    const dispatch = vi.fn();
    const fixture = placed();
    render(
      <ToolPalette
        products={[UPLIGHT, TRANSFORMER, WIRE]}
        state={{
          ...stateWith(fixture),
          design: { ...EMPTY_DESIGN, runs: [circuit], items: [fixture, transformer] },
        }}
        dispatch={dispatch}
      />,
    );

    fireEvent.change(screen.getByLabelText("Assigned transformer circuit"), {
      target: { value: "circuit-1" },
    });

    expect(dispatch).toHaveBeenCalledWith({
      type: "UPDATE_ITEM",
      id: "item-1",
      patch: { circuitId: "circuit-1" },
    });
  });

  it("edits transformer, wire gauge, and tap for a selected circuit", () => {
    const dispatch = vi.fn();
    render(
      <ToolPalette
        products={[UPLIGHT, TRANSFORMER, WIRE]}
        state={{
          ...stateWith(transformer),
          design: { ...EMPTY_DESIGN, runs: [circuit], items: [transformer] },
          selection: { kind: "run", id: circuit.id },
        }}
        dispatch={dispatch}
      />,
    );

    expect(screen.getByText("C1").closest("p")).toHaveTextContent("C1 · 0 assigned fixtures");
    expect(screen.getByRole("option", { name: "12/2 AWG" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "10/2 AWG" })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "14 AWG" })).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Wire gauge"), { target: { value: "10" } });
    fireEvent.change(screen.getByLabelText("Transformer tap"), { target: { value: "13" } });

    expect(dispatch).toHaveBeenCalledWith({
      type: "UPDATE_RUN",
      id: "circuit-1",
      patch: { wireGauge: 10 },
    });
    expect(dispatch).toHaveBeenCalledWith({
      type: "UPDATE_RUN",
      id: "circuit-1",
      patch: { sourceVoltage: 13 },
    });
  });
});
