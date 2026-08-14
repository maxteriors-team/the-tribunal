import type { DesignerShot } from "@/components/estimator/proposal-host";
import type {
  LandscapeBomLineItem,
  LandscapeLegendSettings,
  LandscapePaperSize,
  LandscapePlanFit,
  LandscapePreconState,
  LandscapeProcurementState,
  LandscapeProposalSettings,
  LandscapeWorkflowTab,
} from "@/lib/estimator/types";

export const LANDSCAPE_DOCUMENT_VERSION = 2 as const;
export const LANDSCAPE_PAPER_SIZES: readonly LandscapePaperSize[] = [
  "tabloid",
  "super-b",
  "letter",
  "arch-c",
  "arch-d",
  "ansi-d",
];
export const LANDSCAPE_WORKFLOW_TABS: readonly LandscapeWorkflowTab[] = [
  "drawing",
  "schedule",
  "bom",
  "electrical",
  "proposal",
  "precon",
];

export interface LandscapeDocumentSettings {
  paperSize: LandscapePaperSize;
  planFit: LandscapePlanFit;
  planOpacity: number;
  legend: LandscapeLegendSettings;
  halosVisible: boolean;
  fixtureNumbersVisible: boolean;
  measurementsVisible: boolean;
  sourceVoltage: number;
}

export interface LandscapeDocumentV2 {
  version: typeof LANDSCAPE_DOCUMENT_VERSION;
  activeShotId: string | null;
  activeWorkflowTab?: LandscapeWorkflowTab;
  shots: DesignerShot[];
  updatedAt: string;
  settings?: LandscapeDocumentSettings;
  proposal?: LandscapeProposalSettings;
  bomLineItems?: LandscapeBomLineItem[];
  procurement?: Record<string, LandscapeProcurementState>;
  precon?: LandscapePreconState;
}

export const defaultLandscapeSettings = (): LandscapeDocumentSettings => ({
  paperSize: "tabloid",
  planFit: "contain",
  planOpacity: 1,
  legend: { visible: true, position: { x: 24, y: 24 }, scale: 1 },
  halosVisible: true,
  fixtureNumbersVisible: true,
  measurementsVisible: true,
  sourceVoltage: 13,
});

export const defaultLandscapeProposal = (): LandscapeProposalSettings => ({
  selectedTierKey: null,
  selectedCarePlanKey: null,
  designIntent: "",
  showCombinedTotal: true,
  showFixtureDetails: true,
  zones: [],
  paymentMilestones: [
    { id: "deposit", label: "Scheduling deposit", percent: 50 },
    { id: "completion", label: "Due at completion", percent: 50 },
  ],
  electricalResponsibility: "",
  enhancements: [],
  additionalLineItems: [],
  commitments: [],
  signatureName: "",
  signatureDate: null,
});

export const defaultLandscapePrecon = (): LandscapePreconState => ({
  responses: [],
  leadInstaller: "",
  notes: "",
});

const record = (value: unknown): Record<string, unknown> | null =>
  value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;

const stringOrNull = (value: unknown): string | null =>
  typeof value === "string" && value.trim() ? value : null;

const stringValue = (value: unknown, fallback = ""): string =>
  typeof value === "string" ? value : fallback;

const booleanValue = (value: unknown, fallback: boolean): boolean =>
  typeof value === "boolean" ? value : fallback;

const finiteNumber = (value: unknown, fallback: number, minimum: number, maximum: number): number =>
  typeof value === "number" && Number.isFinite(value)
    ? Math.min(maximum, Math.max(minimum, value))
    : fallback;

const normalizedShots = (value: unknown): DesignerShot[] => {
  if (!Array.isArray(value)) return [];
  return value.flatMap((entry, index) => {
    const shot = record(entry);
    const photo = record(shot?.photo);
    const design = record(shot?.design);
    if (
      !shot ||
      typeof shot.id !== "string" ||
      !photo ||
      typeof photo.dataUrl !== "string" ||
      !photo.dataUrl.startsWith("data:image/") ||
      typeof photo.width !== "number" ||
      photo.width <= 0 ||
      typeof photo.height !== "number" ||
      photo.height <= 0 ||
      !design ||
      !Array.isArray(design.runs) ||
      !Array.isArray(design.items) ||
      typeof shot.dusk !== "number"
    ) {
      return [];
    }
    const sheet = record(shot.sheet);
    return [
      {
        ...(shot as unknown as DesignerShot),
        sheet: {
          label: stringValue(sheet?.label, `Aerial plan ${index + 1}`),
          drawingTitle: stringValue(sheet?.drawingTitle, "Aerial landscape lighting plan"),
          drawingNumber: stringValue(sheet?.drawingNumber, `L-${index + 1}`),
          proposalZoneId: stringOrNull(sheet?.proposalZoneId) ?? undefined,
          revisions: Array.isArray(sheet?.revisions) ? (sheet.revisions as never[]) : [],
        },
      },
    ];
  });
};

const normalizeSettings = (value: unknown): LandscapeDocumentSettings => {
  const defaults = defaultLandscapeSettings();
  const settings = record(value);
  const legend = record(settings?.legend);
  const position = record(legend?.position);
  const paperSize = LANDSCAPE_PAPER_SIZES.includes(settings?.paperSize as LandscapePaperSize)
    ? (settings?.paperSize as LandscapePaperSize)
    : defaults.paperSize;
  return {
    paperSize,
    planFit: settings?.planFit === "cover" ? "cover" : "contain",
    planOpacity: finiteNumber(settings?.planOpacity, defaults.planOpacity, 0.1, 1),
    legend: {
      visible: booleanValue(legend?.visible, defaults.legend.visible),
      position: {
        x: finiteNumber(position?.x, defaults.legend.position.x, 0, 100_000),
        y: finiteNumber(position?.y, defaults.legend.position.y, 0, 100_000),
      },
      scale: finiteNumber(legend?.scale, defaults.legend.scale, 0.5, 2),
    },
    halosVisible: booleanValue(settings?.halosVisible, defaults.halosVisible),
    fixtureNumbersVisible: booleanValue(
      settings?.fixtureNumbersVisible,
      defaults.fixtureNumbersVisible,
    ),
    measurementsVisible: booleanValue(
      settings?.measurementsVisible,
      defaults.measurementsVisible,
    ),
    sourceVoltage: finiteNumber(settings?.sourceVoltage, defaults.sourceVoltage, 10, 24),
  };
};

const normalizeProposal = (value: unknown): LandscapeProposalSettings => {
  const defaults = defaultLandscapeProposal();
  const proposal = record(value);
  if (!proposal) return defaults;
  const milestones = Array.isArray(proposal.paymentMilestones)
    ? proposal.paymentMilestones.flatMap((entry, index) => {
        const item = record(entry);
        if (!item) return [];
        return [
          {
            id: stringValue(item.id, `milestone-${index + 1}`),
            label: stringValue(item.label, `Milestone ${index + 1}`),
            percent: finiteNumber(item.percent, 0, 0, 100),
          },
        ];
      })
    : defaults.paymentMilestones;
  return {
    selectedTierKey: stringOrNull(proposal.selectedTierKey),
    selectedCarePlanKey: stringOrNull(proposal.selectedCarePlanKey),
    designIntent: stringValue(proposal.designIntent),
    showCombinedTotal: booleanValue(proposal.showCombinedTotal, true),
    showFixtureDetails: booleanValue(proposal.showFixtureDetails, true),
    zones: Array.isArray(proposal.zones) ? (proposal.zones as never[]) : [],
    paymentMilestones: milestones,
    electricalResponsibility: stringValue(proposal.electricalResponsibility),
    enhancements: Array.isArray(proposal.enhancements) ? (proposal.enhancements as never[]) : [],
    additionalLineItems: Array.isArray(proposal.additionalLineItems)
      ? proposal.additionalLineItems.flatMap((entry, index) => {
          const item = record(entry);
          if (!item) return [];
          return [
            {
              id: stringValue(item.id, `line-item-${index + 1}`),
              description: stringValue(item.description),
              amount: finiteNumber(item.amount, 0, 0, 1_000_000),
            },
          ];
        })
      : [],
    commitments: Array.isArray(proposal.commitments)
      ? proposal.commitments.filter((item): item is string => typeof item === "string")
      : [],
    signatureName: stringValue(proposal.signatureName),
    signatureDate: stringOrNull(proposal.signatureDate),
  };
};

const normalizeBomLineItems = (value: unknown): LandscapeBomLineItem[] => {
  if (!Array.isArray(value)) return [];
  const usedIds = new Set<string>();
  return value.slice(0, 100).flatMap((entry, index) => {
    const item = record(entry);
    if (!item) return [];
    const fallbackId = `bom-line-${index + 1}`;
    const baseId = (stringValue(item.id, fallbackId).trim() || fallbackId).slice(0, 250);
    let id = baseId;
    let suffix = 2;
    while (usedIds.has(id)) {
      id = `${baseId.slice(0, 240)}-${suffix}`;
      suffix += 1;
    }
    usedIds.add(id);
    return [
      {
        id,
        description: stringValue(item.description).slice(0, 500),
        sku: stringValue(item.sku).slice(0, 160),
        quantity: finiteNumber(item.quantity, 1, 0, 100_000),
        unit: item.unit === "ft" ? "ft" : "each",
      },
    ];
  });
};

const normalizeProcurement = (value: unknown): Record<string, LandscapeProcurementState> => {
  const input = record(value);
  if (!input) return {};
  return Object.fromEntries(
    Object.entries(input).flatMap(([key, entry]) => {
      const item = record(entry);
      if (!item) return [];
      return [
        [
          key,
          {
            catalogItemId: stringOrNull(item.catalogItemId) ?? undefined,
            catalogSku: stringOrNull(item.catalogSku) ?? undefined,
            orderedQuantity: finiteNumber(item.orderedQuantity, 0, 0, 100_000),
            receivedQuantity: finiteNumber(item.receivedQuantity, 0, 0, 100_000),
            supplierNote: stringValue(item.supplierNote),
          },
        ],
      ];
    }),
  );
};

const normalizePrecon = (value: unknown): LandscapePreconState => {
  const input = record(value);
  const defaults = defaultLandscapePrecon();
  if (!input) return defaults;
  return {
    responses: Array.isArray(input.responses) ? (input.responses as never[]) : [],
    leadInstaller: stringValue(input.leadInstaller),
    notes: stringValue(input.notes),
  };
};

/** Migrate every accepted v1 browser/server document into the strict v2 shape. */
export function normalizeLandscapeDocument(value: unknown): LandscapeDocumentV2 | null {
  const candidate = record(value);
  if (!candidate) return null;
  const shots = normalizedShots(candidate.shots);
  if (!Array.isArray(candidate.shots) || shots.length !== candidate.shots.length || shots.length > 6) {
    return null;
  }
  const activeShot = stringOrNull(candidate.activeShotId);
  const activeShotId = shots.some((shot) => shot.id === activeShot) ? activeShot : (shots[0]?.id ?? null);
  const tab = LANDSCAPE_WORKFLOW_TABS.includes(candidate.activeWorkflowTab as LandscapeWorkflowTab)
    ? (candidate.activeWorkflowTab as LandscapeWorkflowTab)
    : "drawing";
  return {
    version: LANDSCAPE_DOCUMENT_VERSION,
    activeShotId,
    activeWorkflowTab: tab,
    shots,
    updatedAt: stringValue(candidate.updatedAt ?? candidate.savedAt, new Date().toISOString()),
    settings: normalizeSettings(candidate.settings),
    proposal: normalizeProposal(candidate.proposal),
    bomLineItems: normalizeBomLineItems(candidate.bomLineItems),
    procurement: normalizeProcurement(candidate.procurement),
    precon: normalizePrecon(candidate.precon),
  };
}

export function createLandscapeDocument(
  shots: DesignerShot[] = [],
  activeShotId: string | null = null,
  updatedAt = new Date().toISOString(),
): LandscapeDocumentV2 {
  return (
    normalizeLandscapeDocument({ version: 1, shots, activeShotId, updatedAt }) ?? {
      version: LANDSCAPE_DOCUMENT_VERSION,
      activeShotId: null,
      activeWorkflowTab: "drawing",
      shots: [],
      updatedAt,
      settings: defaultLandscapeSettings(),
      proposal: defaultLandscapeProposal(),
      bomLineItems: [],
      procurement: {},
      precon: defaultLandscapePrecon(),
    }
  );
}
