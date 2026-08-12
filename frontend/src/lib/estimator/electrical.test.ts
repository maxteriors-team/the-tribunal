import { describe, expect, it } from "vitest";

import type { CatalogItemResponse } from "@/types/sales-wizard";

import {
  calculateLandscapeCircuits,
  calculateLandscapeElectricalLoad,
  resolveCatalogElectricalSpec,
} from "./electrical";

const item = (
  sku: string,
  name: string,
  attributes?: Record<string, unknown>,
): CatalogItemResponse =>
  ({
    id: sku,
    workspace_id: "workspace-1",
    name,
    sku,
    kind: "product",
    unit_price: 0,
    taxable: true,
    is_active: true,
    is_attachable: false,
    attach_targets: [],
    attributes: attributes ?? null,
    components: null,
    created_at: "2026-08-11T00:00:00Z",
    updated_at: "2026-08-11T00:00:00Z",
  }) as CatalogItemResponse;

describe("landscape electrical load", () => {
  it("resolves the FX fixtures and transformers already in the Tribunal catalog", () => {
    expect(resolveCatalogElectricalSpec(item("best-zdc-up", "ZDC Color Uplight"))).toMatchObject({
      watts: 9.1,
      inputVoltage: 12,
      source: "tribunal-default",
    });
    expect(
      resolveCatalogElectricalSpec(item("best-lux-300", "Luxor 300W Transformer")),
    ).toMatchObject({ transformerCapacityWatts: 300 });
  });

  it("prefers catalog electrical attributes over bundled defaults", () => {
    expect(
      resolveCatalogElectricalSpec(
        item("best-zdc-up", "ZDC Color Uplight", {
          electrical: { watts: 10.5, input_voltage: 15 },
        }),
      ),
    ).toMatchObject({ watts: 10.5, inputVoltage: 15, source: "catalog" });
  });

  it("calculates connected watts, 12V current, capacity, and headroom", () => {
    const load = calculateLandscapeElectricalLoad(
      [
        {
          id: "uplight",
          label: "Uplight",
          quantity: 4,
          item: item("best-zdc-up", "ZDC Color Uplight"),
        },
        {
          id: "pathlight",
          label: "Path light",
          quantity: 3,
          item: item("best-zdc-modern-path", "ZDC Modern Color Path Light"),
        },
      ],
      { item: item("best-lux-300", "Luxor 300W Transformer"), quantity: 1 },
    );

    expect(load.connectedWatts).toBe(47.2);
    expect(load.currentAmps).toBe(3.93);
    expect(load.transformerCapacityWatts).toBe(300);
    expect(load.remainingCapacityWatts).toBe(252.8);
    expect(load.utilizationPercent).toBe(15.7);
    expect(load.status).toBe("within-capacity");
  });

  it("calculates conservative circuit voltage drop from route, gauge, tap, and assigned fixtures", () => {
    const circuit = calculateLandscapeCircuits([
      {
        id: "circuit-1",
        label: "C1",
        lengthFeet: 100,
        wireGauge: 12,
        sourceVoltage: 12,
        transformerAssigned: true,
        fixtures: Array.from({ length: 4 }, () => ({
          item: item("best-zdc-up", "ZDC Color Uplight"),
        })),
      },
    ])[0];

    expect(circuit).toMatchObject({
      connectedWatts: 36.4,
      currentAmps: 3.03,
      voltageDrop: 0.96,
      voltageDropPercent: 8,
      estimatedEndVoltage: 11.04,
      status: "review-drop",
    });
  });

  it("requires scale and transformer assignment before calling a circuit calculated", () => {
    const base = {
      id: "circuit-1",
      label: "C1",
      lengthFeet: null,
      wireGauge: 12 as const,
      sourceVoltage: 12,
      transformerAssigned: true,
      fixtures: [{ item: item("essential-accent", "Cora Accent Black") }],
    };

    expect(calculateLandscapeCircuits([base])[0].status).toBe("scale-needed");
    expect(
      calculateLandscapeCircuits([{ ...base, lengthFeet: 20, transformerAssigned: false }])[0]
        .status,
    ).toBe("transformer-needed");
  });

  it("uses an explicit default watt value while labeling the estimate", () => {
    const [circuit] = calculateLandscapeCircuits([
      {
        id: "circuit-default",
        label: "C2",
        lengthFeet: 20,
        wireGauge: 12,
        sourceVoltage: 13,
        transformerAssigned: true,
        defaultWatts: 7,
        fixtures: [{ item: null }, { item: null }],
      },
    ]);

    expect(circuit).toMatchObject({
      connectedWatts: 14,
      usedDefaultWatts: true,
      minimumVoltage: 10.5,
      status: "within-range",
    });
  });

  it("does not pretend the plan is complete when no transformer is placed", () => {
    const load = calculateLandscapeElectricalLoad(
      [
        {
          id: "uplight",
          label: "Uplight",
          quantity: 1,
          item: item("essential-accent", "Cora Accent Black"),
        },
      ],
      { item: item("ess-ex-150", "EX 150W Transformer"), quantity: 0 },
    );

    expect(load.connectedWatts).toBe(5);
    expect(load.transformerCapacityWatts).toBe(0);
    expect(load.status).toBe("transformer-needed");
  });
});
