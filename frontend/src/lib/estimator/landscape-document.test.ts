import { describe, expect, it } from "vitest";

import {
  createLandscapeDocument,
  defaultLandscapePrecon,
  defaultLandscapeProposal,
  defaultLandscapeSettings,
  normalizeLandscapeDocument,
} from "@/lib/estimator/landscape-document";
import { createLandscapeDraft } from "@/lib/estimator/landscape-draft";

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
      projectType: "landscape",
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
      bomLineItems: [],
      procurement: {},
      precon: { responses: [], leadInstaller: "", notes: "" },
    });
    expect(migrated?.shots[0]?.sheet).toMatchObject({
      label: "Aerial plan 1",
      drawingTitle: "Aerial landscape lighting plan",
      drawingNumber: "L-1",
    });
  });

  it("round-trips permanent project identity with its editable drawing", () => {
    const permanent = createLandscapeDraft(
      [shot],
      "shot-1",
      "2026-08-14T12:00:00.000Z",
      undefined,
      undefined,
      "permanent",
    );

    expect(normalizeLandscapeDocument(JSON.parse(JSON.stringify(permanent)))).toMatchObject({
      version: 2,
      projectType: "permanent",
      activeShotId: "shot-1",
      shots: [{ id: "shot-1" }],
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

  it("normalizes fixture icon scale and editable procurement values", () => {
    const document = normalizeLandscapeDocument({
      ...createLandscapeDocument(
        [
          {
            ...shot,
            design: {
              ...shot.design,
              items: [
                {
                  id: "fixture-1",
                  productId: "fixture-uplight",
                  at: { x: 20, y: 30 },
                  sizePx: 40,
                  iconScale: 9,
                },
              ],
            },
          },
        ],
        "shot-1",
      ),
      procurement: {
        "fixture:fixture-1": {
          description: "Patina uplight",
          manufacturer: "Tribunal Lighting",
          supplier: "Regional Supply",
          neededQuantity: 4,
          orderedQuantity: 3,
          receivedQuantity: 1,
          unitCost: 82.5,
          supplierNote: "PO-1042",
        },
      },
    });

    expect(document?.shots[0]?.design.items[0]?.iconScale).toBe(1.8);
    expect(document?.procurement?.["fixture:fixture-1"]).toMatchObject({
      description: "Patina uplight",
      manufacturer: "Tribunal Lighting",
      supplier: "Regional Supply",
      neededQuantity: 4,
      unitCost: 82.5,
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

  it("normalizes manual BOM lines, bounds values, and repairs duplicate IDs", () => {
    const document = normalizeLandscapeDocument({
      ...createLandscapeDocument([shot], "shot-1"),
      bomLineItems: [
        {
          id: "manual-1",
          description: "Copper ground stake",
          sku: "STAKE-CU",
          quantity: 4,
          unit: "each",
        },
        { id: "manual-1", description: "Wire", sku: "", quantity: 200_000, unit: "ft" },
        { id: "ignored", description: "Ignored malformed row" },
      ],
    });

    expect(document?.bomLineItems).toEqual([
      {
        id: "manual-1",
        description: "Copper ground stake",
        sku: "STAKE-CU",
        quantity: 4,
        unit: "each",
      },
      {
        id: "manual-1-2",
        description: "Wire",
        sku: "",
        quantity: 100_000,
        unit: "ft",
      },
      {
        id: "ignored",
        description: "Ignored malformed row",
        sku: "",
        quantity: 1,
        unit: "each",
      },
    ]);
  });

  it("serializes every live document setting and workflow state", () => {
    const liveState = {
      activeWorkflowTab: "precon" as const,
      settings: {
        ...defaultLandscapeSettings(),
        paperSize: "arch-c" as const,
        planFit: "cover" as const,
        planOpacity: 0.5,
        legend: { visible: false, position: { x: 88, y: 64 }, scale: 1.3 },
        halosVisible: false,
        fixtureNumbersVisible: false,
        measurementsVisible: false,
        sourceVoltage: 15,
      },
      proposal: {
        ...defaultLandscapeProposal(),
        selectedTierKey: "best",
        selectedCarePlanKey: "priority",
        designIntent: "Warm entry and specimen-tree emphasis",
        showFixtureDetails: false,
        showCombinedTotal: false,
        additionalLineItems: [{ id: "custom-1", description: "Core drill", amount: 275 }],
      },
      bomLineItems: [
        {
          id: "manual-bom-1",
          description: "Copper ground stake",
          sku: "STAKE-CU",
          quantity: 4,
          unit: "each" as const,
        },
      ],
      procurement: {
        "fixture-1": {
          catalogItemId: "catalog-1",
          catalogSku: "UP-4W",
          orderedQuantity: 4,
          receivedQuantity: 2,
          supplierNote: "ETA Friday",
        },
      },
      precon: {
        ...defaultLandscapePrecon(),
        leadInstaller: "Jordan",
        notes: "Protect the copper roof.",
      },
    };

    const draft = createLandscapeDraft(
      [shot],
      "shot-1",
      "2026-08-14T12:00:00.000Z",
      undefined,
      liveState,
    );
    const roundTrip = normalizeLandscapeDocument(JSON.parse(JSON.stringify(draft)));

    expect(roundTrip).toMatchObject(liveState);
    expect(roundTrip?.proposal?.additionalLineItems).toEqual(
      liveState.proposal.additionalLineItems,
    );
    expect(roundTrip?.bomLineItems).toEqual(liveState.bomLineItems);
  });

  it("keeps a project whose images live in the bucket", () => {
    // Migrated projects store a reference, not bytes. Dropping the shot here
    // makes normalize return null, which the autosave hook turns into a thrown
    // "invalid document" — i.e. the designer fails to open at all.
    const stored = {
      ...shot,
      photo: { ...shot.photo, dataUrl: "lighting-image:workspaces/w/lighting-projects/p/a.png" },
    };

    const normalized = normalizeLandscapeDocument({
      version: 2,
      shots: [stored],
      activeShotId: stored.id,
    });

    expect(normalized).not.toBeNull();
    expect(normalized?.shots).toHaveLength(1);
    expect(normalized?.shots[0]?.photo.dataUrl).toBe(stored.photo.dataUrl);
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
