import { describe, expect, it } from "vitest";

import type { Design, PlanImage } from "@/lib/estimator/types";

import { editorReducer, initialEditorState } from "./editor-store";

const PLAN_IMAGE: PlanImage = {
  id: "plan-image-1",
  dataUrl: "data:image/png;base64,AAAA",
  name: "Pool detail.png",
  at: { x: 300, y: 200 },
  widthPx: 240,
  heightPx: 160,
};

describe("editorReducer plan images", () => {
  it("adds and selects a movable plan image", () => {
    const state = editorReducer(initialEditorState(), {
      type: "ADD_PLAN_IMAGE",
      image: PLAN_IMAGE,
    });

    expect(state.design.planImages).toEqual([PLAN_IMAGE]);
    expect(state.selection).toEqual({ kind: "planImage", id: PLAN_IMAGE.id });
    expect(state.tool).toEqual({ type: "select" });
  });

  it("commits a drag as one undoable update", () => {
    const added = editorReducer(initialEditorState(), {
      type: "ADD_PLAN_IMAGE",
      image: PLAN_IMAGE,
    });
    const moved = editorReducer(added, {
      type: "UPDATE_PLAN_IMAGE",
      id: PLAN_IMAGE.id,
      patch: { at: { x: 500, y: 450 } },
      transient: true,
    });
    const committed = editorReducer(moved, {
      type: "COMMIT_HISTORY",
      before: added.design,
    });
    const undone = editorReducer(committed, { type: "UNDO" });

    expect(moved.design.planImages?.[0].at).toEqual({ x: 500, y: 450 });
    expect(undone.design.planImages?.[0].at).toEqual(PLAN_IMAGE.at);
  });

  it("keeps reference images when clearing priced lighting geometry", () => {
    const added = editorReducer(initialEditorState(), {
      type: "ADD_PLAN_IMAGE",
      image: PLAN_IMAGE,
    });
    const cleared = editorReducer(added, { type: "CLEAR_DESIGN" });

    expect(cleared.design.planImages).toEqual([PLAN_IMAGE]);
  });

  it("removes a selected plan image", () => {
    const added = editorReducer(initialEditorState(), {
      type: "ADD_PLAN_IMAGE",
      image: PLAN_IMAGE,
    });
    const deleted = editorReducer(added, {
      type: "DELETE_PLAN_IMAGE",
      id: PLAN_IMAGE.id,
    });

    expect(deleted.design.planImages).toEqual([]);
    expect(deleted.selection).toBeNull();
  });
});

describe("editorReducer calibration scales", () => {
  it("updates Scale 2 without overwriting Scale 1 and keeps the change undoable", () => {
    const primary = { a: { x: 0, y: 0 }, b: { x: 100, y: 0 }, feet: 10 };
    const secondary = { a: { x: 0, y: 20 }, b: { x: 200, y: 20 }, feet: 10 };
    const withPrimary = editorReducer(initialEditorState(), {
      type: "SET_CALIBRATION",
      calibration: primary,
    });
    const withSecondary = editorReducer(withPrimary, {
      type: "SET_CALIBRATION",
      calibration: secondary,
      scaleSlot: 2,
    });

    expect(withSecondary.design.calibration).toEqual(primary);
    expect(withSecondary.design.secondaryCalibration).toEqual(secondary);
    const undone = editorReducer(withSecondary, { type: "UNDO" });
    expect(undone.design.calibration).toEqual(primary);
    expect(undone.design.secondaryCalibration).toBeUndefined();
  });
});

const ELECTRICAL_DESIGN: Design = {
  calibration: null,
  planImages: [],
  runs: [
    {
      id: "circuit-1",
      productId: "landscape-wire",
      points: [
        { x: 10, y: 10 },
        { x: 100, y: 100 },
      ],
      circuitLabel: "C1",
      transformerId: "transformer-1",
      wireGauge: 12,
      sourceVoltage: 12,
    },
  ],
  items: [
    {
      id: "fixture-1",
      productId: "fixture-uplight",
      at: { x: 100, y: 100 },
      sizePx: 30,
      circuitId: "circuit-1",
    },
    {
      id: "transformer-1",
      productId: "fixture-transformer",
      at: { x: 10, y: 10 },
      sizePx: 30,
    },
  ],
};

describe("editorReducer electrical references", () => {
  it("clears fixture assignments when their wire circuit is deleted", () => {
    const loaded = editorReducer(initialEditorState(), {
      type: "RESET",
      design: ELECTRICAL_DESIGN,
    });
    const deleted = editorReducer(loaded, { type: "DELETE_RUN", id: "circuit-1" });

    expect(deleted.design.items.find((item) => item.id === "fixture-1")?.circuitId).toBeUndefined();
  });

  it("clears circuit assignments when their transformer is deleted", () => {
    const loaded = editorReducer(initialEditorState(), {
      type: "RESET",
      design: ELECTRICAL_DESIGN,
    });
    const deleted = editorReducer(loaded, { type: "DELETE_ITEM", id: "transformer-1" });

    expect(deleted.design.runs[0].transformerId).toBeUndefined();
  });
});
