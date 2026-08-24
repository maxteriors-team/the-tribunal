import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import React from "react";
import { describe, expect, it, vi, beforeEach } from "vitest";

import { loadImage } from "@/lib/estimator/photo";
import { beamAngleAt, beamHandlePos, resizeHandlePos } from "@/lib/estimator/render";
import type { PhotoInfo, Product } from "@/lib/estimator/types";

import {
  editorReducer,
  initialEditorState,
  type EditorAction,
  type EditorState,
} from "./editor-store";
import { deterministicPhotoFit, LightCanvas } from "./light-canvas";

// The glow engine is exercised in render.test.ts; jsdom has no 2D context.
vi.mock("@/lib/estimator/render", () => ({
  drawScene: vi.fn(),
  itemHit: vi.fn(() => false),
  planImageHit: vi.fn(() => false),
  planImageResizeHandlePos: vi.fn(() => ({ x: 0, y: 0 })),
  resizeHandlePos: vi.fn(() => ({ x: 0, y: 0 })),
  beamHandlePos: vi.fn(() => null),
  beamAngleAt: vi.fn(() => 30),
  DEFAULT_DUSK: 0.52,
  MAX_DUSK: 0.92,
}));

vi.mock("@/lib/estimator/photo", () => ({
  loadImage: vi.fn(() => new Promise(() => undefined)),
  fileToPhoto: vi.fn().mockResolvedValue({
    dataUrl: "data:image/png;base64,PLAN",
    width: 200,
    height: 100,
  }),
}));

vi.mock("@/lib/estimator/image-resize", () => ({
  fileToResizedDataUrl: vi.fn().mockResolvedValue("data:image/jpeg;base64,RESIZED"),
}));

const PHOTO: PhotoInfo = {
  dataUrl: "data:image/png;base64,AAAA",
  width: 1000,
  height: 800,
};

beforeEach(() => {
  vi.mocked(loadImage).mockReset();
  vi.mocked(loadImage).mockImplementation(() => new Promise(() => undefined));
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);
});

const UPLIGHT: Product = {
  id: "fixture-uplight",
  name: "Uplight",
  category: "landscape",
  kind: "each",
  price: 785,
  style: "uplight",
  colors: ["#ffd98a"],
  spacingIn: 0,
  sizeFt: 14,
  sku: "best-zdc-up",
  target: { field: "landscape", fixtureType: "uplight" },
};

const BISTRO: Product = {
  id: "bistro-temporary-layout",
  name: "Temporary Bistro Lights",
  category: "landscape",
  kind: "linear",
  price: 0,
  style: "bistro",
  colors: ["#ffd98a"],
  spacingIn: 24,
  sizeFt: 0,
  sku: null,
  target: { field: "bistro", installation: "temporary" },
};

/**
 * Mount the canvas with the place tool armed, with the canvas element mapped
 * 1:1 onto the photo (identity transform) so a client coordinate is also an
 * image coordinate — which makes "outside the photo" easy to express.
 */
function setup(placementMarkerColor?: string) {
  let state: EditorState = {
    ...initialEditorState(),
    tool: { type: "place", productId: UPLIGHT.id },
  };
  const dispatch = vi.fn((action: EditorAction) => {
    state = editorReducer(state, action);
  });
  const { container, rerender } = render(
    <LightCanvas
      photo={PHOTO}
      products={[UPLIGHT]}
      state={state}
      dispatch={dispatch}
      placementMarkerColor={placementMarkerColor}
    />,
  );
  const canvas = container.querySelector("canvas")!;
  // Identity mapping: canvas origin at (0,0), one client px per image px.
  vi.spyOn(canvas, "getBoundingClientRect").mockReturnValue({
    left: 0,
    top: 0,
    width: PHOTO.width,
    height: PHOTO.height,
    right: PHOTO.width,
    bottom: PHOTO.height,
    x: 0,
    y: 0,
    toJSON: () => ({}),
  } as DOMRect);
  canvas.setPointerCapture = vi.fn();
  canvas.releasePointerCapture = vi.fn();

  const clickAt = (x: number, y: number) => {
    fireEvent.pointerDown(canvas, { clientX: x, clientY: y, button: 0, pointerId: 1 });
    fireEvent.pointerUp(canvas, { clientX: x, clientY: y, button: 0, pointerId: 1 });
  };
  const placed = () => dispatch.mock.calls.filter(([a]) => a.type === "ADD_ITEM").length;

  return { clickAt, placed, dispatch, rerender };
}

function setupAerialTool(tool: EditorState["tool"]) {
  const dispatch = vi.fn();
  const { container } = render(
    <LightCanvas
      photo={PHOTO}
      products={[BISTRO]}
      state={{ ...initialEditorState(), tool }}
      dispatch={dispatch}
      perspective="aerial"
    />,
  );
  const canvas = container.querySelector("canvas")!;
  vi.spyOn(canvas, "getBoundingClientRect").mockReturnValue({
    left: 0,
    top: 0,
    width: PHOTO.width,
    height: PHOTO.height,
    right: PHOTO.width,
    bottom: PHOTO.height,
    x: 0,
    y: 0,
    toJSON: () => ({}),
  } as DOMRect);
  canvas.setPointerCapture = vi.fn();
  canvas.releasePointerCapture = vi.fn();
  return { canvas, dispatch };
}

describe("LightCanvas — aerial plan semantics", () => {
  it("labels the landscape canvas and scale controls as top-down aerial", async () => {
    render(
      <LightCanvas
        photo={PHOTO}
        products={[UPLIGHT]}
        state={initialEditorState()}
        dispatch={vi.fn()}
        perspective="aerial"
      />,
    );

    const canvas = await screen.findByLabelText("Top-down aerial lighting plan canvas");
    expect(canvas).toHaveAttribute("data-viewport-policy", "locked");
    expect(
      screen.queryByTitle("Set the aerial plan scale from a known top-down distance"),
    ).not.toBeInTheDocument();
    expect(screen.queryByTitle("Show the base aerial without lighting")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add detail photo" })).not.toBeInTheDocument();
  });

  it("lets a phone pan the zoomed sheet without activating canvas edits", () => {
    const { canvas } = setupAerialTool({ type: "pan" });

    expect(canvas).toHaveStyle({ cursor: "grab", touchAction: "pan-x pan-y" });
    fireEvent.pointerDown(canvas, {
      pointerId: 1,
      pointerType: "touch",
      clientX: 300,
      clientY: 300,
      button: 0,
    });
    expect(canvas.setPointerCapture).not.toHaveBeenCalled();
  });

  it("computes a deterministic centered contain fit", () => {
    expect(deterministicPhotoFit(500, 800, 1000, 800)).toEqual({
      scale: 0.48,
      ox: 10,
      oy: 208,
    });
  });

  it("refits a locked aerial after resize without letting gestures drift the drawing", async () => {
    let notifyResize: (() => void) | null = null;
    class ControlledResizeObserver {
      constructor(callback: ResizeObserverCallback) {
        notifyResize = () => callback([], this as unknown as ResizeObserver);
      }
      observe = vi.fn();
      unobserve = vi.fn();
      disconnect = vi.fn();
    }
    vi.stubGlobal("ResizeObserver", ControlledResizeObserver);

    try {
      vi.mocked(loadImage).mockResolvedValueOnce({
        naturalWidth: 1000,
        naturalHeight: 800,
      } as HTMLImageElement);
      let width = 1000;
      let height = 800;
      const dispatch = vi.fn();
      const state: EditorState = {
        ...initialEditorState(),
        tool: { type: "place", productId: UPLIGHT.id },
      };
      const { container } = render(
        <LightCanvas
          photo={PHOTO}
          products={[UPLIGHT]}
          state={state}
          dispatch={dispatch}
          perspective="aerial"
        />,
      );
      const wrapper = container.querySelector(".lc-wrap") as HTMLDivElement;
      const canvas = container.querySelector("canvas")!;
      const rect = () =>
        ({
          left: 0,
          top: 0,
          width,
          height,
          right: width,
          bottom: height,
          x: 0,
          y: 0,
          toJSON: () => ({}),
        }) as DOMRect;
      vi.spyOn(wrapper, "getBoundingClientRect").mockImplementation(rect);
      vi.spyOn(canvas, "getBoundingClientRect").mockImplementation(rect);
      canvas.setPointerCapture = vi.fn();
      canvas.releasePointerCapture = vi.fn();

      await waitFor(() => expect(Number(canvas.dataset.viewScale)).toBeCloseTo(0.96));
      expect(canvas.dataset.viewportPolicy).toBe("locked");
      expect(Number(canvas.dataset.viewOriginX)).toBeCloseTo(20);
      expect(Number(canvas.dataset.viewOriginY)).toBeCloseTo(16);

      fireEvent.pointerDown(canvas, { pointerId: 1, clientX: 500, clientY: 400, button: 0 });
      fireEvent.pointerUp(canvas, { pointerId: 1, clientX: 500, clientY: 400, button: 0 });

      const viewBeforeGestures = {
        scale: canvas.dataset.viewScale,
        x: canvas.dataset.viewOriginX,
        y: canvas.dataset.viewOriginY,
      };
      const wheel = new WheelEvent("wheel", { deltaX: 80, deltaY: 120, cancelable: true });
      canvas.dispatchEvent(wheel);
      expect(wheel.defaultPrevented).toBe(false);

      fireEvent.pointerDown(canvas, { pointerId: 2, clientX: 450, clientY: 400, button: 1 });
      fireEvent.pointerMove(canvas, { pointerId: 2, clientX: 600, clientY: 520, button: 1 });
      fireEvent.pointerUp(canvas, { pointerId: 2, clientX: 600, clientY: 520, button: 1 });

      const touch = (pointerId: number, clientX: number, clientY: number) => ({
        pointerId,
        clientX,
        clientY,
        button: 0,
        pointerType: "touch",
      });
      fireEvent.pointerDown(canvas, touch(3, 400, 400));
      fireEvent.pointerDown(canvas, touch(4, 500, 400));
      fireEvent.pointerMove(canvas, touch(3, 300, 350));
      fireEvent.pointerMove(canvas, touch(4, 600, 450));
      fireEvent.pointerUp(canvas, touch(3, 300, 350));
      fireEvent.pointerUp(canvas, touch(4, 600, 450));

      expect({
        scale: canvas.dataset.viewScale,
        x: canvas.dataset.viewOriginX,
        y: canvas.dataset.viewOriginY,
      }).toEqual(viewBeforeGestures);

      width = 500;
      height = 800;
      act(() => notifyResize?.());
      await waitFor(() => expect(Number(canvas.dataset.viewScale)).toBeCloseTo(0.48));
      expect(Number(canvas.dataset.viewOriginX)).toBeCloseTo(10);
      expect(Number(canvas.dataset.viewOriginY)).toBeCloseTo(208);

      fireEvent.pointerDown(canvas, { pointerId: 5, clientX: 250, clientY: 400, button: 0 });
      fireEvent.pointerUp(canvas, { pointerId: 5, clientX: 250, clientY: 400, button: 0 });
      const placements = dispatch.mock.calls
        .map(([action]) => action)
        .filter((action) => action.type === "ADD_ITEM");
      expect(placements).toHaveLength(2);
      expect(placements.map((action) => action.item.at)).toEqual([
        { x: 500, y: 400 },
        { x: 500, y: 400 },
      ]);
    } finally {
      vi.unstubAllGlobals();
    }
  });
});

describe("LightCanvas — geometry stays on the photo", () => {
  beforeEach(() => vi.clearAllMocks());

  it("places a fixture where the rep clicks on the photo", () => {
    const { clickAt, placed } = setup();
    clickAt(500, 400);
    expect(placed()).toBe(1);
  });

  it("applies the shared toolbar marker color to a newly placed fixture", () => {
    const { clickAt, dispatch } = setup("#2f80ed");
    clickAt(500, 400);
    expect(dispatch).toHaveBeenCalledWith(
      expect.objectContaining({
        type: "ADD_ITEM",
        item: expect.objectContaining({ markerColor: "#2f80ed" }),
      }),
    );
  });

  it("ignores clicks in the letterbox around the photo", () => {
    // The canvas is bigger than the photo while panning/zooming. A fixture
    // placed out there renders nowhere but still counts toward the quote and
    // the crew's parts list — the customer would be billed for hardware they
    // never see. So creation is refused off-photo.
    const { clickAt, placed } = setup();
    clickAt(500, 900); // below the photo
    clickAt(1200, 400); // right of the photo
    clickAt(-40, 400); // left of the photo
    clickAt(500, -30); // above the photo
    expect(placed()).toBe(0);
  });

  it("still accepts a click exactly on the photo's edge", () => {
    const { clickAt, placed } = setup();
    clickAt(0, 0);
    clickAt(PHOTO.width, PHOTO.height);
    expect(placed()).toBe(2);
  });
});

describe("LightCanvas — highlights", () => {
  beforeEach(() => vi.clearAllMocks());

  it("commits a freehand highlight after a drag", () => {
    const dispatch = vi.fn();
    const state = { ...initialEditorState(), tool: { type: "highlight" as const } };
    const { container } = render(
      <LightCanvas photo={PHOTO} products={[UPLIGHT]} state={state} dispatch={dispatch} />,
    );
    const canvas = container.querySelector("canvas")!;
    vi.spyOn(canvas, "getBoundingClientRect").mockReturnValue({
      left: 0,
      top: 0,
      width: PHOTO.width,
      height: PHOTO.height,
      right: PHOTO.width,
      bottom: PHOTO.height,
      x: 0,
      y: 0,
      toJSON: () => ({}),
    } as DOMRect);
    canvas.setPointerCapture = vi.fn();
    canvas.releasePointerCapture = vi.fn();

    fireEvent.pointerDown(canvas, { pointerId: 12, clientX: 180, clientY: 170 });
    fireEvent.pointerMove(canvas, { pointerId: 12, clientX: 230, clientY: 205 });
    fireEvent.pointerMove(canvas, { pointerId: 12, clientX: 280, clientY: 235 });
    fireEvent.pointerUp(canvas, { pointerId: 12, clientX: 280, clientY: 235 });

    expect(dispatch).toHaveBeenCalledWith(
      expect.objectContaining({
        type: "ADD_HIGHLIGHT",
        highlight: expect.objectContaining({
          color: "rgba(255, 226, 74, 0.55)",
          widthPx: 34,
        }),
      }),
    );
  });
});

/**
 * Harness that keeps real reducer state, so a gesture's effect on the view is
 * observable through the rendered zoom label rather than by reaching inside.
 */
function setupCanvas() {
  const seen: EditorAction[] = [];
  function Harness() {
    const [state, rawDispatch] = React.useReducer(editorReducer, undefined, () => ({
      ...initialEditorState(),
      tool: { type: "place" as const, productId: UPLIGHT.id },
    }));
    const dispatch = (action: EditorAction) => {
      seen.push(action);
      rawDispatch(action);
    };
    return <LightCanvas photo={PHOTO} products={[UPLIGHT]} state={state} dispatch={dispatch} />;
  }
  const { container } = render(<Harness />);
  const canvas = container.querySelector("canvas")!;
  vi.spyOn(canvas, "getBoundingClientRect").mockReturnValue({
    left: 0,
    top: 0,
    width: PHOTO.width,
    height: PHOTO.height,
    right: PHOTO.width,
    bottom: PHOTO.height,
    x: 0,
    y: 0,
    toJSON: () => ({}),
  } as DOMRect);
  canvas.setPointerCapture = vi.fn();
  canvas.releasePointerCapture = vi.fn();

  const zoom = () => {
    const label = container.querySelector(".lc-zoom-label")?.textContent ?? "";
    return Number(label.replace("%", ""));
  };
  const placed = () => seen.filter((a) => a.type === "ADD_ITEM").length;
  return { canvas, container, zoom, placed, seen };
}

describe("LightCanvas — plan images", () => {
  beforeEach(() => vi.clearAllMocks());

  it("drops an image at the pointer and adds a movable plan inset", async () => {
    const { container, seen } = setupCanvas();
    const wrapper = container.querySelector(".lc-wrap")!;
    const file = new File(["image"], "pool-detail.png", { type: "image/png" });

    fireEvent.drop(wrapper, {
      clientX: 500,
      clientY: 400,
      dataTransfer: { files: [file], types: ["Files"] },
    });

    await waitFor(() =>
      expect(seen.find((action) => action.type === "ADD_PLAN_IMAGE")).toMatchObject({
        image: {
          name: "pool-detail.png",
          dataUrl: "data:image/png;base64,PLAN",
          at: { x: 500, y: 400 },
          widthPx: 200,
          heightPx: 100,
        },
      }),
    );
  });

  it("moves and proportionally resizes a selected image from the keyboard", async () => {
    const { container, seen } = setupCanvas();
    const wrapper = container.querySelector(".lc-wrap")!;
    const file = new File(["image"], "pool-detail.png", { type: "image/png" });
    fireEvent.drop(wrapper, {
      clientX: 500,
      clientY: 400,
      dataTransfer: { files: [file], types: ["Files"] },
    });
    await waitFor(() => expect(seen.some((action) => action.type === "ADD_PLAN_IMAGE")).toBe(true));

    fireEvent.keyDown(window, { key: "ArrowRight" });
    fireEvent.keyDown(window, { key: "ArrowRight", altKey: true, shiftKey: true });

    await waitFor(() =>
      expect(seen.filter((action) => action.type === "UPDATE_PLAN_IMAGE")).toEqual(
        expect.arrayContaining([
          expect.objectContaining({ patch: { at: { x: 501, y: 400 } } }),
          expect.objectContaining({ patch: { widthPx: 210, heightPx: 105 } }),
        ]),
      ),
    );
  });

  it("offers a keyboard/touch-safe file picker alternative to drag and drop", async () => {
    const { container, seen } = setupCanvas();
    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(["image"], "detail.webp", { type: "image/webp" });

    fireEvent.change(input, { target: { files: [file] } });

    await waitFor(() => expect(seen.some((action) => action.type === "ADD_PLAN_IMAGE")).toBe(true));
  });

  it("compresses oversized plan images before they enter autosave", async () => {
    vi.mocked(loadImage)
      .mockImplementationOnce(() => new Promise(() => undefined))
      .mockResolvedValueOnce({ naturalWidth: 1600, naturalHeight: 900 } as HTMLImageElement);
    const { container, seen } = setupCanvas();
    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File([new Uint8Array(2 * 1024 * 1024 + 1)], "large-photo.png", {
      type: "image/png",
    });

    fireEvent.change(input, { target: { files: [file] } });

    await waitFor(() => expect(seen.some((action) => action.type === "ADD_PLAN_IMAGE")).toBe(true));
    expect(container.querySelector('[role="alert"]')).toBeNull();
  });
});

describe("LightCanvas — touch gestures", () => {
  beforeEach(() => vi.clearAllMocks());

  const touch = (id: number, x: number, y: number) => ({
    pointerId: id,
    clientX: x,
    clientY: y,
    button: 0,
    pointerType: "touch",
  });

  it("pinching outward zooms in — an iPad has no wheel, middle button, or spacebar", () => {
    const { canvas, zoom } = setupCanvas();
    const before = zoom();
    fireEvent.pointerDown(canvas, touch(1, 400, 400));
    fireEvent.pointerDown(canvas, touch(2, 500, 400));
    fireEvent.pointerMove(canvas, touch(1, 300, 400));
    fireEvent.pointerMove(canvas, touch(2, 600, 400));
    expect(zoom()).toBeGreaterThan(before);
  });

  it("pinching inward zooms back out", () => {
    const { canvas, zoom } = setupCanvas();
    fireEvent.pointerDown(canvas, touch(1, 300, 400));
    fireEvent.pointerDown(canvas, touch(2, 600, 400));
    fireEvent.pointerMove(canvas, touch(1, 300, 400));
    fireEvent.pointerMove(canvas, touch(2, 600, 400));
    const wide = zoom();
    fireEvent.pointerMove(canvas, touch(1, 440, 400));
    fireEvent.pointerMove(canvas, touch(2, 460, 400));
    expect(zoom()).toBeLessThan(wide);
  });

  it("two fingers pan the photo without placing anything", () => {
    const { canvas, placed } = setupCanvas();
    fireEvent.pointerDown(canvas, touch(1, 400, 400));
    fireEvent.pointerDown(canvas, touch(2, 500, 400));
    fireEvent.pointerMove(canvas, touch(1, 300, 350));
    fireEvent.pointerMove(canvas, touch(2, 400, 350));
    fireEvent.pointerUp(canvas, touch(1, 300, 350));
    fireEvent.pointerUp(canvas, touch(2, 400, 350));
    expect(placed()).toBe(0);
  });

  it("traces and commits a bistro run with one finger", () => {
    const { canvas, dispatch } = setupAerialTool({ type: "draw", productId: BISTRO.id });

    fireEvent.pointerDown(canvas, touch(1, 220, 260));
    fireEvent.pointerMove(canvas, touch(1, 300, 300));
    fireEvent.pointerMove(canvas, touch(1, 380, 260));
    fireEvent.pointerUp(canvas, touch(1, 380, 260));

    expect(dispatch.mock.calls.map(([action]) => action)).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          type: "ADD_RUN",
          run: expect.objectContaining({
            productId: BISTRO.id,
            points: expect.arrayContaining([expect.any(Object), expect.any(Object)]),
          }),
        }),
      ]),
    );
  });

  it("discards a partial touch trace when the OS cancels the pointer", () => {
    const { canvas, dispatch } = setupAerialTool({ type: "draw", productId: BISTRO.id });

    fireEvent.pointerDown(canvas, touch(1, 220, 260));
    fireEvent.pointerMove(canvas, touch(1, 320, 300));
    fireEvent.pointerCancel(canvas, touch(1, 320, 300));

    expect(
      dispatch.mock.calls.some(([action]) => (action as EditorAction).type === "ADD_RUN"),
    ).toBe(false);
  });

  it("never leaves a stray fixture behind when a pinch begins", () => {
    // A pinch always starts as one finger landing a frame before the other. If
    // placement fired on touch-down, every zoom attempt would bill the customer
    // for a fixture nobody meant to place.
    const { canvas, placed } = setupCanvas();
    fireEvent.pointerDown(canvas, touch(1, 400, 400));
    expect(placed()).toBe(0);
    fireEvent.pointerDown(canvas, touch(2, 500, 400));
    fireEvent.pointerUp(canvas, touch(1, 400, 400));
    fireEvent.pointerUp(canvas, touch(2, 500, 400));
    expect(placed()).toBe(0);
  });

  it("does not place a fixture when the OS cancels a tap", () => {
    const { canvas, placed } = setupCanvas();
    fireEvent.pointerDown(canvas, touch(1, 420, 380));
    fireEvent.pointerCancel(canvas, touch(1, 420, 380));
    expect(placed()).toBe(0);
  });

  it("still places on a clean single tap", () => {
    const { canvas, placed } = setupCanvas();
    fireEvent.pointerDown(canvas, touch(1, 420, 380));
    fireEvent.pointerUp(canvas, touch(1, 420, 380));
    expect(placed()).toBe(1);
  });

  it("treats a finger that slid as a gesture, not a placement", () => {
    const { canvas, placed } = setupCanvas();
    fireEvent.pointerDown(canvas, touch(1, 420, 380));
    fireEvent.pointerUp(canvas, touch(1, 470, 430));
    expect(placed()).toBe(0);
  });
});

/**
 * Harness with one fixture already placed and selected, so the grips around it
 * are live. The geometry behind the grips is unit-tested in render.test.ts; what
 * matters here is that grabbing one drives the right edit.
 */
function setupSelectedFixture() {
  const item = {
    id: "item-1",
    productId: UPLIGHT.id,
    at: { x: 400, y: 600 },
    sizePx: 300,
  };
  const seen: EditorAction[] = [];
  function Harness() {
    const [state, rawDispatch] = React.useReducer(editorReducer, undefined, () => ({
      ...initialEditorState(),
      tool: { type: "select" as const },
      design: { calibration: null, runs: [], items: [item] },
      selection: { kind: "item" as const, id: item.id },
    }));
    const dispatch = (action: EditorAction) => {
      seen.push(action);
      rawDispatch(action);
    };
    return <LightCanvas photo={PHOTO} products={[UPLIGHT]} state={state} dispatch={dispatch} />;
  }
  const { container } = render(<Harness />);
  const canvas = container.querySelector("canvas")!;
  vi.spyOn(canvas, "getBoundingClientRect").mockReturnValue({
    left: 0,
    top: 0,
    width: PHOTO.width,
    height: PHOTO.height,
    right: PHOTO.width,
    bottom: PHOTO.height,
    x: 0,
    y: 0,
    toJSON: () => ({}),
  } as DOMRect);
  canvas.setPointerCapture = vi.fn();
  canvas.releasePointerCapture = vi.fn();
  return { canvas, seen, item };
}

describe("LightCanvas — beam spread grip", () => {
  beforeEach(() => vi.clearAllMocks());

  it("drags the spread grip into a beam-angle edit, leaving the throw alone", () => {
    // Grip on the cone's edge (up and to the right of an uplight's fixture).
    vi.mocked(beamHandlePos).mockReturnValue({ x: 480, y: 300 });
    vi.mocked(beamAngleAt).mockReturnValue(48);
    const { canvas, seen, item } = setupSelectedFixture();

    fireEvent.pointerDown(canvas, {
      clientX: 480,
      clientY: 300,
      button: 0,
      pointerId: 1,
    });
    fireEvent.pointerMove(canvas, {
      clientX: 560,
      clientY: 300,
      button: 0,
      pointerId: 1,
    });
    fireEvent.pointerUp(canvas, {
      clientX: 560,
      clientY: 300,
      button: 0,
      pointerId: 1,
    });

    const edits = seen.filter((a) => a.type === "UPDATE_ITEM");
    expect(edits).toHaveLength(1);
    expect(edits[0]).toMatchObject({
      id: item.id,
      patch: { beamAngleDeg: 48 },
    });
    // The throw and the position are untouched by a spread drag.
    expect(edits[0]).not.toHaveProperty("patch.sizePx");
    expect(edits[0]).not.toHaveProperty("patch.at");
    // One undo step for the whole drag, not one per pointer move.
    expect(seen.filter((a) => a.type === "COMMIT_HISTORY")).toHaveLength(1);
  });

  it("keeps the throw grip's priority where the two grips crowd each other", () => {
    // A tight beam puts both grips near the end of the throw; resizing the throw
    // is the more common gesture, so it wins the ambiguous grab.
    vi.mocked(resizeHandlePos).mockReturnValue({ x: 400, y: 300 });
    vi.mocked(beamHandlePos).mockReturnValue({ x: 404, y: 300 });
    const { canvas, seen } = setupSelectedFixture();

    fireEvent.pointerDown(canvas, {
      clientX: 402,
      clientY: 300,
      button: 0,
      pointerId: 1,
    });
    fireEvent.pointerMove(canvas, {
      clientX: 402,
      clientY: 250,
      button: 0,
      pointerId: 1,
    });

    const patch = seen.find((a) => a.type === "UPDATE_ITEM");
    expect(patch && "patch" in patch ? patch.patch : {}).toHaveProperty("sizePx");
  });
});
