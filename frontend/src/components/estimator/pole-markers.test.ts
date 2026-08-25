import { describe, expect, it } from "vitest";

import { BISTRO_POLE_PRODUCT, buildBistroCatalog, indexProducts } from "@/lib/estimator/catalog";
import type { Design } from "@/lib/estimator/types";

import { editorReducer, initialEditorState } from "./editor-store";
import { closestBistroRun } from "./light-canvas";

const bistroProducts = buildBistroCatalog([], { installationVariants: true });
const temporaryBistro = bistroProducts.find(
  (product) => product.target.field === "bistro" && product.target.installation === "temporary",
)!;
const permanentBistro = bistroProducts.find(
  (product) => product.target.field === "bistro" && product.target.installation === "permanent",
)!;
const products = indexProducts([...bistroProducts, BISTRO_POLE_PRODUCT]);

function design(): Design {
  return {
    calibration: null,
    runs: [
      {
        id: "temporary-run",
        productId: temporaryBistro.id,
        points: [
          { x: 0, y: 0 },
          { x: 100, y: 0 },
        ],
        colors: ["#ffffff"],
        spacingIn: 15,
      },
      {
        id: "permanent-run",
        productId: permanentBistro.id,
        points: [
          { x: 0, y: 100 },
          { x: 100, y: 100 },
        ],
        colors: ["#ffffff"],
        spacingIn: 15,
      },
    ],
    items: [
      {
        id: "pole-1",
        productId: BISTRO_POLE_PRODUCT.id,
        bistroRunId: "permanent-run",
        at: { x: 50, y: 100 },
        sizePx: 12,
      },
    ],
    planImages: [],
  };
}

describe("Bistro pole markers", () => {
  it("associates a placed marker with the closest Bistro run", () => {
    expect(closestBistroRun({ x: 40, y: 90 }, design(), products)?.id).toBe("permanent-run");
    expect(closestBistroRun({ x: 40, y: 10 }, design(), products)?.id).toBe("temporary-run");
  });

  it("moves and deletes attached pole markers with their run", () => {
    const state = { ...initialEditorState(), design: design() };
    const moved = editorReducer(state, {
      type: "UPDATE_RUN",
      id: "permanent-run",
      patch: {
        points: [
          { x: 20, y: 130 },
          { x: 120, y: 130 },
        ],
      },
    });

    expect(moved.design.items[0].at).toEqual({ x: 70, y: 130 });

    const deleted = editorReducer(moved, { type: "DELETE_RUN", id: "permanent-run" });
    expect(deleted.design.runs.map((run) => run.id)).toEqual(["temporary-run"]);
    expect(deleted.design.items).toEqual([]);
  });
});
