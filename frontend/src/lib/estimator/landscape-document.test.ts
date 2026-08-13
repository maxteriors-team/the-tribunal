import { describe, expect, it } from "vitest";

import {
  createLandscapeDocument,
  normalizeLandscapeDocument,
} from "@/lib/estimator/landscape-document";

const shot = {
  id: "shot-1",
  photo: { dataUrl: "data:image/png;base64,AAAA", width: 1200, height: 800 },
  design: { calibration: null, runs: [], items: [] },
  dusk: 0.35,
};

describe("landscape document v2", () => {
  it("migrates a v1 draft and applies complete defaults", () => {
    const migrated = normalizeLandscapeDocument({
      version: 1,
      activeShotId: "shot-1",
      shots: [shot],
      updatedAt: "2026-08-11T00:00:00.000Z",
      proposal: { selectedTierKey: "better", selectedCarePlanKey: "essential" },
    });

    expect(migrated).toMatchObject({
      version: 2,
      activeShotId: "shot-1",
      activeWorkflowTab: "drawing",
      settings: {
        paperSize: "tabloid",
        planFit: "contain",
        planOpacity: 1,
        sourceVoltage: 13,
      },
      proposal: {
        selectedTierKey: "better",
        selectedCarePlanKey: "essential",
        showCombinedTotal: true,
        showFixtureDetails: true,
      },
      procurement: {},
      precon: { responses: [], leadInstaller: "", notes: "" },
    });
    expect(migrated?.shots[0]?.sheet).toMatchObject({
      label: "Sheet 1",
      drawingNumber: "L-1",
    });
  });

  it("normalizes unsafe numeric settings without dropping project content", () => {
    const document = normalizeLandscapeDocument({
      ...createLandscapeDocument([shot], "shot-1"),
      settings: {
        paperSize: "unknown",
        planFit: "cover",
        planOpacity: 9,
        sourceVoltage: 0,
        legend: { visible: false, position: { x: -2, y: 10 }, scale: 10 },
      },
    });

    expect(document?.settings).toMatchObject({
      paperSize: "tabloid",
      planFit: "cover",
      planOpacity: 1,
      sourceVoltage: 10,
      legend: { visible: false, position: { x: 0, y: 10 }, scale: 2 },
    });
  });

  it("normalizes persisted additional proposal line items", () => {
    const document = normalizeLandscapeDocument({
      ...createLandscapeDocument([shot], "shot-1"),
      proposal: {
        additionalLineItems: [
          { id: "custom-1", description: "Core drill", amount: 275.5 },
          { id: "custom-2", description: "", amount: -10 },
        ],
      },
    });

    expect(document?.proposal?.additionalLineItems).toEqual([
      { id: "custom-1", description: "Core drill", amount: 275.5 },
      { id: "custom-2", description: "", amount: 0 },
    ]);
  });

  it("rejects malformed image payloads and excessive sheets", () => {
    expect(
      normalizeLandscapeDocument({
        version: 1,
        shots: [{ ...shot, photo: { ...shot.photo, dataUrl: "https://example.com/x.png" } }],
      }),
    ).toBeNull();
    expect(
      normalizeLandscapeDocument({
        version: 1,
        shots: Array.from({ length: 7 }, (_, index) => ({ ...shot, id: `shot-${index}` })),
      }),
    ).toBeNull();
  });
});
