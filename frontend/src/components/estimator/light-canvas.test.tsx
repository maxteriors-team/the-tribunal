import { fireEvent, render } from "@testing-library/react";
import React from "react";
import { describe, expect, it, vi, beforeEach } from "vitest";

import type { PhotoInfo, Product } from "@/lib/estimator/types";

import {
  editorReducer,
  initialEditorState,
  type EditorAction,
  type EditorState,
} from "./editor-store";
import { LightCanvas } from "./light-canvas";

// The glow engine is exercised in render.test.ts; jsdom has no 2D context.
vi.mock("@/lib/estimator/render", () => ({
  drawScene: vi.fn(),
  itemHit: vi.fn(() => false),
  resizeHandlePos: vi.fn(() => ({ x: 0, y: 0 })),
  DEFAULT_DUSK: 0.52,
  MAX_DUSK: 0.92,
}));

vi.mock("@/lib/estimator/photo", () => ({
  loadImage: vi.fn().mockResolvedValue({ naturalWidth: 1000, naturalHeight: 800 }),
}));

const PHOTO: PhotoInfo = {
  dataUrl: "data:image/png;base64,AAAA",
  width: 1000,
  height: 800,
};

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

/**
 * Mount the canvas with the place tool armed, with the canvas element mapped
 * 1:1 onto the photo (identity transform) so a client coordinate is also an
 * image coordinate — which makes "outside the photo" easy to express.
 */
function setup() {
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
  const placed = () =>
    dispatch.mock.calls.filter(([a]) => a.type === "ADD_ITEM").length;

  return { clickAt, placed, dispatch, rerender };
}

describe("LightCanvas — geometry stays on the photo", () => {
  beforeEach(() => vi.clearAllMocks());

  it("places a fixture where the rep clicks on the photo", () => {
    const { clickAt, placed } = setup();
    clickAt(500, 400);
    expect(placed()).toBe(1);
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

/**
 * Harness that keeps real reducer state, so a gesture's effect on the view is
 * observable through the rendered zoom label rather than by reaching inside.
 */
function setupCanvas() {
  const seen: EditorAction[] = [];
  function Harness() {
    const [state, rawDispatch] = React.useReducer(
      editorReducer,
      undefined,
      () => ({
        ...initialEditorState(),
        tool: { type: "place" as const, productId: UPLIGHT.id },
      }),
    );
    const dispatch = (action: EditorAction) => {
      seen.push(action);
      rawDispatch(action);
    };
    return (
      <LightCanvas
        photo={PHOTO}
        products={[UPLIGHT]}
        state={state}
        dispatch={dispatch}
      />
    );
  }
  const { container } = render(<Harness />);
  const canvas = container.querySelector("canvas")!;
  vi.spyOn(canvas, "getBoundingClientRect").mockReturnValue({
    left: 0, top: 0, width: PHOTO.width, height: PHOTO.height,
    right: PHOTO.width, bottom: PHOTO.height, x: 0, y: 0, toJSON: () => ({}),
  } as DOMRect);
  canvas.setPointerCapture = vi.fn();
  canvas.releasePointerCapture = vi.fn();

  const zoom = () => {
    const label = container.querySelector(".lc-zoom-label")?.textContent ?? "";
    return Number(label.replace("%", ""));
  };
  const placed = () => seen.filter((a) => a.type === "ADD_ITEM").length;
  return { canvas, zoom, placed, seen };
}

describe("LightCanvas — touch gestures", () => {
  beforeEach(() => vi.clearAllMocks());

  const touch = (id: number, x: number, y: number) => ({
    pointerId: id, clientX: x, clientY: y, button: 0, pointerType: "touch",
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
