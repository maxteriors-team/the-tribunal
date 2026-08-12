import type { CatalogItemResponse } from "@/types/sales-wizard";

const SYSTEM_VOLTAGE = 12;

interface KnownElectricalSpec {
  watts?: number;
  transformerCapacityWatts?: number;
}

/**
 * Electrical values for the FX fixtures already carried in the Tribunal price book.
 * Catalog attributes override these defaults, so operators can update a fixture
 * without waiting for a frontend release.
 */
const TRIBUNAL_ELECTRICAL_DEFAULTS: Record<string, KnownElectricalSpec> = {
  "essential-accent": { watts: 5 },
  "essential-accent-alt": { watts: 4 },
  "essential-ingrade": { watts: 5 },
  "essential-path": { watts: 3 },
  "essential-ex-150": { transformerCapacityWatts: 150 },
  "ess-accent": { watts: 4 },
  "ess-path": { watts: 3 },
  "ess-ex": { transformerCapacityWatts: 150 },
  "better-accent": { watts: 5 },
  "better-ingrade": { watts: 5 },
  "better-path": { watts: 2.2 },
  "better-dx-300": { transformerCapacityWatts: 300 },
  "better-mod-path": { watts: 3 },
  "better-cora-in-grade": { watts: 5 },
  "better-well": { watts: 5 },
  "better-dx": { transformerCapacityWatts: 300 },
  "best-zdc-up": { watts: 9.1 },
  "best-zdc-down": { watts: 9.1 },
  "best-zdc-modern-path": { watts: 3.6 },
  "best-zdc-mod-path": { watts: 3.6 },
  "best-zdc-path": { watts: 3.6 },
  "best-zdc-path2": { watts: 3.6 },
  "best-well": { watts: 5 },
  "best-zd-down": { watts: 5 },
  "best-zd-ingrade": { watts: 5 },
  "best-zd-modern-path": { watts: 2 },
  "best-zd-mod-path": { watts: 2 },
  "best-zd-narrow": { watts: 5 },
  "best-zd-path": { watts: 2.2 },
  "best-zd-up": { watts: 5 },
  "best-cora-in-grade": { watts: 5 },
  "best-lux-300": { transformerCapacityWatts: 300 },
  "best-luxor": { transformerCapacityWatts: 300 },
};

export interface CatalogElectricalSpec {
  watts: number | null;
  inputVoltage: number;
  transformerCapacityWatts: number | null;
  source: "catalog" | "tribunal-default" | "missing";
}

export interface LandscapeLoadInput {
  id: string;
  label: string;
  quantity: number;
  item: CatalogItemResponse | null;
}

export interface LandscapeLoadRow {
  id: string;
  label: string;
  productName: string | null;
  quantity: number;
  wattsEach: number | null;
  totalWatts: number | null;
}

export type LandscapeLoadStatus =
  | "empty"
  | "incomplete"
  | "transformer-needed"
  | "within-capacity"
  | "limited-headroom"
  | "over-capacity";

export interface LandscapeElectricalLoad {
  rows: LandscapeLoadRow[];
  connectedWatts: number;
  currentAmps: number;
  transformerCapacityWatts: number;
  remainingCapacityWatts: number | null;
  utilizationPercent: number | null;
  missingFixtureIds: string[];
  status: LandscapeLoadStatus;
}

function positiveNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) && value > 0 ? value : null;
}

function attributeNumber(
  attributes: CatalogItemResponse["attributes"],
  keys: string[],
): number | null {
  if (!attributes) return null;
  for (const key of keys) {
    const value = positiveNumber(attributes[key]);
    if (value !== null) return value;
  }
  const electrical = attributes.electrical;
  if (electrical && typeof electrical === "object" && !Array.isArray(electrical)) {
    const values = electrical as Record<string, unknown>;
    for (const key of keys) {
      const value = positiveNumber(values[key]);
      if (value !== null) return value;
    }
  }
  return null;
}

function componentWatts(item: CatalogItemResponse): number | null {
  for (const component of item.components ?? []) {
    for (const value of [component.sku, component.description]) {
      const match = value?.match(/(?:^|\s)(\d+(?:\.\d+)?)\s*W(?:\s|$)/i);
      if (!match) continue;
      const watts = Number(match[1]);
      if (Number.isFinite(watts) && watts > 0) return watts;
    }
  }
  return null;
}

export function resolveCatalogElectricalSpec(
  item: CatalogItemResponse | null,
): CatalogElectricalSpec {
  if (!item) {
    return {
      watts: null,
      inputVoltage: SYSTEM_VOLTAGE,
      transformerCapacityWatts: null,
      source: "missing",
    };
  }

  const attributeWatts = attributeNumber(item.attributes, ["fixture_watts", "watts"]);
  const attributeCapacity = attributeNumber(item.attributes, [
    "transformer_capacity_watts",
    "capacity_watts",
  ]);
  const attributeVoltage = attributeNumber(item.attributes, ["input_voltage", "voltage"]);
  const known = item.sku ? TRIBUNAL_ELECTRICAL_DEFAULTS[item.sku] : undefined;
  const watts = attributeWatts ?? componentWatts(item) ?? known?.watts ?? null;
  const transformerCapacityWatts =
    attributeCapacity ??
    known?.transformerCapacityWatts ??
    (/transformer/i.test(item.name)
      ? positiveNumber(Number(item.name.match(/(\d+)\s*W/i)?.[1]))
      : null);

  return {
    watts,
    inputVoltage: attributeVoltage ?? SYSTEM_VOLTAGE,
    transformerCapacityWatts,
    source:
      attributeWatts !== null || attributeCapacity !== null
        ? "catalog"
        : watts !== null || transformerCapacityWatts !== null
          ? "tribunal-default"
          : "missing",
  };
}

export interface LandscapeCircuitInput {
  id: string;
  defaultWatts?: number;
  label: string;
  lengthFeet: number | null;
  wireGauge: 8 | 10 | 12 | 14;
  sourceVoltage: number;
  transformerAssigned: boolean;
  fixtures: Array<{ item: CatalogItemResponse | null }>;
}

export type LandscapeCircuitStatus =
  | "empty"
  | "incomplete"
  | "transformer-needed"
  | "scale-needed"
  | "within-range"
  | "review-drop"
  | "high-drop";

export interface LandscapeCircuitLoad {
  id: string;
  label: string;
  fixtureCount: number;
  connectedWatts: number;
  currentAmps: number;
  lengthFeet: number | null;
  wireGauge: 8 | 10 | 12 | 14;
  sourceVoltage: number;
  voltageDrop: number | null;
  voltageDropPercent: number | null;
  estimatedEndVoltage: number | null;
  minimumVoltage: number;
  usedDefaultWatts: boolean;
  status: LandscapeCircuitStatus;
}

const COPPER_OHMS_PER_1000_FT: Record<8 | 10 | 12 | 14, number> = {
  8: 0.6282,
  10: 0.9989,
  12: 1.588,
  14: 2.525,
};

const round = (value: number, digits = 1) => {
  const factor = 10 ** digits;
  return Math.round((value + Number.EPSILON) * factor) / factor;
};

export function calculateLandscapeCircuits(
  circuits: LandscapeCircuitInput[],
): LandscapeCircuitLoad[] {
  return circuits.map((circuit) => {
    const specs = circuit.fixtures.map((fixture) => resolveCatalogElectricalSpec(fixture.item));
    const hasMissingWatts = specs.some((spec) => spec.watts === null);
    const defaultWatts = positiveNumber(circuit.defaultWatts) ?? 0;
    const usedDefaultWatts = hasMissingWatts && defaultWatts > 0;
    const unresolvedWatts = hasMissingWatts && !usedDefaultWatts;
    const connectedWatts = round(
      specs.reduce((sum, spec) => sum + (spec.watts ?? defaultWatts), 0),
    );
    const currentAmps = round(connectedWatts / circuit.sourceVoltage, 2);
    const voltageDrop =
      circuit.lengthFeet === null
        ? null
        : round(
            (2 * circuit.lengthFeet * currentAmps * COPPER_OHMS_PER_1000_FT[circuit.wireGauge]) /
              1000,
            2,
          );
    const voltageDropPercent =
      voltageDrop === null ? null : round((voltageDrop / circuit.sourceVoltage) * 100, 1);
    const estimatedEndVoltage =
      voltageDrop === null ? null : round(circuit.sourceVoltage - voltageDrop, 2);

    let status: LandscapeCircuitStatus;
    if (!circuit.fixtures.length) status = "empty";
    else if (unresolvedWatts) status = "incomplete";
    else if (!circuit.transformerAssigned) status = "transformer-needed";
    else if (circuit.lengthFeet === null) status = "scale-needed";
    else if ((voltageDropPercent ?? 0) > 10) status = "high-drop";
    else if ((voltageDropPercent ?? 0) > 5) status = "review-drop";
    else status = "within-range";

    return {
      id: circuit.id,
      label: circuit.label,
      fixtureCount: circuit.fixtures.length,
      connectedWatts,
      currentAmps,
      lengthFeet: circuit.lengthFeet,
      wireGauge: circuit.wireGauge,
      sourceVoltage: circuit.sourceVoltage,
      voltageDrop,
      voltageDropPercent,
      estimatedEndVoltage,
      minimumVoltage: 10.5,
      usedDefaultWatts,
      status,
    };
  });
}

export function calculateLandscapeElectricalLoad(
  fixtures: LandscapeLoadInput[],
  transformer: { item: CatalogItemResponse | null; quantity: number },
): LandscapeElectricalLoad {
  const rows = fixtures.map<LandscapeLoadRow>((fixture) => {
    const spec = resolveCatalogElectricalSpec(fixture.item);
    return {
      id: fixture.id,
      label: fixture.label,
      productName: fixture.item?.name ?? null,
      quantity: fixture.quantity,
      wattsEach: spec.watts,
      totalWatts: spec.watts === null ? null : round(spec.watts * fixture.quantity),
    };
  });
  const missingFixtureIds = rows.filter((row) => row.wattsEach === null).map((row) => row.id);
  const connectedWatts = round(rows.reduce((sum, row) => sum + (row.totalWatts ?? 0), 0));
  const transformerSpec = resolveCatalogElectricalSpec(transformer.item);
  const transformerCapacityWatts = round(
    (transformerSpec.transformerCapacityWatts ?? 0) * transformer.quantity,
  );
  const utilizationPercent =
    transformerCapacityWatts > 0 ? round((connectedWatts / transformerCapacityWatts) * 100) : null;
  const remainingCapacityWatts =
    transformerCapacityWatts > 0 ? round(transformerCapacityWatts - connectedWatts) : null;

  let status: LandscapeLoadStatus;
  if (!rows.length) status = "empty";
  else if (missingFixtureIds.length) status = "incomplete";
  else if (transformerCapacityWatts === 0) status = "transformer-needed";
  else if ((utilizationPercent ?? 0) > 100) status = "over-capacity";
  else if ((utilizationPercent ?? 0) > 80) status = "limited-headroom";
  else status = "within-capacity";

  return {
    rows,
    connectedWatts,
    currentAmps: round(connectedWatts / SYSTEM_VOLTAGE, 2),
    transformerCapacityWatts,
    remainingCapacityWatts,
    utilizationPercent,
    missingFixtureIds,
    status,
  };
}
