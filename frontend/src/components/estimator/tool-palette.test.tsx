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

import { calculateWrap } from "@/lib/estimator/tree-wrap";
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

const STRAND: Product = {
  ...WIRE,
  id: "roofline-c9-warm",
  name: "C9 Roofline",
  category: "seasonal",
  style: "c9",
  price: 6,
  spacingIn: 12,
  target: { field: "roofline" },
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

describe("photo measurement scales", () => {
  const primary = { a: { x: 0, y: 0 }, b: { x: 100, y: 0 }, feet: 10 };
  const secondary = { a: { x: 0, y: 20 }, b: { x: 200, y: 20 }, feet: 10 };

  it("offers Scale 2 setup only after Scale 1 exists", () => {
    const dispatch = vi.fn();
    render(
      <ToolPalette
        products={[STRAND]}
        state={{
          ...stateWith(placed()),
          design: { ...EMPTY_DESIGN, calibration: primary },
          selection: null,
        }}
        dispatch={dispatch}
        enableSecondaryScale
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Add Scale 2" }));
    expect(dispatch).toHaveBeenCalledWith({
      type: "SET_TOOL",
      tool: { type: "calibrate", scaleSlot: 2 },
    });
  });

  it("assigns the selected strand to Scale 2", () => {
    const dispatch = vi.fn();
    const run = {
      id: "run-1",
      productId: STRAND.id,
      points: [
        { x: 0, y: 0 },
        { x: 400, y: 0 },
      ],
    };
    render(
      <ToolPalette
        products={[STRAND]}
        state={{
          ...stateWith(placed()),
          design: {
            ...EMPTY_DESIGN,
            calibration: primary,
            secondaryCalibration: secondary,
            runs: [run],
          },
          selection: { kind: "run", id: run.id },
        }}
        dispatch={dispatch}
        enableSecondaryScale
      />,
    );

    expect(screen.getByRole("button", { name: "Scale 1" })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByRole("button", { name: "Scale 2" }));
    expect(dispatch).toHaveBeenCalledWith({
      type: "UPDATE_RUN",
      id: run.id,
      patch: { scaleSlot: 2 },
    });
    expect(screen.getByText(/Split runs at every corner or depth change/i)).toBeInTheDocument();
  });
});

describe("FixtureOptions beam slider", () => {
  it("keeps the price-book specification and per-fixture marker, size, duplicate, and delete controls", () => {
    const dispatch = renderPalette(placed());

    expect(screen.getByText("ZDC Color Uplight")).toBeInTheDocument();
    expect(screen.getByText("FX-ZDC-UP")).toBeInTheDocument();
    expect(screen.getByText("2700K LED")).toBeInTheDocument();
    expect(screen.getByText("Long shroud, Ground stake")).toBeInTheDocument();

    expect(screen.getAllByRole("radio")).toHaveLength(16);
    fireEvent.click(screen.getByRole("radio", { name: "Yellow" }));
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
    expect(screen.getByLabelText(/Beam direction in degrees/i)).toHaveValue("0");

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

  it("changes beam direction without touching its spread", () => {
    const dispatch = renderPalette(placed({ beamAngleDeg: 24 }));

    fireEvent.change(screen.getByLabelText(/Beam direction in degrees/i), {
      target: { value: "-35" },
    });

    expect(dispatch).toHaveBeenCalledWith({
      type: "UPDATE_ITEM",
      id: "item-1",
      patch: { beamRotationDeg: -35 },
    });
  });

  it("names the direction and resets it to the fixture's natural axis", () => {
    const dispatch = renderPalette(placed({ beamRotationDeg: 90 }));

    expect(screen.getByText(/90° clockwise · pointing right/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Reset" }));
    expect(dispatch).toHaveBeenCalledWith({
      type: "UPDATE_ITEM",
      id: "item-1",
      patch: { beamRotationDeg: 0 },
    });
  });

  it("uses a downlight's natural down-facing axis", () => {
    const downlight: Product = { ...UPLIGHT, id: "down", style: "downlight" };
    renderPalette(placed({ productId: "down" }), [downlight]);

    expect(screen.getByText(/Straight down · pointing down/i)).toBeInTheDocument();
  });

  it("shows no beam control for a fixture that throws no cone", () => {
    renderPalette(placed({ productId: "path" }), [PATH_LIGHT]);

    expect(screen.queryByLabelText(/Beam angle in degrees/i)).toBeNull();
    expect(screen.queryByLabelText(/Beam direction in degrees/i)).toBeNull();
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

/**
 * Exact tree measuring.
 *
 * A rep can price a tree two ways: the size band the price book quotes, or the
 * real wrap they measured. These pin the switch between the two, because the
 * whole point of the feature is that a tree is billed once, on one basis, and
 * the rep can always see which.
 */
const TREE: Product = {
  id: "cat-trees-medium",
  name: "Front spruce",
  category: "seasonal",
  kind: "each",
  price: 250,
  style: "treewrap",
  colors: ["#ffd98a"],
  spacingIn: 0,
  sizeFt: 12,
  target: { field: "christmas", category: "trees", option: "medium" },
};

const WREATH: Product = {
  ...TREE,
  id: "cat-wreaths-standard",
  name: "Wreath",
  style: "wreath",
  target: { field: "christmas", category: "wreaths", option: "standard" },
};

const tree = (over: Partial<PlacedItem> = {}): PlacedItem => ({
  id: "tree-1",
  productId: TREE.id,
  at: { x: 100, y: 100 },
  sizePx: 120,
  ...over,
});

const MEASURED = {
  shape: "evergreen",
  lightType: "mini",
  heightFt: 20,
  radiusFt: 6,
  rowSpacingIn: 12,
  feetPerUnit: 25,
  pricingMode: "unit",
  unitPrice: 39.99,
} as const;

function renderTree(item: PlacedItem, photoWidth?: number) {
  const dispatch = vi.fn();
  render(
    <ToolPalette
      products={[TREE, WREATH]}
      state={stateWith(item)}
      dispatch={dispatch}
      photoWidth={photoWidth}
    />,
  );
  return dispatch;
}

describe("exact tree measuring", () => {
  it("offers measuring on an unmeasured tree, still on band pricing", () => {
    const dispatch = renderTree(tree());
    expect(screen.getByText(/Priced by size band/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Measure exactly/ }));
    const call = dispatch.mock.calls[0][0];
    expect(call.type).toBe("UPDATE_ITEM");
    expect(call.patch.wrap).toMatchObject({ shape: "evergreen", rowSpacingIn: 12 });
  });

  it("never offers measuring on decor that is counted, not wrapped", () => {
    renderTree(tree({ productId: WREATH.id }));
    expect(screen.queryByRole("button", { name: /Measure exactly/ })).not.toBeInTheDocument();
  });

  it("shows the wrap footage, rows and strands once measured", () => {
    renderTree(tree({ wrap: MEASURED }));
    const readout = screen.getByText(/of wrap/).closest("div");
    expect(readout).toHaveTextContent("379 ft");
    expect(readout).toHaveTextContent("16 strands");
    expect(readout).toHaveTextContent("$639.84");
    // The row count reads off the drawing, which is where it means something.
    expect(screen.getByText("20 rows")).toBeInTheDocument();
    expect(
      screen.getByRole("img", { name: /Evergreen tree, 20 wrap rows/ }),
    ).toBeInTheDocument();
  });

  it("says the tree is unpriced rather than showing a zero", () => {
    renderTree(tree({ wrap: { ...MEASURED, unitPrice: undefined } }));
    // And says what the customer is charged meanwhile, so a rep who walks away
    // mid-measurement is not left thinking the tree is now free.
    expect(screen.getByText(/Enter a price/)).toBeInTheDocument();
    expect(screen.getByText(/stays on size-band pricing/)).toBeInTheDocument();
    expect(screen.queryByText(/\$0/)).not.toBeInTheDocument();
  });

  it("warns when a measurement is too big to bill as one line", () => {
    renderTree(
      tree({
        wrap: {
          ...MEASURED,
          shape: "branch",
          branchWidthIn: 6,
          branchCount: 500,
          rowSpacingIn: 3,
          pricingMode: "foot",
          unitPrice: 2,
        },
      }),
    );
    expect(screen.getByText(/Too big for one line/)).toBeInTheDocument();
  });

  it("edits a dimension without discarding the rest of the measurement", () => {
    const dispatch = renderTree(tree({ wrap: MEASURED }));
    fireEvent.change(screen.getByLabelText("Radius in feet"), { target: { value: "8" } });
    expect(dispatch).toHaveBeenCalledWith({
      type: "UPDATE_ITEM",
      id: "tree-1",
      patch: { wrap: { ...MEASURED, radiusFt: 8 } },
    });
  });

  it("clears a field instead of pricing a half-typed number as zero", () => {
    const dispatch = renderTree(tree({ wrap: MEASURED }));
    fireEvent.change(screen.getByLabelText("Radius in feet"), { target: { value: "" } });
    expect(dispatch.mock.calls[0][0].patch.wrap.radiusFt).toBeUndefined();
  });

  it("only offers whole limbs, which is all the math accepts", () => {
    renderTree(tree({ wrap: { ...MEASURED, shape: "branch", branchWidthIn: 4, branchCount: 12 } }));
    expect(screen.getByLabelText("Branches")).toHaveAttribute("step", "1");
    // Dimensions stay continuous — a 6.5 ft tree is real, 2.5 limbs is not.
    expect(screen.getByLabelText("Lit height in feet")).toHaveAttribute("step", "any");
  });

  it("spells out each field's unit for a screen reader", () => {
    // The visible "ft" chip is decorative; alone it would leave a non-sighted
    // rep guessing whether a field wants feet or inches.
    renderTree(tree({ wrap: MEASURED }));
    expect(screen.getByLabelText("Lit height in feet")).toBeInTheDocument();
    expect(screen.getByLabelText("Row gap in inches")).toBeInTheDocument();
    expect(screen.getByLabelText("Each in dollars")).toBeInTheDocument();
  });

  it("asks only for the dimensions the chosen shape actually uses", () => {
    renderTree(tree({ wrap: { ...MEASURED, shape: "bush", widthFt: 8, depthFt: 4 } }));
    expect(screen.getByLabelText("Width in feet")).toBeInTheDocument();
    expect(screen.getByLabelText("Depth in feet")).toBeInTheDocument();
    expect(screen.queryByLabelText("Radius in feet")).not.toBeInTheDocument();
  });

  it("picks a shape from the pictures, showing which one is chosen", () => {
    const dispatch = renderTree(tree({ wrap: MEASURED }));
    const evergreen = screen.getByRole("button", { name: "Evergreen tree" });
    expect(evergreen).toHaveAttribute("aria-pressed", "true");

    const bush = screen.getByRole("button", { name: "Bush" });
    expect(bush).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(bush);
    expect(dispatch.mock.calls[0][0].patch.wrap).toMatchObject({ shape: "bush" });
  });

  it("keeps the tree priced when the rep changes its shape", () => {
    // "Actually that one's more of a bush" is said mid-conversation, in front
    // of the customer. If the new shape arrived with empty dimensions, the
    // price would vanish and their photo would drop back to a generic cone.
    const dispatch = renderTree(tree({ wrap: MEASURED }));
    fireEvent.click(screen.getByRole("button", { name: "Bush" }));

    const next = dispatch.mock.calls[0][0].patch.wrap;
    // The 6 ft canopy radius carries over as a 12 ft footprint.
    expect(next).toMatchObject({ shape: "bush", widthFt: 12, depthFt: 12 });
    expect(calculateWrap(next)?.price).toBeGreaterThan(0);
  });

  it("moves a hand-wrapped shape off bulb cord it cannot be installed with", () => {
    const dispatch = renderTree(tree({ wrap: { ...MEASURED, lightType: "c9", bulbSpacingIn: 12 } }));
    fireEvent.click(screen.getByRole("button", { name: "Bush" }));
    expect(dispatch.mock.calls[0][0].patch.wrap).toMatchObject({
      shape: "bush",
      lightType: "mini",
    });
  });

  it("switches the charge basis without a dropdown, and shows which is on", () => {
    const dispatch = renderTree(tree({ wrap: MEASURED }));
    // The selected chip must carry the shared `.on` class, or it looks unset:
    // an invented class name styles nothing and silently loses the highlight.
    const perStrand = screen.getByRole("button", { name: "Per strand" });
    expect(perStrand).toHaveAttribute("aria-pressed", "true");
    expect(perStrand.className).toContain("on");

    const perFoot = screen.getByRole("button", { name: "Per foot" });
    expect(perFoot).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(perFoot);
    expect(dispatch.mock.calls[0][0].patch.wrap.pricingMode).toBe("foot");
  });

  it("offers the drawn height from the photo scale, and only when it differs", () => {
    // 100px == 10ft, so a 120px tree reads 12ft on the photo.
    const dispatch = vi.fn();
    const state = stateWith(tree({ wrap: MEASURED }));
    render(
      <ToolPalette
        products={[TREE]}
        state={{
          ...state,
          design: {
            ...state.design,
            calibration: { a: { x: 0, y: 0 }, b: { x: 100, y: 0 }, feet: 10 },
          },
        }}
        dispatch={dispatch}
        photoWidth={1200}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /Photo says 12 ft tall/ }));
    expect(dispatch.mock.calls[0][0].patch.wrap.heightFt).toBe(12);
  });

  it("puts a tree back on band pricing without a trace", () => {
    const dispatch = renderTree(tree({ wrap: MEASURED }));
    fireEvent.click(screen.getByRole("button", { name: /Use size band instead/ }));
    expect(dispatch).toHaveBeenCalledWith({
      type: "UPDATE_ITEM",
      id: "tree-1",
      patch: { wrap: undefined },
    });
  });
});
