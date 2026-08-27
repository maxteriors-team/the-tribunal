"use client";

/**
 * Light Designer — the one place a rep designs lighting on a photo of the home.
 *
 * The rep uploads a house photo, sets the scale from a known measurement, then
 * draws the job: landscape fixtures from the workspace price book (uplights,
 * path lights, wall lights, underwater lights), glowing C9 roofline, mini-lights
 * on bushes and trees, and wreaths. Dusk is a slider, so the customer watches
 * own house light up.
 *
 * A job is rarely one photo. The rep adds as many shots as the house needs
 * (front elevation, back patio, the walkway) and each keeps its own drawing,
 * scale, and dusk; the thumbnail strip switches between them. Measurements are
 * totalled across every shot — the quote covers the whole job, not the photo
 * that happened to be on screen — and every drawn shot becomes a mockup on the
 * proposal.
 *
 * What the canvas produces is geometry — feet and counts, never money:
 *
 * - Holiday work is priced **server-side** into a live permanent-vs-seasonal
 *   comparison; "Client preview" renders the exact feet-free comparison the
 *   homeowner gets and "Save & share" mints a public link.
 * - Landscape fixtures resolve to real price-book items, so each one carries its
 *   SKU and bill-of-materials through to saved project pricing and the technician's
 *   parts list.
 *
 * Layout: tool/product palette (left), photo design stage (center), itemized
 * estimate + customer/share (right).
 */
import { keepPreviousData, useMutation, useQuery } from "@tanstack/react-query";
import {
  ArrowLeft,
  ArrowUp,
  Cable,
  CheckCircle2,
  Circle,
  ChevronDown,
  CircleDot,
  Copy,
  FileDown,
  FileText,
  Focus,
  Footprints,
  HelpCircle,
  ImagePlus,
  LampWallDown,
  Layers3,
  Mail,
  MessageSquareText,
  MousePointer2,
  Plus,
  Presentation,
  Printer,
  RefreshCcw,
  Ruler,
  Settings2,
  Sparkles,
  Trash2,
  TriangleAlert,
  Undo2,
  Waves,
  X,
  Zap,
} from "lucide-react";
import Link from "next/link";
import { Children, useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";

import { InventoryAvailabilityCard } from "@/components/estimator/inventory-availability-card";
import { LandscapeClientPreview } from "@/components/landscape-lighting/studio/client-preview";
import {
  DocumentActionButton,
  DocumentViewport,
} from "@/components/landscape-lighting/studio/document-viewport";
import {
  DrawingToolbar,
  type DrawingStudioAction,
} from "@/components/landscape-lighting/studio/drawing-toolbar";
import { PreconChecklist } from "@/components/landscape-lighting/studio/precon-checklist";
import {
  LandscapeBistroRunScheduleTable,
  LandscapeBomTable as LandscapeProcurementTable,
  LandscapeFixtureScheduleTable,
  type LandscapeBistroRunRow,
} from "@/components/landscape-lighting/studio/workflow-tables";
import { ConvertQuoteDialog } from "@/components/quotes/convert-quote-dialog";
import { QuoteEditDialog } from "@/components/quotes/quote-edit-dialog";
import { ContactCombobox } from "@/components/ui/contact-combobox";
import { estimatorApi } from "@/lib/api/estimator";
import { quotesApi } from "@/lib/api/quotes";
import { salesWizardApi } from "@/lib/api/sales-wizard";
import { DEFAULT_WORKSPACE_BRAND_NAME } from "@/lib/brand";
import {
  BISTRO_POLE_PRODUCT,
  buildBistroCatalog,
  buildCatalog,
  buildSavedBistroFallbacks,
  indexProducts,
} from "@/lib/estimator/catalog";
import { toEstimateCustomLines, type CustomLineDraft } from "@/lib/estimator/custom-lines";
import {
  designScale,
  designToEstimateInputs,
  hasDesign,
  runScale,
  sumEstimateInputs,
} from "@/lib/estimator/design";
import {
  calculateLandscapeCircuits,
  calculateLandscapeElectricalLoad,
  type LandscapeCircuitLoad,
  type LandscapeElectricalLoad,
} from "@/lib/estimator/electrical";
import { exportDesignJpeg } from "@/lib/estimator/export";
import {
  FIXTURE_TYPES,
  buildFixturePalette,
  hasLandscapeFixtures,
  landscapeWireLabel,
  resolveTierFixtures,
  resolveTierTransformer,
  resolveTierWire,
  type FixtureType,
} from "@/lib/estimator/fixtures";
import { polylineLength } from "@/lib/estimator/geometry";
import {
  defaultLandscapePrecon,
  defaultLandscapeProposal,
  defaultLandscapeSettings,
  normalizeLandscapeDocument,
} from "@/lib/estimator/landscape-document";
import {
  createLandscapeDraft,
  loadLandscapeDraft,
  saveLandscapeDraft,
  type LandscapeDraft,
  type LandscapeDraftState,
} from "@/lib/estimator/landscape-draft";
import {
  buildLandscapeProcurement,
  procurementRowsToSupplierCsv,
  procurementStateForRow,
  procurementSupplementFromSupplierRow,
  recountLandscapeProcurement,
  type LandscapeProcurementRow,
} from "@/lib/estimator/landscape-procurement";
import {
  buildLandscapeProposalPayload,
  hasUnpriceableBistroRuns,
  splitLandscapeFixturePricing,
} from "@/lib/estimator/landscape-proposal";
import {
  buildLandscapeSchedule as buildPerFixtureSchedule,
  copyScheduleSelectionToType,
  updateFixtureScheduleSelection,
  type LandscapeFixtureScheduleUpdate,
  type LandscapeScheduleRow,
} from "@/lib/estimator/landscape-schedule";
import { DEFAULT_FIXTURE_MARKER_COLOR } from "@/lib/estimator/marker-colors";
import { resolveSelectedPackage, packageName, seasonalTotal } from "@/lib/estimator/packages";
import { fileToPhoto } from "@/lib/estimator/photo";
import { DEFAULT_DUSK } from "@/lib/estimator/render";
import { SERVICES, clientThemeClass, type ServiceKey } from "@/lib/estimator/services";
import {
  buildManualSupplierCsvRows,
  buildSupplierCsvRows,
  downloadSupplierCsv,
  type SupplierCsvRow,
  type SupplierFixtureInput,
} from "@/lib/estimator/supplier-csv";
import {
  beamAngleFor,
  type Design,
  type DesignerShot,
  type LandscapeBomLineItem,
  type LandscapePaperSize,
  type LandscapePlanFit,
  type LandscapePreconState,
  type LandscapeProcurementState,
  type LandscapeProposalLineItem,
  type LandscapeProposalSettings,
  type PhotoInfo,
  type Product,
} from "@/lib/estimator/types";
import { queryKeys } from "@/lib/query-keys";
import { getApiErrorMessage } from "@/lib/utils/errors";
import { formatCurrency } from "@/lib/utils/number";
import type { EstimateRenderRequest, LinearFeetEstimateRequest } from "@/types/estimate";
import type { QuoteInventoryAvailability } from "@/types/inventory";
import type {
  CatalogItemResponse,
  ProposalDocument,
  ProposalWizardPayload,
  QuoteDetail,
  TierConfig,
} from "@/types/sales-wizard";

import { AIRenderModal } from "./ai-render";
import { ComparisonCard, type ComparisonView } from "./comparison-card";
import {
  EMPTY_DESIGN,
  editorReducer,
  initialEditorState,
  nextId,
  type EditorAction,
  type EditorState,
} from "./editor-store";
import { EstimatePanel } from "./estimate-panel";
import { LightCanvas } from "./light-canvas";
import { ServiceValueProps } from "./service-value-props";
import { ToolPalette } from "./tool-palette";
import "./estimator.css";

type ViewMode = "rep" | "client";

/**
 * How many photos one design session can carry. The cap keeps saved project
 * records bounded while covering the usual front, side, and back elevations.
 */
export const MAX_SHOTS = 6;

/** How the client's estimate link reaches them. */
type SendChannel = "email" | "sms";

export interface LandscapeProjectPersistenceAdapter {
  initialDraft: LandscapeDraft;
  onLandscapeDraftChange: (draft: LandscapeDraft, options?: { immediate?: boolean }) => void;
  persistenceStatus: {
    state: "loading" | "saved" | "pending" | "saving" | "error" | "conflict";
    label: string;
  };
  projectId?: string;
  projectName?: string;
  contactName?: string;
  contactId?: number | null;
  opportunityId?: string | null;
  serviceLocationId?: string | null;
  installationShotId?: string | null;
  onSelectInstallationShot?: (shotId: string) => Promise<void>;
  flushBeforeProposal?: () => Promise<unknown>;
  resetKey: number | string;
  activeWorkflowTab?: LandscapeWorkspaceTab;
  onActiveWorkflowTabChange?: (tab: LandscapeWorkspaceTab) => void;
}

interface LightDesignerProps {
  workspaceId: string;
  workspaceName?: string;
  workspaceLogoUrl?: string | null;
  /** Locks a dedicated lighting-project section to one service catalog. */
  focus?: "all" | "landscape" | "permanent";
  /**
   * Server-backed project state. When present, browser-only workspace restore is
   * disabled and every debounced drawing change is emitted to the project owner.
   */
  landscapeProject?: LandscapeProjectPersistenceAdapter;
}

// Params for the catalog probe: a feet=0 estimate that returns the workspace's
// decor catalog (and roofline rate) without needing a drawn design yet.
// Cents-exact rounding, matching the backend's ``round(value, 2)`` on money.
const round2 = (value: number) => Math.round(value * 100) / 100;

type PermanentComplexity = LinearFeetEstimateRequest["permanent_complexity"];
export const PERMANENT_COMPLEXITY_OPTIONS = [
  { value: "aerial", label: "Aerial Pics · 1.5×" },
  { value: "easy", label: "Easy" },
  { value: "standard", label: "Standard" },
  { value: "complex", label: "Complex" },
] as const satisfies readonly { value: PermanentComplexity; label: string }[];
const PERMANENT_COMPLEXITIES: readonly PermanentComplexity[] = PERMANENT_COMPLEXITY_OPTIONS.map(
  ({ value }) => value,
);

/**
 * Preserve a truthful scalar for servers/rows that cannot consume the measured
 * per-run map. Ties choose the harder run so a fallback never silently understates
 * a design; an unmeasured design retains the backward-compatible Standard default.
 */
export function dominantPermanentComplexity(
  measuredFeet: Readonly<Record<PermanentComplexity, number>>,
): PermanentComplexity {
  let dominant: PermanentComplexity = "standard";
  let longest = 0;
  for (const complexity of PERMANENT_COMPLEXITIES) {
    const measured = measuredFeet[complexity];
    if (measured > longest || (measured > 0 && measured === longest)) {
      dominant = complexity;
      longest = measured;
    }
  }
  return dominant;
}

const CATALOG_PARAMS: LinearFeetEstimateRequest = {
  feet: 0,
  channels: 0,
  takedown: false,
  storage: false,
  permanent_complexity: "standard",
  permanent_complexity_feet: {},
  proposal_side: "comparison",
  discount_amount: 0,
  per_ft_override: null,
  christmas_per_ft_override: null,
  christmas_items: {},
};

const LANDSCAPE_LEGEND = [
  { id: "uplight", label: "Uplight", detail: "2700 K", color: "#dc534b", Icon: ArrowUp },
  { id: "pathlight", label: "Path light", detail: "2700 K", color: "#d7a33e", Icon: Footprints },
  { id: "downlight", label: "Downlight", detail: "2700 K", color: "#477bb8", Icon: Focus },
  {
    id: "ingrade",
    label: "Well / in-grade",
    detail: "2700 K",
    color: "#4b9a70",
    Icon: CircleDot,
  },
  {
    id: "walllight",
    label: "Wall light",
    detail: "Core-drilled",
    color: "#d56f4f",
    Icon: LampWallDown,
  },
  {
    id: "underwater",
    label: "Underwater",
    detail: "Submersible",
    color: "#238eae",
    Icon: Waves,
  },
  {
    id: "transformer",
    label: "Transformer",
    detail: "Power equipment",
    color: "#8b67c8",
    Icon: Zap,
  },
] as const;

const LANDSCAPE_WORKSPACE_TABS = [
  { key: "drawing", label: "Drawing Sheet" },
  { key: "schedule", label: "Fixture Schedule" },
  { key: "bom", label: "BOM" },
  { key: "electrical", label: "Electrical" },
  { key: "proposal", label: "Proposal" },
  { key: "precon", label: "Pre-Con" },
] as const;

type LandscapeWorkspaceTab = (typeof LANDSCAPE_WORKSPACE_TABS)[number]["key"];
type AutosaveStatus = "loading" | "saving" | "saved" | "error";

const landscapeDraftSignature = (
  shots: DesignerShot[],
  activeShotId: string | null,
  liveState: LandscapeDraftState,
): string => JSON.stringify({ activeShotId, shots, ...liveState });

const parseLandscapeLiveState = (serialized: string): LandscapeDraftState =>
  JSON.parse(serialized) as LandscapeDraftState;

const landscapeStateFromDraft = (draft: LandscapeDraft): LandscapeDraftState => ({
  activeWorkflowTab: draft.activeWorkflowTab ?? "drawing",
  settings: draft.settings ?? defaultLandscapeSettings(),
  proposal: draft.proposal ?? defaultLandscapeProposal(),
  bomLineItems: draft.bomLineItems ?? [],
  procurement: draft.procurement ?? {},
  precon: draft.precon ?? defaultLandscapePrecon(),
});

interface LandscapeFixtureScheduleRow {
  id: string;
  label: string;
  productName: string | null;
  sku: string | null;
  count: number;
  beam: string;
  number?: number;
  itemId?: string;
  lampCatalogItemId?: string | null;
  accessories?: string[];
}

function LandscapeSheetTitleBlock({
  fixtureCount,
  bistroRunCount,
  calibrated,
  sheetNumber,
  workspaceName,
  workspaceLogoUrl,
  projectName,
  contactName,
}: {
  fixtureCount: number;
  bistroRunCount: number;
  calibrated: boolean;
  sheetNumber: number;
  workspaceName: string;
  workspaceLogoUrl: string | null;
  projectName: string;
  contactName: string;
}) {
  return (
    <aside className="ll-title-block" aria-label="Design sheet details">
      <div className="ll-title-brand">
        {workspaceLogoUrl ? (
          // eslint-disable-next-line @next/next/no-img-element -- workspace-configured logo URL
          <img src={workspaceLogoUrl} alt={workspaceName} />
        ) : (
          <span>{workspaceName}</span>
        )}
      </div>
      <dl>
        <div>
          <dt>Project</dt>
          <dd>{projectName}</dd>
        </div>
        <div>
          <dt>Site address</dt>
          <dd>Not added</dd>
        </div>
        <div>
          <dt>Client</dt>
          <dd>{contactName}</dd>
        </div>
        <div>
          <dt>Drawing</dt>
          <dd>Aerial landscape lighting plan</dd>
        </div>
        <div>
          <dt>Scale</dt>
          <dd>{calibrated ? "Set from drawing" : "Not set"}</dd>
        </div>
        <div>
          <dt>Date</dt>
          <dd>{new Date().toLocaleDateString()}</dd>
        </div>
        <div>
          <dt>Designed by</dt>
          <dd>{workspaceName}</dd>
        </div>
        <div>
          <dt>Fixtures</dt>
          <dd>{fixtureCount}</dd>
        </div>
        <div>
          <dt>Bistro runs</dt>
          <dd>{bistroRunCount}</dd>
        </div>
      </dl>
      <div className="ll-sheet-number">
        <span>Sheet</span>
        <strong>L-{sheetNumber}</strong>
      </div>
    </aside>
  );
}

function LandscapeLegendEntry({ entry }: { entry: (typeof LANDSCAPE_LEGEND)[number] }) {
  const { label, detail, color, Icon } = entry;
  return (
    <div className="ll-legend-row">
      <span className="ll-legend-symbol" style={{ color }}>
        <Icon aria-hidden="true" />
      </span>
      <span>
        <strong>{label}</strong>
        <small>{detail}</small>
      </span>
      <span aria-label="Quantity not set">0</span>
    </div>
  );
}

function LandscapeWelcome({
  onUpload,
  onDropFile,
  workspaceName,
  workspaceLogoUrl,
  projectName,
  contactName,
}: {
  onUpload: () => void;
  onDropFile: (file: File) => void;
  workspaceName: string;
  workspaceLogoUrl: string | null;
  projectName: string;
  contactName: string;
}) {
  const [dragActive, setDragActive] = useState(false);
  const acceptsFiles = (event: React.DragEvent) =>
    Array.from(event.dataTransfer.types).includes("Files");

  return (
    <section
      className={`est-welcome est-welcome-landscape${dragActive ? " drag-active" : ""}`}
      aria-label="Aerial plan file drop zone"
      onDragEnter={(event) => {
        if (!acceptsFiles(event)) return;
        event.preventDefault();
        setDragActive(true);
      }}
      onDragOver={(event) => {
        if (!acceptsFiles(event)) return;
        event.preventDefault();
        event.dataTransfer.dropEffect = "copy";
      }}
      onDragLeave={(event) => {
        if (event.currentTarget.contains(event.relatedTarget as Node | null)) return;
        setDragActive(false);
      }}
      onDrop={(event) => {
        if (!acceptsFiles(event)) return;
        event.preventDefault();
        setDragActive(false);
        const file = event.dataTransfer.files[0];
        if (file) onDropFile(file);
      }}
    >
      <div className="ll-empty-drafting-stage">
        <div className="ll-live-sheet ll-empty-sheet">
          <div className="ll-empty-sheet-main">
            <div className="ll-empty-sheet-frame">
              <span className="ll-sheet-kicker">New design · Sheet L-1</span>
              <div className="ll-empty-sheet-copy">
                <Layers3 aria-hidden="true" />
                <h1 id="ll-welcome-title">Start with a top-down aerial plan</h1>
                <p>
                  Upload a satellite, drone, or site-plan image viewed from directly above.
                  Street-level and elevation photos do not produce an accurate fixture or wiring
                  plan.
                </p>
                <span className="ll-drop-instruction" aria-live="polite">
                  {dragActive
                    ? "Release to place this aerial on Sheet L-1"
                    : "Drop top-down aerial image here"}
                </span>
                <button className="est-btn primary ll-upload-btn" type="button" onClick={onUpload}>
                  <ImagePlus aria-hidden="true" />
                  Upload aerial plan
                </button>
              </div>
              <div className="ll-empty-sheet-steps" aria-label="Aerial landscape lighting workflow">
                <span>
                  <strong>01</strong> Scale the aerial
                </span>
                <span>
                  <strong>02</strong> Place from above
                </span>
                <span>
                  <strong>03</strong> Present and quote
                </span>
              </div>
            </div>
            <div className="ll-fixture-legend ll-empty-legend" aria-label="Example fixture legend">
              <div className="ll-legend-title">
                <span>Fixture legend</span>
                <span>Qty</span>
              </div>
              {LANDSCAPE_LEGEND.map((entry) => (
                <LandscapeLegendEntry key={entry.label} entry={entry} />
              ))}
            </div>
          </div>
          <LandscapeSheetTitleBlock
            fixtureCount={0}
            bistroRunCount={0}
            calibrated={false}
            sheetNumber={1}
            workspaceName={workspaceName}
            workspaceLogoUrl={workspaceLogoUrl}
            projectName={projectName}
            contactName={contactName}
          />
        </div>
      </div>
    </section>
  );
}

function LandscapeDraftingToolbar({
  products,
  workspaceName,
  activeTool,
  design,
  hasPhoto,
  canUndo,
  markerColor,
  onMarkerColorChange,
  duskPreview,
  onTogglePreview,
  planFit,
  planOpacity,
  legendScale,
  sourceVoltage,
  toolsOpen,
  legendOpen,
  helpOpen,
  sheetSize,
  onSheetSizeChange,
  onPlaceAerial,
  onSelect,
  onSetScale,
  onPlaceFixture,
  onStartWiring,
  onUndo,
  onToggleTools,
  onToggleLegend,
  onToggleHelp,
  onOpenSchedule,
  onOpenElectrical,
  onPresent,
  onRender,
  onPrint,
  studio = false,
  studioSettings,
  onStudioAction,
}: {
  products: Product[];
  workspaceName: string;
  activeTool: EditorState["tool"];
  design: Design;
  hasPhoto: boolean;
  canUndo: boolean;
  markerColor: string | null;
  onMarkerColorChange: (color: string) => void;
  duskPreview: boolean;
  onTogglePreview: () => void;
  planFit: LandscapePlanFit;
  planOpacity: number;
  legendScale: number;
  sourceVoltage: number;
  toolsOpen: boolean;
  legendOpen: boolean;
  helpOpen: boolean;
  sheetSize: LandscapePaperSize;
  onSheetSizeChange: (value: LandscapePaperSize) => void;
  onPlaceAerial: () => void;
  onSelect: () => void;
  onSetScale: () => void;
  onPlaceFixture: (product: Product) => void;
  onStartWiring: (product: Product) => void;
  onUndo: () => void;
  onToggleTools: () => void;
  onToggleLegend: () => void;
  onToggleHelp: () => void;
  onOpenSchedule: () => void;
  onOpenElectrical: () => void;
  onPresent: () => void;
  onRender: () => void;
  onPrint: () => void;
  studio?: boolean;
  studioSettings?: {
    fixtureNumbersVisible: boolean;
    measurementsVisible: boolean;
    legendVisible: boolean;
    halosVisible: boolean;
  };
  onStudioAction?: (action: DrawingStudioAction) => void;
}) {
  const wireProduct = products.find((product) => product.style === "wire");
  const activeDrawProduct =
    activeTool.type === "draw"
      ? products.find((product) => product.id === activeTool.productId)
      : undefined;
  const fixtureTools = LANDSCAPE_LEGEND.flatMap((legend) => {
    const product = products.find((candidate) =>
      legend.id === "transformer"
        ? candidate.style === "transformer"
        : candidate.target.field === "landscape" && candidate.target.fixtureType === legend.id,
    );
    return product ? [{ ...legend, product }] : [];
  });
  const bistroTools = products.filter(
    (product) =>
      !product.paletteHidden &&
      product.target.field === "bistro" &&
      product.target.installation !== undefined,
  );
  const hasBistroRun = design.runs.some((run) =>
    bistroTools.some((product) => product.id === run.productId),
  );
  const bistroPoleTool = hasBistroRun
    ? products.find((product) => product.target.field === "bistroPole")
    : undefined;

  if (studio && studioSettings && onStudioAction) {
    return (
      <DrawingToolbar
        workspaceName={workspaceName}
        paperSize={sheetSize}
        activeAction={
          activeTool.type === "select"
            ? "select"
            : activeTool.type === "pan"
              ? "pan"
              : activeTool.type === "draw" && activeDrawProduct?.style === "wire"
                ? "wire"
                : activeTool.type === "highlight"
                  ? "highlight"
                  : undefined
        }
        hasAerial={hasPhoto}
        hasDrawing={design.runs.length > 0 || design.items.length > 0}
        hasPlanSymbols={Boolean(
          design.annotations?.length ||
          design.measurements?.length ||
          design.highlights?.length ||
          design.arrows?.length,
        )}
        canUndo={canUndo}
        canWire={Boolean(wireProduct)}
        canRender={hasPhoto}
        duskPreview={duskPreview}
        renderDisabledReason={
          hasPhoto ? undefined : "Place an aerial before creating a dusk render."
        }
        markerColor={markerColor}
        planFit={planFit}
        planOpacity={planOpacity}
        legendScale={legendScale}
        sourceVoltage={sourceVoltage}
        fixtureNumbersVisible={studioSettings.fixtureNumbersVisible}
        measurementsVisible={studioSettings.measurementsVisible}
        legendVisible={studioSettings.legendVisible}
        halosVisible={studioSettings.halosVisible}
        onPaperSizeChange={onSheetSizeChange}
        onMarkerColorChange={onMarkerColorChange}
        onAction={(action) => {
          if (action === "place-aerial") onPlaceAerial();
          else if (action === "select") onSelect();
          else if (action === "undo") onUndo();
          else if (action === "set-scale") onSetScale();
          else if (action === "wire") {
            if (wireProduct) onStartWiring(wireProduct);
          } else if (action === "present") onPresent();
          else if (action === "toggle-preview") onTogglePreview();
          else if (action === "render") onRender();
          else if (action === "download-pdf") onPrint();
          else if (action === "help") onToggleHelp();
          else onStudioAction(action);
        }}
        fixtureTools={[
          ...fixtureTools.map(({ id, label, product, Icon }) => ({
            id,
            label,
            icon: Icon,
            active: activeTool.type === "place" && activeTool.productId === product.id,
            onSelect: () => onPlaceFixture(product),
          })),
          ...bistroTools.map((product) => ({
            id: product.id,
            label: product.name,
            icon: Cable,
            group: "bistro" as const,
            active: activeTool.type === "draw" && activeTool.productId === product.id,
            onSelect: () => onStartWiring(product),
          })),
          ...(bistroPoleTool
            ? [
                {
                  id: bistroPoleTool.id,
                  label: "Bistro pole",
                  icon: CircleDot,
                  group: "bistro" as const,
                  active: activeTool.type === "place" && activeTool.productId === bistroPoleTool.id,
                  onSelect: () => onPlaceFixture(bistroPoleTool),
                },
              ]
            : []),
        ]}
      />
    );
  }

  return (
    <section className="ll-drafting-toolbar" aria-label="Drawing sheet tools">
      <div className="ll-toolbar-primary">
        <div className="ll-core-tools" role="group" aria-label="Plan tools">
          <button
            className={`ll-toolbar-button${activeTool.type === "select" ? " active" : ""}`}
            type="button"
            aria-pressed={activeTool.type === "select"}
            title="Select and move plan items"
            disabled={!hasPhoto}
            onClick={onSelect}
          >
            <MousePointer2 aria-hidden="true" />
            Select
          </button>
          <button
            className={`ll-toolbar-button${activeTool.type === "calibrate" ? " active" : ""}`}
            type="button"
            aria-pressed={activeTool.type === "calibrate"}
            title="Set drawing scale"
            disabled={!hasPhoto}
            onClick={onSetScale}
          >
            <Ruler aria-hidden="true" />
            Set scale
          </button>
          <button
            className={`ll-toolbar-button${
              activeTool.type === "draw" && activeTool.productId === wireProduct?.id
                ? " active"
                : ""
            }`}
            type="button"
            aria-pressed={activeTool.type === "draw" && activeTool.productId === wireProduct?.id}
            title="Draw a transformer wire circuit"
            disabled={!hasPhoto || !wireProduct}
            onClick={() => wireProduct && onStartWiring(wireProduct)}
          >
            <Cable aria-hidden="true" />
            Wire
          </button>
          <button
            className="ll-toolbar-button ll-icon-button"
            type="button"
            title="Undo last drawing change"
            disabled={!canUndo}
            onClick={onUndo}
          >
            <Undo2 aria-hidden="true" />
            <span>Undo</span>
          </button>
        </div>

        {hasPhoto ? (
          <div
            className="ll-fixture-tools"
            role="group"
            aria-label="Place fixtures and draw bistro runs"
          >
            <span className="ll-fixture-tools-label">Add</span>
            {fixtureTools.map(({ id, label, product, color, Icon }) => {
              const active = activeTool.type === "place" && activeTool.productId === product.id;
              return (
                <button
                  className={`ll-fixture-tool${active ? " active" : ""}`}
                  type="button"
                  key={id}
                  title={product.name}
                  aria-label={`${label}: ${product.name}`}
                  aria-pressed={active}
                  onClick={() => onPlaceFixture(product)}
                >
                  <Icon aria-hidden="true" style={{ color }} />
                  <span>{label}</span>
                </button>
              );
            })}
            {bistroTools.map((product) => {
              const active = activeTool.type === "draw" && activeTool.productId === product.id;
              return (
                <button
                  className={`ll-fixture-tool${active ? " active" : ""}`}
                  type="button"
                  key={product.id}
                  title={`Draw ${product.name}`}
                  aria-pressed={active}
                  onClick={() => onStartWiring(product)}
                >
                  <Cable aria-hidden="true" />
                  <span>{product.name}</span>
                </button>
              );
            })}
            {bistroPoleTool ? (
              <button
                className={`ll-fixture-tool${
                  activeTool.type === "place" && activeTool.productId === bistroPoleTool.id
                    ? " active"
                    : ""
                }`}
                type="button"
                title="Place a billable support pole on a Bistro run"
                aria-pressed={
                  activeTool.type === "place" && activeTool.productId === bistroPoleTool.id
                }
                onClick={() => onPlaceFixture(bistroPoleTool)}
              >
                <CircleDot aria-hidden="true" />
                <span>Bistro pole</span>
              </button>
            ) : null}
          </div>
        ) : (
          <span className="ll-toolbar-empty-hint">
            Add an aerial photo to start placing fixtures.
          </span>
        )}

        <div className="ll-toolbar-end">
          <button
            className={`ll-toolbar-button${legendOpen ? " active" : ""}`}
            type="button"
            aria-pressed={legendOpen}
            title="Show or hide fixture legend"
            disabled={!hasPhoto}
            onClick={onToggleLegend}
          >
            <Layers3 aria-hidden="true" />
            Legend
          </button>
          <button
            className={`ll-toolbar-button${toolsOpen ? " active" : ""}`}
            type="button"
            aria-expanded={toolsOpen}
            title="Open fixture and drawing details"
            disabled={!hasPhoto}
            onClick={onToggleTools}
          >
            <Settings2 aria-hidden="true" />
            Details
          </button>
          <details className="ll-toolbar-more">
            <summary>
              More
              <ChevronDown aria-hidden="true" />
            </summary>
            <div className="ll-toolbar-menu">
              <label className="ll-sheet-size-control">
                <span>Sheet size</span>
                <select
                  value={sheetSize}
                  onChange={(event) => onSheetSizeChange(event.target.value as LandscapePaperSize)}
                >
                  <option value="tabloid">Tabloid, 17 × 11</option>
                  <option value="super-b">Super B, 19 × 13</option>
                  <option value="letter">Letter, 11 × 8.5</option>
                  <option value="arch-c">ARCH C, 24 × 18</option>
                  <option value="arch-d">ARCH D, 36 × 24</option>
                </select>
              </label>
              <button type="button" onClick={onOpenSchedule}>
                <FileText aria-hidden="true" />
                Fixture schedule
              </button>
              <button type="button" onClick={onOpenElectrical}>
                <Zap aria-hidden="true" />
                Electrical load
              </button>
              <button type="button" onClick={onPresent}>
                <Presentation aria-hidden="true" />
                Present plan
              </button>
              <button type="button" onClick={onPrint}>
                <FileDown aria-hidden="true" />
                Download PDF
              </button>
              <button type="button" aria-expanded={helpOpen} onClick={onToggleHelp}>
                <HelpCircle aria-hidden="true" />
                How to use the plan
              </button>
            </div>
          </details>
        </div>
      </div>
      {helpOpen ? (
        <div className="ll-toolbar-help" role="status">
          Set one known top-down distance, choose a fixture icon, then click the aerial to place it.
          Select a fixture to move or aim it from above. Draft changes save automatically.
        </div>
      ) : null}
    </section>
  );
}

function LandscapeSheetBar({
  shots,
  activeShotId,
  installationShotId,
  atShotCap,
  onSelect,
  onSelectInstallation,
  onAdd,
  onDuplicate,
  onRemove,
}: {
  shots: DesignerShot[];
  activeShotId: string | null;
  installationShotId?: string | null;
  atShotCap: boolean;
  onSelect: (id: string) => void;
  onSelectInstallation?: (id: string) => void;
  onAdd: () => void;
  onDuplicate: () => void;
  onRemove: () => void;
}) {
  return (
    <div className="ll-sheet-tabs" aria-label="Aerial drawing sheets">
      <span className="ll-sheet-tabs-label">Sheets</span>
      {!shots.length ? (
        <button type="button" className="active" aria-current="page" disabled>
          L-1
        </button>
      ) : null}
      {Children.toArray(
        shots.map((shot, index) => (
          <span key={shot.id} className="inline-flex items-center">
            <button
              type="button"
              className={shot.id === activeShotId ? "active" : ""}
              aria-current={shot.id === activeShotId ? "page" : undefined}
              onClick={() => onSelect(shot.id)}
            >
              L-{index + 1}
            </button>
            {onSelectInstallation ? (
              <button
                type="button"
                className={shot.id === installationShotId ? "active" : ""}
                aria-pressed={shot.id === installationShotId}
                aria-label={`Use L-${index + 1} as installation sheet`}
                title="Use as installation sheet"
                onClick={() => onSelectInstallation(shot.id)}
              >
                {shot.id === installationShotId ? "Install ✓" : "Install"}
              </button>
            ) : null}
          </span>
        )),
      )}
      <button type="button" disabled={atShotCap} onClick={onAdd}>
        <Plus aria-hidden="true" />
        Add sheet
      </button>
      <button type="button" disabled={!shots.length || atShotCap} onClick={onDuplicate}>
        <Copy aria-hidden="true" />
        Duplicate sheet
      </button>
      <button type="button" disabled={!shots.length} onClick={onRemove}>
        <Trash2 aria-hidden="true" />
        Delete sheet
      </button>
    </div>
  );
}

function LandscapeLiveLegend({
  rows,
  position,
  scale,
}: {
  rows: LandscapeFixtureScheduleRow[];
  position: { x: number; y: number };
  scale: number;
}) {
  return (
    <div
      className="ll-fixture-legend ll-live-legend"
      aria-label="Fixture legend"
      style={{
        left: position.x,
        bottom: position.y,
        transform: `scale(${scale})`,
        transformOrigin: "bottom left",
      }}
    >
      <div className="ll-legend-title">
        <span>Fixture legend</span>
        <span>Qty</span>
      </div>
      {rows.length ? (
        Children.toArray(
          rows.map((row) => {
            const legend = LANDSCAPE_LEGEND.find((entry) => entry.id === row.id);
            const Icon = legend?.Icon ?? CircleDot;
            return (
              <div key={row.id} className="ll-legend-row">
                <span
                  className="ll-legend-symbol"
                  style={{ color: legend?.color ?? "#8a651d" }}
                  aria-hidden="true"
                >
                  <Icon />
                </span>
                <span>
                  <strong>{row.label}</strong>
                  <small>{row.beam}</small>
                </span>
                <span>{row.count}</span>
              </div>
            );
          }),
        )
      ) : (
        <div className="ll-legend-empty">Place fixtures to populate this legend.</div>
      )}
    </div>
  );
}

function LandscapeWorkspaceNav({
  activeTab,
  onChange,
}: {
  activeTab: LandscapeWorkspaceTab;
  onChange: (tab: LandscapeWorkspaceTab) => void;
}) {
  return (
    <nav className="ll-builder-tabs" aria-label="Landscape lighting project sections">
      {LANDSCAPE_WORKSPACE_TABS.map((tab) => (
        <button
          key={tab.key}
          type="button"
          className={activeTab === tab.key ? "active" : ""}
          aria-current={activeTab === tab.key ? "page" : undefined}
          onClick={() => onChange(tab.key)}
        >
          {tab.label}
        </button>
      ))}
    </nav>
  );
}

function LandscapeEmptyPanel({
  title,
  description,
  onUpload,
}: {
  title: string;
  description: string;
  onUpload: () => void;
}) {
  return (
    <div className="ll-panel-empty">
      <FileText aria-hidden="true" />
      <h2>{title}</h2>
      <p>{description}</p>
      <button className="est-btn primary" type="button" onClick={onUpload}>
        <ImagePlus aria-hidden="true" />
        Upload aerial plan
      </button>
    </div>
  );
}

function LandscapeManualBomTable({
  supplierRows,
  lineItems,
  onLineItemsChange,
}: {
  supplierRows: SupplierCsvRow[];
  lineItems: LandscapeBomLineItem[];
  onLineItemsChange: (lineItems: LandscapeBomLineItem[]) => void;
}) {
  const updateLine = (id: string, update: Partial<Omit<LandscapeBomLineItem, "id">>) => {
    onLineItemsChange(lineItems.map((line) => (line.id === id ? { ...line, ...update } : line)));
  };
  const hasRows = supplierRows.length > 0 || lineItems.length > 0;

  return (
    <section className="ll-bom-lines" aria-labelledby="ll-bom-lines-heading">
      <div className="ll-bom-lines-heading">
        <div>
          <h3 id="ll-bom-lines-heading">Additional materials</h3>
          <p>Add materials that are not represented by plan fixtures or traced wire.</p>
        </div>
        <button
          type="button"
          className="est-btn"
          disabled={lineItems.length >= 100}
          onClick={() =>
            onLineItemsChange([
              ...lineItems,
              { id: nextId("bom-line"), description: "", sku: "", quantity: 1, unit: "each" },
            ])
          }
        >
          <Plus aria-hidden="true" />
          Add line item
        </button>
      </div>

      {hasRows ? (
        <div className="ll-data-table-wrap">
          <table className="ll-data-table ll-bom-table">
            <caption className="sr-only">Bill of materials</caption>
            <thead>
              <tr>
                <th scope="col">Item</th>
                <th scope="col">SKU</th>
                <th scope="col">Quantity</th>
                <th scope="col">Unit</th>
                <th scope="col">Source or action</th>
              </tr>
            </thead>
            <tbody>
              {supplierRows.map((row, index) => (
                <tr key={`${row.supplier}:${row.sku}:${row.description}:${index}`}>
                  <td>
                    <strong>{row.description}</strong>
                    <span>{row.manufacturer || row.supplier || row.planSource}</span>
                  </td>
                  <td>
                    {row.sku || "Not assigned"}
                    <span>{row.status}</span>
                  </td>
                  <td>{row.needed ?? row.quantity}</td>
                  <td>{row.unit}</td>
                  <td>
                    <span className="ll-bom-source">Plan</span>
                  </td>
                </tr>
              ))}
              {lineItems.map((line, index) => (
                <tr key={line.id} className="ll-bom-manual-row">
                  <td>
                    <label>
                      <span className="sr-only">BOM line item {index + 1} description</span>
                      <input
                        className="ll-bom-description-input"
                        value={line.description}
                        maxLength={500}
                        placeholder="Description"
                        onChange={(event) =>
                          updateLine(line.id, { description: event.target.value })
                        }
                      />
                    </label>
                  </td>
                  <td>
                    <label>
                      <span className="sr-only">BOM line item {index + 1} SKU</span>
                      <input
                        value={line.sku}
                        maxLength={160}
                        placeholder="Optional SKU"
                        onChange={(event) => updateLine(line.id, { sku: event.target.value })}
                      />
                    </label>
                  </td>
                  <td>
                    <label>
                      <span className="sr-only">BOM line item {index + 1} quantity</span>
                      <input
                        className="ll-bom-quantity-input"
                        type="number"
                        inputMode="decimal"
                        min="0"
                        max="100000"
                        step={line.unit === "ft" ? "0.1" : "1"}
                        value={line.quantity}
                        placeholder="0"
                        onChange={(event) =>
                          updateLine(line.id, {
                            quantity: Math.min(
                              100_000,
                              Math.max(0, Number(event.target.value) || 0),
                            ),
                          })
                        }
                      />
                    </label>
                  </td>
                  <td>
                    <label>
                      <span className="sr-only">BOM line item {index + 1} unit</span>
                      <select
                        value={line.unit}
                        onChange={(event) =>
                          updateLine(line.id, { unit: event.target.value === "ft" ? "ft" : "each" })
                        }
                      >
                        <option value="each">each</option>
                        <option value="ft">ft</option>
                      </select>
                    </label>
                  </td>
                  <td>
                    <button
                      type="button"
                      className="est-btn ghost ll-bom-line-remove"
                      aria-label={`Remove BOM line item ${index + 1}${line.description ? `: ${line.description}` : ""}`}
                      onClick={() =>
                        onLineItemsChange(lineItems.filter((item) => item.id !== line.id))
                      }
                    >
                      <Trash2 aria-hidden="true" />
                      <span>Remove</span>
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="ll-panel-inline-empty">
          No additional materials yet. Add an unplaced item when needed.
        </div>
      )}
    </section>
  );
}

const formatWatts = (watts: number) => `${Number.isInteger(watts) ? watts : watts.toFixed(1)} W`;

function LandscapeElectricalSummary({
  load,
  circuits,
}: {
  load: LandscapeElectricalLoad;
  circuits: LandscapeCircuitLoad[];
}) {
  const statusCopy: Record<LandscapeElectricalLoad["status"], string> = {
    empty: "Place fixture icons on the drawing to calculate connected load.",
    incomplete: "One or more placed fixture types are missing a watt value in the catalog.",
    "transformer-needed": "Place a transformer icon to compare connected load with capacity.",
    "within-capacity": "Connected load is within the placed transformer capacity.",
    "limited-headroom": "Less than 20% spare transformer capacity remains.",
    "over-capacity": "Connected load exceeds the placed transformer capacity.",
  };
  const circuitStatusCopy: Record<LandscapeCircuitLoad["status"], string> = {
    empty: "No fixtures assigned",
    incomplete: "Fixture watts missing",
    "transformer-needed": "Assign transformer",
    "scale-needed": "Set drawing scale",
    "within-range": "Within range",
    "review-drop": "Review voltage drop",
    "high-drop": "High voltage drop",
  };

  return (
    <>
      <div className="ll-electrical-metrics" aria-label="Electrical load summary">
        <div>
          <span>Connected load</span>
          <strong>{formatWatts(load.connectedWatts)}</strong>
        </div>
        <div>
          <span>Current at 12 V</span>
          <strong>{load.currentAmps.toFixed(2)} A</strong>
        </div>
        <div>
          <span>Transformer capacity</span>
          <strong>
            {load.transformerCapacityWatts > 0
              ? formatWatts(load.transformerCapacityWatts)
              : "Not placed"}
          </strong>
        </div>
        <div>
          <span>Capacity remaining</span>
          <strong>
            {load.remainingCapacityWatts === null
              ? "Not available"
              : formatWatts(load.remainingCapacityWatts)}
          </strong>
        </div>
      </div>

      <div className={`ll-load-status ${load.status}`} role="status">
        <strong>{statusCopy[load.status]}</strong>
        {load.utilizationPercent !== null ? (
          <div className="ll-load-progress">
            <progress
              max={100}
              value={Math.min(load.utilizationPercent, 100)}
              aria-label="Transformer capacity used"
            />
            <span>{load.utilizationPercent.toFixed(1)}% used</span>
          </div>
        ) : null}
      </div>

      {load.rows.length ? (
        <div className="ll-data-table-wrap">
          <table className="ll-data-table ll-electrical-table">
            <caption className="sr-only">Connected fixture load by type</caption>
            <thead>
              <tr>
                <th scope="col">Fixture</th>
                <th scope="col">Quantity</th>
                <th scope="col">Watts each</th>
                <th scope="col">Connected load</th>
              </tr>
            </thead>
            <tbody>
              {load.rows.map((row) => (
                <tr key={row.id}>
                  <td>
                    <strong>{row.label}</strong>
                    {row.productName ? <span>{row.productName}</span> : null}
                  </td>
                  <td>{row.quantity}</td>
                  <td>{row.wattsEach === null ? "Missing" : formatWatts(row.wattsEach)}</td>
                  <td>{row.totalWatts === null ? "Missing" : formatWatts(row.totalWatts)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      <div className="ll-electrical-section-heading">
        <div>
          <span>Field wiring</span>
          <h3>Transformer circuits</h3>
        </div>
        <strong>
          {circuits.length} {circuits.length === 1 ? "circuit" : "circuits"}
        </strong>
      </div>
      {circuits.length ? (
        <div className="ll-data-table-wrap">
          <table className="ll-data-table ll-circuit-table">
            <caption className="sr-only">Wire circuit load and voltage-drop estimates</caption>
            <thead>
              <tr>
                <th scope="col">Circuit</th>
                <th scope="col">Fixtures</th>
                <th scope="col">Route</th>
                <th scope="col">Wire</th>
                <th scope="col">Load</th>
                <th scope="col">Tap</th>
                <th scope="col">Drop</th>
                <th scope="col">End voltage</th>
                <th scope="col">Minimum</th>
              </tr>
            </thead>
            <tbody>
              {circuits.map((circuit) => (
                <tr key={circuit.id}>
                  <td>
                    <strong>{circuit.label}</strong>
                    <span className={`ll-circuit-status ${circuit.status}`}>
                      {circuitStatusCopy[circuit.status]}
                      {circuit.usedDefaultWatts ? " (default watts)" : ""}
                    </span>
                  </td>
                  <td>{circuit.fixtureCount}</td>
                  <td>
                    {circuit.lengthFeet === null
                      ? "Not scaled"
                      : `${circuit.lengthFeet.toFixed(1)} ft`}
                  </td>
                  <td>{landscapeWireLabel(circuit.wireGauge)}</td>
                  <td>{formatWatts(circuit.connectedWatts)}</td>
                  <td>{circuit.sourceVoltage} V</td>
                  <td>
                    {circuit.voltageDrop === null
                      ? "Pending"
                      : `${circuit.voltageDrop.toFixed(2)} V (${circuit.voltageDropPercent?.toFixed(1)}%)`}
                  </td>
                  <td>
                    {circuit.estimatedEndVoltage === null
                      ? "Pending"
                      : `${circuit.estimatedEndVoltage.toFixed(2)} V`}
                  </td>
                  <td>{circuit.minimumVoltage.toFixed(1)} V</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="ll-panel-inline-empty">
          Draw a wire circuit on the Drawing Sheet, then assign its transformer and fixtures in
          Details.
        </div>
      )}

      <p className="ll-panel-footnote">
        Connected load uses fixture watts carried in the current Tribunal price book. Where
        explicitly configured, unresolved fixtures use the shown planning default and remain
        labeled. Voltage drop is a planning estimate, not field-verified; confirm installed route
        and voltage before closeout.
      </p>
    </>
  );
}

function LandscapeProposalPanel({
  projectName,
  contactName,
  mockupImage,
  aiImage,
  aiRenderDisabledReason,
  onAIRender,
  shots,
  rows,
  circuits,
  bistroRows,
  previews,
  previewsPending,
  tiers,
  document,
  inventoryAvailability,
  inventoryAvailabilityPending,
  inventoryAvailabilityError,
  selectedTierKey,
  selectedCarePlanKey,
  wireItems,
  additionalLineItems,
  pricingPending,
  pricingError,
  onRetryPricing,
  onSelectTier,
  onSelectCarePlan,
  onAdditionalLineItemsChange,
  onCreateQuote,
  createQuotePending,
  createQuoteError,
  createdQuote,
  quoteDisabledReason,
  onDeliverQuote,
  deliveryPending,
  deliveryStatus,
}: {
  projectName: string;
  contactName?: string;
  mockupImage: string | null;
  aiImage: string | null;
  aiRenderDisabledReason: string | null;
  onAIRender: () => void;
  shots: DesignerShot[];
  rows: LandscapeFixtureScheduleRow[];
  circuits: LandscapeCircuitLoad[];
  bistroRows: LandscapeBistroRunRow[];
  previews: Record<string, string>;
  previewsPending: boolean;
  tiers: TierConfig[];
  document: ProposalDocument | undefined;
  inventoryAvailability: QuoteInventoryAvailability | undefined;
  inventoryAvailabilityPending: boolean;
  inventoryAvailabilityError: string | null;
  selectedTierKey: string | null;
  selectedCarePlanKey: string | null;
  wireItems: Map<10 | 12, CatalogItemResponse | null>;
  additionalLineItems: LandscapeProposalLineItem[];
  pricingPending: boolean;
  pricingError: string | null;
  onRetryPricing: () => void;
  onSelectTier: (tierKey: string) => void;
  onSelectCarePlan: (carePlanKey: string | null) => void;
  onAdditionalLineItemsChange: (items: LandscapeProposalLineItem[]) => void;
  onCreateQuote: () => void;
  createQuotePending: boolean;
  createQuoteError: string | null;
  createdQuote: QuoteDetail | null;
  quoteDisabledReason: string | null;
  onDeliverQuote: (channel: "email" | "sms") => void;
  deliveryPending: boolean;
  deliveryStatus: string | null;
}) {
  const selectedTier = (document?.tiers ?? []).find((tier) => tier.key === selectedTierKey) ?? null;
  const selectedCarePlan =
    (document?.care_plan?.options ?? []).find((option) => option.key === selectedCarePlanKey) ??
    null;
  const bistroPricing = document?.bistro?.pricing_mode === "installation" ? document.bistro : null;
  const estimateTotal =
    document?.grand_financed_total ?? selectedTier?.pricing.financed_total ?? null;
  const wireTotals = new Map<8 | 10 | 12 | 14, number | null>();
  for (const circuit of circuits) {
    const previous = wireTotals.get(circuit.wireGauge);
    wireTotals.set(
      circuit.wireGauge,
      previous === null || circuit.lengthFeet === null
        ? null
        : (previous ?? 0) + circuit.lengthFeet,
    );
  }
  const quoteFixtureRows = rows.filter((row) => row.id !== "transformer");
  const [paymentTermsOpen, setPaymentTermsOpen] = useState(false);

  return (
    <section
      id="landscape-quote-builder"
      className="ll-workspace-panel"
      aria-labelledby="ll-proposal-title"
      tabIndex={-1}
    >
      <div className="ll-panel-sheet ll-proposal-preview">
        <header className="ll-panel-heading">
          <div>
            <span>Current design, customer, and CRM pricing</span>
            <h2 id="ll-proposal-title">Landscape Lighting Quote Builder</h2>
          </div>
          {estimateTotal !== null ? <strong>{formatCurrency(estimateTotal)}</strong> : null}
        </header>

        <LandscapeClientPreview
          projectName={projectName}
          contactName={contactName}
          mockupImage={mockupImage}
          aiImage={aiImage}
          fixtureCount={quoteFixtureRows.reduce((total, row) => total + row.count, 0)}
          bistroRunCount={bistroRows.length}
          packageName={selectedTier ? (selectedTier.name ?? selectedTier.label) : null}
          priceLabel={selectedTier ? formatCurrency(selectedTier.pricing.cash_total) : null}
          aiRenderDisabledReason={aiRenderDisabledReason}
          onAIRender={onAIRender}
        />

        <fieldset id="landscape-fixture-package" className="ll-proposal-fieldset">
          <legend>Fixture package</legend>
          <p>
            Switch packages without redrawing. Every plan fixture resolves to that tier’s catalog
            item.
          </p>
          <div className="ll-package-options">
            {tiers.map((tier) => {
              const previewTier = (document?.tiers ?? []).find(
                (candidate) => candidate.key === tier.key,
              );
              const selected = tier.key === selectedTierKey;
              return (
                <button
                  key={tier.key}
                  className={selected ? "selected" : ""}
                  type="button"
                  aria-pressed={selected}
                  onClick={() => onSelectTier(tier.key)}
                >
                  <span>{tier.tab || tier.label || tier.key}</span>
                  <strong>
                    {previewTier
                      ? formatCurrency(previewTier.pricing.cash_total)
                      : pricingPending
                        ? "Pricing…"
                        : "Add fixtures to price"}
                  </strong>
                  <small>CRM price book</small>
                </button>
              );
            })}
          </div>
        </fieldset>

        {pricingError ? (
          <div className="ll-proposal-error" role="alert">
            <span>{pricingError}</span>
            <button className="est-btn" type="button" onClick={onRetryPricing}>
              Retry pricing
            </button>
          </div>
        ) : null}

        <InventoryAvailabilityCard
          availability={inventoryAvailability}
          pending={inventoryAvailabilityPending}
          error={inventoryAvailabilityError}
        />

        <div className="ll-proposal-section">
          <div className="ll-proposal-section-heading">
            <div>
              <span>Selected package</span>
              <h3>Fixture pricing</h3>
            </div>
            <strong>
              {quoteFixtureRows.reduce((total, row) => total + row.count, 0)} fixtures
            </strong>
          </div>
          {quoteFixtureRows.length ? (
            <div className="ll-data-table-wrap">
              <table className="ll-data-table ll-proposal-price-table">
                <caption className="sr-only">Fixture pricing for the selected package</caption>
                <thead>
                  <tr>
                    <th scope="col">Fixture</th>
                    <th scope="col">Qty</th>
                    <th scope="col">Proposal unit</th>
                    <th scope="col">Line total</th>
                  </tr>
                </thead>
                <tbody>
                  {quoteFixtureRows.map((row) => {
                    const line = (selectedTier?.lines ?? []).find(
                      (candidate) => candidate.item_id === row.sku,
                    );
                    return (
                      <tr key={row.id}>
                        <td>
                          <strong>{row.label}</strong>
                          <span>{row.productName ?? "Not sold in this package"}</span>
                        </td>
                        <td>{row.count}</td>
                        <td>{line ? formatCurrency(line.unit_price) : "Not priced"}</td>
                        <td>{line ? formatCurrency(line.line_total) : "Not priced"}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="ll-panel-inline-empty">
              {bistroRows.length
                ? "No landscape fixtures selected; this estimate contains Bistro lighting only."
                : "Place fixtures on the Drawing Sheet to price them."}
            </div>
          )}
        </div>

        {bistroRows.length ? (
          <div className="ll-proposal-section">
            <div className="ll-proposal-section-heading">
              <div>
                <span>Saved with the drawing</span>
                <h3>Bistro lighting layout</h3>
              </div>
              <strong>{bistroRows.length} runs</strong>
            </div>
            <LandscapeBistroRunScheduleTable rows={bistroRows} />
            {bistroPricing ? (
              <div className="ll-wire-price-list" aria-label="Bistro estimate breakdown">
                {(bistroPricing.installations ?? []).flatMap((installation) => [
                  <div key={`${installation.installation}-lights`}>
                    <span>
                      <strong>{installation.label} lights</strong>
                      <small>
                        {Number.isInteger(installation.feet)
                          ? installation.feet
                          : installation.feet.toFixed(1)}{" "}
                        measured ft
                      </small>
                    </span>
                    <span>
                      <strong>{formatCurrency(installation.lights_cost)}</strong>
                      <small>
                        {formatCurrency(installation.lights_cost / installation.feet)}/ft
                      </small>
                    </span>
                  </div>,
                  ...(installation.pole_count
                    ? [
                        <div key={`${installation.installation}-poles`}>
                          <span>
                            <strong>Support poles</strong>
                            <small>
                              {installation.pole_count} marked{" "}
                              {installation.pole_count === 1 ? "pole" : "poles"}
                            </small>
                          </span>
                          <span>
                            <strong>{formatCurrency(installation.poles_cost)}</strong>
                            <small>
                              {formatCurrency(installation.poles_cost / installation.pole_count)}{" "}
                              each
                            </small>
                          </span>
                        </div>,
                      ]
                    : []),
                ])}
                {bistroPricing.min_applied ? (
                  <div>
                    <span>
                      <strong>Bistro project minimum adjustment</strong>
                      <small>One minimum across every run</small>
                    </span>
                    <strong>{formatCurrency(bistroPricing.total - bistroPricing.raw_total)}</strong>
                  </div>
                ) : null}
                <div>
                  <span>
                    <strong>Bistro estimate total</strong>
                    <small>Server-calculated CRM pricing</small>
                  </span>
                  <strong>{formatCurrency(bistroPricing.total)}</strong>
                </div>
              </div>
            ) : (
              <p className="ll-panel-footnote">CRM pricing is loading for these measured runs.</p>
            )}
          </div>
        ) : null}

        {wireTotals.size ? (
          <div className="ll-proposal-section">
            <div className="ll-proposal-section-heading">
              <div>
                <span>Traced routes</span>
                <h3>Wire pricing</h3>
              </div>
            </div>
            <div className="ll-wire-price-list">
              {[...wireTotals.entries()].map(([gauge, feet]) => {
                const item = gauge === 10 || gauge === 12 ? wireItems.get(gauge) : null;
                const line = (selectedTier?.lines ?? []).find(
                  (candidate) => candidate.item_id === (item?.sku || item?.id),
                );
                return (
                  <div key={gauge}>
                    <span>
                      <strong>{landscapeWireLabel(gauge)}</strong>
                      <small>
                        {feet === null ? "Set drawing scale" : `${Math.ceil(feet)} traced ft`}
                      </small>
                    </span>
                    <span>
                      <strong>{line ? formatCurrency(line.line_total) : "Not priced"}</strong>
                      <small>
                        {item
                          ? `${item.name}${line ? ` · ${formatCurrency(line.unit_price)}/ft` : ""}`
                          : "Add this wire size to the selected catalog tier"}
                      </small>
                    </span>
                  </div>
                );
              })}
            </div>
          </div>
        ) : null}

        <fieldset className="ll-proposal-fieldset ll-additional-lines">
          <legend>Additional line items</legend>
          <p>
            Add job-specific work or materials. Each completed line is included in every package
            total.
          </p>
          <div className="ll-additional-line-list">
            {additionalLineItems.map((line, index) => (
              <div className="ll-additional-line" key={line.id}>
                <label>
                  <span className="sr-only">Line item {index + 1} description</span>
                  <input
                    value={line.description}
                    maxLength={500}
                    placeholder="Description"
                    onChange={(event) =>
                      onAdditionalLineItemsChange(
                        additionalLineItems.map((item) =>
                          item.id === line.id ? { ...item, description: event.target.value } : item,
                        ),
                      )
                    }
                  />
                </label>
                <label className="ll-additional-line-amount">
                  <span aria-hidden="true">$</span>
                  <span className="sr-only">Line item {index + 1} amount</span>
                  <input
                    type="number"
                    inputMode="decimal"
                    min="0"
                    max="1000000"
                    step="0.01"
                    value={line.amount || ""}
                    placeholder="0.00"
                    onChange={(event) =>
                      onAdditionalLineItemsChange(
                        additionalLineItems.map((item) =>
                          item.id === line.id
                            ? {
                                ...item,
                                amount: Math.min(
                                  1_000_000,
                                  Math.max(0, Number(event.target.value) || 0),
                                ),
                              }
                            : item,
                        ),
                      )
                    }
                  />
                </label>
                <button
                  type="button"
                  className="est-btn ll-additional-line-remove"
                  aria-label={`Remove line item ${index + 1}`}
                  onClick={() =>
                    onAdditionalLineItemsChange(
                      additionalLineItems.filter((item) => item.id !== line.id),
                    )
                  }
                >
                  <X aria-hidden="true" />
                </button>
              </div>
            ))}
          </div>
          <button
            type="button"
            className="est-btn"
            disabled={additionalLineItems.length >= 100}
            onClick={() =>
              onAdditionalLineItemsChange([
                ...additionalLineItems,
                { id: nextId("line-item"), description: "", amount: 0 },
              ])
            }
          >
            <Plus aria-hidden="true" />
            Add line item
          </button>
        </fieldset>

        <fieldset className="ll-proposal-fieldset">
          <legend>Care plan</legend>
          <p>
            Care pricing uses the fixture count on this plan and stays separate from the
            installation total.
          </p>
          <div className="ll-care-options">
            <button
              className={selectedCarePlanKey === null ? "selected" : ""}
              type="button"
              aria-pressed={selectedCarePlanKey === null}
              onClick={() => onSelectCarePlan(null)}
            >
              <span>No care plan</span>
              <strong>$0.00/year</strong>
            </button>
            {(document?.care_plan?.options ?? []).map((option) => (
              <button
                key={option.key}
                className={option.key === selectedCarePlanKey ? "selected" : ""}
                type="button"
                aria-pressed={option.key === selectedCarePlanKey}
                onClick={() => onSelectCarePlan(option.key)}
              >
                <span>{option.name}</span>
                <strong>{formatCurrency(option.price)}/year</strong>
                <small>
                  {option.visits} service {option.visits === 1 ? "visit" : "visits"}
                  {option.repair_discount > 0
                    ? ` · ${option.repair_discount}% repair discount`
                    : ""}
                </small>
              </button>
            ))}
          </div>
          {selectedCarePlan?.blurb ? (
            <p className="ll-care-note">{selectedCarePlan.blurb}</p>
          ) : null}
        </fieldset>

        <div className="ll-proposal-section">
          <div className="ll-proposal-section-heading">
            <div>
              <span>Project intent and areas</span>
              <h3>Design narrative</h3>
            </div>
          </div>
          <label className="grid gap-2">
            <span>Design intent</span>
            <textarea
              rows={3}
              placeholder="Describe arrival, entertaining, safety, and focal-point intent."
            />
          </label>
          <div className="grid gap-4 sm:grid-cols-2">
            <label className="grid gap-2">
              <span>Payment milestones</span>
              <input defaultValue="50% scheduling deposit, 50% at completion" />
            </label>
            <label className="grid gap-2">
              <span>Electrical responsibility</span>
              <input placeholder="Confirm who supplies line-voltage work" />
            </label>
          </div>
          <label className="grid gap-2">
            <span>Commitments</span>
            <textarea
              rows={2}
              placeholder="Add only reviewed workmanship or service commitments."
            />
          </label>
          <div className="grid gap-4 sm:grid-cols-2">
            <label className="grid gap-2">
              <span>Client signature</span>
              <input aria-label="Client signature name" />
            </label>
            <label className="grid gap-2">
              <span>Signature date</span>
              <input type="date" aria-label="Signature date" />
            </label>
          </div>
        </div>

        <div className="ll-proposal-section">
          <div className="ll-proposal-section-heading">
            <div>
              <span>Customer drawings and zones</span>
              <h3>Dusk concepts by area</h3>
            </div>
          </div>
          {previewsPending ? (
            <div className="ll-panel-inline-empty" role="status">
              Preparing the latest dusk drawings…
            </div>
          ) : Object.keys(previews).length ? (
            <div className="ll-preview-grid">
              {shots.map((shot, index) =>
                previews[shot.id] ? (
                  <figure key={shot.id}>
                    {/* eslint-disable-next-line @next/next/no-img-element -- generated in-memory preview */}
                    <img
                      src={previews[shot.id]}
                      alt={`Lighting concept for property view ${index + 1}`}
                    />
                    <figcaption>Sheet L-{index + 1}</figcaption>
                  </figure>
                ) : null,
              )}
            </div>
          ) : (
            <div className="ll-panel-inline-empty">
              Place at least one fixture to generate a customer-facing dusk concept.
            </div>
          )}
        </div>

        <footer className="ll-proposal-total">
          <div>
            <span>One-time installation</span>
            <strong>
              {estimateTotal !== null ? formatCurrency(estimateTotal) : "Pricing pending"}
            </strong>
            {selectedCarePlan ? (
              <small>
                Plus {formatCurrency(selectedCarePlan.price)} per year for {selectedCarePlan.name}
              </small>
            ) : (
              <small>No recurring care plan selected</small>
            )}
          </div>
          <button
            className="est-btn primary"
            type="button"
            disabled={Boolean(quoteDisabledReason) || createQuotePending || Boolean(createdQuote)}
            title={quoteDisabledReason ?? undefined}
            onClick={onCreateQuote}
          >
            {createQuotePending
              ? "Creating draft…"
              : createdQuote
                ? `Quote ${createdQuote.number} created`
                : "Create draft quote"}
          </button>
        </footer>
        {quoteDisabledReason ? <p className="ll-panel-footnote">{quoteDisabledReason}</p> : null}
        {createQuoteError ? (
          <div className="ll-proposal-error" role="alert">
            {createQuoteError}
          </div>
        ) : null}
        {createdQuote ? (
          <div className="ll-proposal-success">
            <p role="status">
              Draft quote {createdQuote.number} was created from the measured Bistro layout,
              selected package, care plan, fixture pricing, and any catalog-priced wire.
            </p>
            <p>The customer link is locked to the highlighted fixture package.</p>
            <div>
              <strong>Collect payment in three steps</strong>
              <ol className="list-decimal space-y-1 pl-5 text-sm">
                <li>Set the deposit due when the customer accepts.</li>
                <li>Open the quote to preview the client acceptance and payment page.</li>
                <li>Email or text the selected package so the customer can accept and pay.</li>
              </ol>
            </div>
            <div className="flex flex-wrap gap-2">
              <button
                className="est-btn primary"
                type="button"
                onClick={() => setPaymentTermsOpen(true)}
              >
                Set deposit & payment terms
              </button>
              <Link className="est-btn" href="/quotes">
                Open quote & preview payment page
              </Link>
              <button
                className="est-btn"
                type="button"
                disabled={deliveryPending}
                onClick={() => onDeliverQuote("email")}
              >
                Email selected package
              </button>
              <button
                className="est-btn"
                type="button"
                disabled={deliveryPending}
                onClick={() => onDeliverQuote("sms")}
              >
                Text selected package
              </button>
            </div>
            {deliveryStatus ? <p role="status">{deliveryStatus}</p> : null}
            <QuoteEditDialog
              quote={createdQuote}
              open={paymentTermsOpen}
              onOpenChange={setPaymentTermsOpen}
            />
          </div>
        ) : null}
      </div>
    </section>
  );
}

function PreconChecklistItem({ label, complete }: { label: string; complete: boolean }) {
  return (
    <li className={complete ? "complete" : ""}>
      {complete ? <CheckCircle2 aria-hidden="true" /> : <Circle aria-hidden="true" />}
      <span>{label}</span>
    </li>
  );
}

function LandscapeWorkspacePanel({
  tab,
  projectName,
  contactName,
  mockupImage,
  aiImage,
  aiRenderDisabledReason,
  onAIRender,
  shots,
  rows,
  scheduleRows,
  procurementRows,
  catalogItems,
  onUpdateSchedule,
  onCopyScheduleType,
  onUpdateProcurement,
  electricalLoad,
  circuitLoads,
  bistroRows,
  previews,
  previewsPending,
  bomLineItems,
  onBomLineItemsChange,
  pricingTiers,
  proposalDocument,
  inventoryAvailability,
  inventoryAvailabilityPending,
  inventoryAvailabilityError,
  selectedTierKey,
  selectedCarePlanKey,
  wireItems,
  additionalLineItems,
  pricingPending,
  pricingError,
  onRetryPricing,
  onSelectTier,
  onSelectCarePlan,
  onAdditionalLineItemsChange,
  onCreateQuote,
  createQuotePending,
  createQuoteError,
  createdQuote,
  quoteDisabledReason,
  onDeliverQuote,
  deliveryPending,
  deliveryStatus,
  preconState,
  contractAmount,
  onPreconChange,
  onUpload,
}: {
  tab: Exclude<LandscapeWorkspaceTab, "drawing">;
  projectName: string;
  contactName?: string;
  mockupImage: string | null;
  aiImage: string | null;
  aiRenderDisabledReason: string | null;
  onAIRender: () => void;
  shots: DesignerShot[];
  rows: LandscapeFixtureScheduleRow[];
  scheduleRows: LandscapeScheduleRow[];
  bistroRows: LandscapeBistroRunRow[];
  procurementRows: LandscapeProcurementRow[];
  catalogItems: CatalogItemResponse[];
  onUpdateSchedule: (itemId: string, update: LandscapeFixtureScheduleUpdate) => void;
  onCopyScheduleType: (itemId: string) => void;
  onUpdateProcurement: (
    row: LandscapeProcurementRow,
    patch: Partial<LandscapeProcurementRow>,
  ) => void;
  electricalLoad: LandscapeElectricalLoad;
  circuitLoads: LandscapeCircuitLoad[];
  previews: Record<string, string>;
  previewsPending: boolean;
  bomLineItems: LandscapeBomLineItem[];
  onBomLineItemsChange: (lineItems: LandscapeBomLineItem[]) => void;
  pricingTiers: TierConfig[];
  proposalDocument: ProposalDocument | undefined;
  inventoryAvailability: QuoteInventoryAvailability | undefined;
  inventoryAvailabilityPending: boolean;
  inventoryAvailabilityError: string | null;
  selectedTierKey: string | null;
  selectedCarePlanKey: string | null;
  wireItems: Map<10 | 12, CatalogItemResponse | null>;
  additionalLineItems: LandscapeProposalLineItem[];
  pricingPending: boolean;
  pricingError: string | null;
  onRetryPricing: () => void;
  onSelectTier: (tierKey: string) => void;
  onSelectCarePlan: (carePlanKey: string | null) => void;
  onAdditionalLineItemsChange: (items: LandscapeProposalLineItem[]) => void;
  onCreateQuote: () => void;
  createQuotePending: boolean;
  createQuoteError: string | null;
  createdQuote: QuoteDetail | null;
  quoteDisabledReason: string | null;
  onDeliverQuote: (channel: "email" | "sms") => void;
  deliveryPending: boolean;
  deliveryStatus: string | null;
  preconState: LandscapePreconState;
  contractAmount: number | null;
  onPreconChange: (state: LandscapePreconState) => void;
  onUpload: () => void;
}) {
  const fixtureCount = rows.reduce(
    (sum, row) => sum + (row.id === "transformer" ? 0 : row.count),
    0,
  );
  const allAerialPlansScaled =
    shots.length > 0 && shots.every((shot) => Boolean(shot.design.calibration));
  const checklist = [
    { label: "Aerial plan added", complete: shots.length > 0 },
    { label: "Every aerial plan is scaled", complete: allAerialPlansScaled },
    { label: "Lighting plan completed", complete: fixtureCount > 0 || bistroRows.length > 0 },
    { label: "Wire circuits drawn", complete: circuitLoads.length > 0 },
    {
      label: "Circuits assigned and calculated",
      complete:
        circuitLoads.length > 0 &&
        circuitLoads.every((circuit) =>
          ["within-range", "review-drop", "high-drop"].includes(circuit.status),
        ),
    },
    { label: "Dusk preview reviewed", complete: shots.some((shot) => shot.dusk > 0) },
  ];

  if (!shots.length && tab !== "bom") {
    const isEmptyProposal = tab === "proposal";
    return (
      <section
        id={isEmptyProposal ? "landscape-quote-builder" : undefined}
        className="ll-workspace-panel"
        aria-label={isEmptyProposal ? "Landscape Lighting Quote Builder" : `${tab} workspace`}
        tabIndex={isEmptyProposal ? -1 : undefined}
      >
        <LandscapeEmptyPanel
          title={
            isEmptyProposal
              ? "Landscape Lighting Quote Builder"
              : `Start the ${LANDSCAPE_WORKSPACE_TABS.find((item) => item.key === tab)?.label ?? tab}`
          }
          description="Add the first top-down aerial to connect this section to a real lighting plan."
          onUpload={onUpload}
        />
      </section>
    );
  }

  if (tab === "schedule" || tab === "bom") {
    return (
      <section className="ll-workspace-panel" aria-labelledby={`ll-${tab}-title`}>
        <div className="ll-panel-sheet">
          <header className="ll-panel-heading">
            <div>
              <span>Landscape lighting project</span>
              <h2 id={`ll-${tab}-title`}>
                {tab === "schedule" ? "Fixture Schedule" : "Bill of Materials"}
              </h2>
            </div>
            <div className="ll-panel-heading-actions">
              <strong>
                {tab === "bom"
                  ? `${procurementRows.length + bomLineItems.length} line items`
                  : `${fixtureCount} fixtures · ${bistroRows.length} bistro runs`}
              </strong>
            </div>
          </header>
          {tab === "schedule" ? (
            scheduleRows.length || bistroRows.length ? (
              <div className="ll-schedule-sections">
                {scheduleRows.length ? (
                  <section aria-labelledby="ll-fixture-schedule-heading">
                    <h3 id="ll-fixture-schedule-heading">Fixture schedule</h3>
                    <LandscapeFixtureScheduleTable
                      rows={scheduleRows}
                      catalog={catalogItems}
                      onUpdate={onUpdateSchedule}
                      onCopyToType={onCopyScheduleType}
                    />
                  </section>
                ) : null}
                {bistroRows.length ? (
                  <section aria-labelledby="ll-bistro-schedule-heading">
                    <h3 id="ll-bistro-schedule-heading">Bistro run schedule</h3>
                    <LandscapeBistroRunScheduleTable rows={bistroRows} />
                  </section>
                ) : null}
              </div>
            ) : (
              <div className="ll-panel-inline-empty">
                Place fixtures on the Drawing Sheet or trace bistro runs there to build this table.
              </div>
            )
          ) : (
            <>
              <LandscapeProcurementTable rows={procurementRows} onUpdate={onUpdateProcurement} />
              <LandscapeManualBomTable
                supplierRows={[]}
                lineItems={bomLineItems}
                onLineItemsChange={onBomLineItemsChange}
              />
            </>
          )}
          {tab === "bom" ? (
            <p className="ll-panel-footnote">
              Supplier CSV uses the edited procurement values, includes additional manual items,
              expands catalog components, includes placed transformers and traced wire, and flags
              missing SKUs or drawing scale. Wire quantities use traced one-way route length rounded
              up to a whole foot without a waste allowance.
            </p>
          ) : null}
        </div>
      </section>
    );
  }

  if (tab === "electrical") {
    return (
      <section className="ll-workspace-panel" aria-labelledby="ll-electrical-title">
        <div className="ll-panel-sheet ll-electrical-sheet">
          <header className="ll-panel-heading">
            <div>
              <span>Landscape lighting project</span>
              <h2 id="ll-electrical-title">Electrical Plan</h2>
            </div>
          </header>
          <LandscapeElectricalSummary load={electricalLoad} circuits={circuitLoads} />
        </div>
      </section>
    );
  }

  if (tab === "proposal") {
    return (
      <LandscapeProposalPanel
        projectName={projectName}
        contactName={contactName}
        mockupImage={mockupImage}
        aiImage={aiImage}
        aiRenderDisabledReason={aiRenderDisabledReason}
        onAIRender={onAIRender}
        shots={shots}
        rows={rows}
        circuits={circuitLoads}
        bistroRows={bistroRows}
        previews={previews}
        previewsPending={previewsPending}
        tiers={pricingTiers}
        document={proposalDocument}
        inventoryAvailability={inventoryAvailability}
        inventoryAvailabilityPending={inventoryAvailabilityPending}
        inventoryAvailabilityError={inventoryAvailabilityError}
        selectedTierKey={selectedTierKey}
        selectedCarePlanKey={selectedCarePlanKey}
        wireItems={wireItems}
        additionalLineItems={additionalLineItems}
        pricingPending={pricingPending}
        pricingError={pricingError}
        onRetryPricing={onRetryPricing}
        onSelectTier={onSelectTier}
        onSelectCarePlan={onSelectCarePlan}
        onAdditionalLineItemsChange={onAdditionalLineItemsChange}
        onCreateQuote={onCreateQuote}
        createQuotePending={createQuotePending}
        createQuoteError={createQuoteError}
        createdQuote={createdQuote}
        quoteDisabledReason={quoteDisabledReason}
        onDeliverQuote={onDeliverQuote}
        deliveryPending={deliveryPending}
        deliveryStatus={deliveryStatus}
      />
    );
  }

  if (tab === "precon") {
    return (
      <section className="ll-workspace-panel" aria-label="Pre-construction checklist">
        <PreconChecklist
          state={preconState}
          contractAmount={contractAmount}
          onChange={onPreconChange}
        />
      </section>
    );
  }

  return (
    <section className="ll-workspace-panel" aria-labelledby="ll-precon-title">
      <div className="ll-panel-sheet ll-precon-sheet">
        <header className="ll-panel-heading">
          <div>
            <span>Installation handoff</span>
            <h2 id="ll-precon-title">Pre-Con Checklist</h2>
          </div>
          <strong>
            {checklist.filter((item) => item.complete).length}/{checklist.length} complete
          </strong>
        </header>
        <ul className="ll-precon-list">
          {checklist.map((item) => (
            <PreconChecklistItem key={item.label} {...item} />
          ))}
        </ul>
        <p className="ll-panel-footnote">
          Complete the Electrical tab and confirm field conditions before releasing the plan to the
          installation crew.
        </p>
      </div>
    </section>
  );
}

export function LightDesigner({
  workspaceId,
  workspaceName = DEFAULT_WORKSPACE_BRAND_NAME,
  workspaceLogoUrl = null,
  focus = "all",
  landscapeProject,
}: LightDesignerProps) {
  const fileRef = useRef<HTMLInputElement>(null);
  const projectImportRef = useRef<HTMLInputElement>(null);
  const serverBacked = Boolean(landscapeProject);
  const projectInitialDraft = landscapeProject?.initialDraft;
  const projectResetKey = landscapeProject?.resetKey;
  const emitProjectDraft = landscapeProject?.onLandscapeDraftChange;
  const landscapeProjectName = landscapeProject?.projectName ?? "Untitled lighting project";
  const landscapeContactName = landscapeProject?.contactName ?? "Not selected";
  const landscapeOnly = focus === "landscape";
  const serviceLocked = focus === "landscape" || focus === "permanent";
  const initialLandscapeSettings = projectInitialDraft?.settings ?? defaultLandscapeSettings();
  const initialLandscapeProposal = projectInitialDraft?.proposal ?? defaultLandscapeProposal();
  const [localLandscapeTab, setLocalLandscapeTab] = useState<LandscapeWorkspaceTab>(
    projectInitialDraft?.activeWorkflowTab ?? "drawing",
  );
  const landscapeTab = landscapeProject?.activeWorkflowTab ?? localLandscapeTab;
  const onActiveWorkflowTabChange = landscapeProject?.onActiveWorkflowTabChange;
  const setLandscapeTab = useCallback(
    (tab: LandscapeWorkspaceTab) => {
      setLocalLandscapeTab(tab);
      onActiveWorkflowTabChange?.(tab);
    },
    [onActiveWorkflowTabChange],
  );
  const [landscapeToolsOpen, setLandscapeToolsOpen] = useState(false);
  const [landscapeLegendOpen, setLandscapeLegendOpen] = useState(
    initialLandscapeSettings.legend.visible,
  );
  const [landscapeHelpOpen, setLandscapeHelpOpen] = useState(false);
  const [landscapeSheetSize, setLandscapeSheetSize] = useState<LandscapePaperSize>(
    initialLandscapeSettings.paperSize,
  );
  const [landscapePlanFit, setLandscapePlanFit] = useState<LandscapePlanFit>(
    initialLandscapeSettings.planFit,
  );
  const [landscapePlanOpacity, setLandscapePlanOpacity] = useState(
    initialLandscapeSettings.planOpacity,
  );
  const [landscapeLegendPosition, setLandscapeLegendPosition] = useState(
    initialLandscapeSettings.legend.position,
  );
  const [landscapeLegendScale, setLandscapeLegendScale] = useState(
    initialLandscapeSettings.legend.scale,
  );
  const [landscapeSourceVoltage, setLandscapeSourceVoltage] = useState(
    initialLandscapeSettings.sourceVoltage,
  );
  const [fixtureNumbersVisible, setFixtureNumbersVisible] = useState(
    initialLandscapeSettings.fixtureNumbersVisible,
  );
  const [measurementsVisible, setMeasurementsVisible] = useState(
    initialLandscapeSettings.measurementsVisible,
  );
  const [halosVisible, setHalosVisible] = useState(initialLandscapeSettings.halosVisible);
  const [studioNotice, setStudioNotice] = useState<string | null>(null);
  const [newFixtureMarkerColor, setNewFixtureMarkerColor] = useState<string>(
    DEFAULT_FIXTURE_MARKER_COLOR,
  );
  const [planImageRequestToken, setPlanImageRequestToken] = useState(0);
  const [preconState, setPreconState] = useState<LandscapePreconState>(
    () => projectInitialDraft?.precon ?? defaultLandscapePrecon(),
  );

  const handleStudioAction = (action: DrawingStudioAction) => {
    switch (action) {
      case "place-aerial":
        fileRef.current?.click();
        return;
      case "select":
        dispatch({ type: "SET_TOOL", tool: { type: "select" } });
        return;
      case "pan":
        dispatch({ type: "SET_TOOL", tool: { type: "pan" } });
        setStudioNotice("Pan mode on. Drag the zoomed plan with one finger.");
        return;
      case "undo":
        dispatch({ type: "UNDO" });
        return;
      case "wire":
        return;
      case "highlight":
        if (state.tool.type === "highlight") {
          dispatch({ type: "SET_TOOL", tool: { type: "select" } });
          setStudioNotice("Highlight mode closed.");
        } else {
          dispatch({ type: "SET_TOOL", tool: { type: "highlight" } });
          setStudioNotice("Highlight mode on. Drag across the plan to mark an area.");
        }
        return;
      case "fixture-numbers":
        setFixtureNumbersVisible((value) => !value);
        return;
      case "set-scale":
        dispatch({ type: "SET_TOOL", tool: { type: "calibrate" } });
        return;
      case "measurements-visible":
        setMeasurementsVisible((value) => !value);
        return;
      case "fit-contain":
        setLandscapePlanFit("contain");
        return;
      case "fit-cover":
        setLandscapePlanFit("cover");
        return;
      case "opacity-25":
        setLandscapePlanOpacity(0.25);
        return;
      case "opacity-50":
        setLandscapePlanOpacity(0.5);
        return;
      case "opacity-75":
        setLandscapePlanOpacity(0.75);
        return;
      case "opacity-100":
        setLandscapePlanOpacity(1);
        return;
      case "clear-design":
        if (window.confirm("Clear all fixtures and wire routes on this sheet?")) {
          dispatch({ type: "CLEAR_DESIGN" });
        }
        return;
      case "clear-symbols":
        if (
          window.confirm("Clear all highlights, measurements, arrows, and notes on this sheet?")
        ) {
          dispatch({ type: "CLEAR_SYMBOLS" });
        }
        return;
      case "add-photo":
        setPlanImageRequestToken((token) => token + 1);
        setStudioNotice("Choose a supplemental detail photo to pin onto this drawing sheet.");
        return;
      case "clear-wires":
        if (window.confirm("Clear every wire route on this sheet?")) {
          dispatch({ type: "RESET", design: { ...state.design, runs: [] } });
        }
        return;
      case "source-voltage-12":
        setLandscapeSourceVoltage(12);
        return;
      case "source-voltage-13":
        setLandscapeSourceVoltage(13);
        return;
      case "source-voltage-15":
        setLandscapeSourceVoltage(15);
        return;
      case "legend-visible":
        setLandscapeLegendOpen((value) => !value);
        return;
      case "legend-left":
        setLandscapeLegendPosition((position) => ({
          ...position,
          x: Math.max(0, position.x - 24),
        }));
        return;
      case "legend-right":
        setLandscapeLegendPosition((position) => ({ ...position, x: position.x + 24 }));
        return;
      case "legend-up":
        setLandscapeLegendPosition((position) => ({ ...position, y: position.y + 24 }));
        return;
      case "legend-down":
        setLandscapeLegendPosition((position) => ({
          ...position,
          y: Math.max(0, position.y - 24),
        }));
        return;
      case "legend-smaller":
        setLandscapeLegendScale((scale) => Math.max(0.6, Number((scale - 0.1).toFixed(2))));
        return;
      case "legend-larger":
        setLandscapeLegendScale((scale) => Math.min(1.6, Number((scale + 0.1).toFixed(2))));
        return;
      case "recount":
        setLandscapeProcurement((current) => recountLandscapeProcurement(current));
        setStudioNotice(
          `${fixtureScheduleRows.length} fixture${fixtureScheduleRows.length === 1 ? "" : "s"} recounted across all sheets. Purchasing progress was preserved.`,
        );
        return;
      case "halos-visible":
        setHalosVisible((value) => !value);
        return;
      case "import-project":
        projectImportRef.current?.click();
        return;
      case "export-project": {
        const draft = createLandscapeDraft(
          liveShots,
          activeShot?.id ?? null,
          new Date().toISOString(),
          undefined,
          parseLandscapeLiveState(landscapeLiveStateJson),
        );
        const blob = new Blob([JSON.stringify(draft, null, 2)], { type: "application/json" });
        const href = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = href;
        link.download = `${landscapeProjectName.replace(/[^a-z0-9]+/gi, "-").toLowerCase() || "landscape-project"}.tribunal.json`;
        link.click();
        URL.revokeObjectURL(href);
        setStudioNotice("Editable Tribunal project downloaded.");
        return;
      }
      case "fullscreen": {
        const element = document.querySelector<HTMLElement>(".est-landscape-builder");
        const fullscreenRequest = document.fullscreenElement
          ? document.exitFullscreen()
          : element?.requestFullscreen();
        void fullscreenRequest?.catch(() =>
          setStudioNotice("Full screen could not be opened in this browser."),
        );
        return;
      }
      case "present":
        setLandscapeTab("proposal");
        return;
      case "toggle-preview":
        dispatch({ type: "SET_DUSK", dusk: dusk > 0 ? 0 : DEFAULT_DUSK });
        return;
      case "render":
        if (photo) setAiOpen(true);
        return;
      case "download-pdf":
        window.print();
        return;
      case "help":
        setLandscapeHelpOpen((value) => !value);
    }
  };
  const [draftReady, setDraftReady] = useState(!landscapeOnly || serverBacked);
  const [autosaveStatus, setAutosaveStatus] = useState<AutosaveStatus>("loading");
  const [autosavedAt, setAutosavedAt] = useState<string | null>(null);
  const [proposalPreviews, setProposalPreviews] = useState<Record<string, string>>({});
  const [aiRenderByShot, setAiRenderByShot] = useState<
    Record<string, { image: string; designSignature: string }>
  >({});
  const [proposalPreviewsPending, setProposalPreviewsPending] = useState(false);
  const [landscapeProposalSettings, setLandscapeProposalSettings] =
    useState<LandscapeProposalSettings>(initialLandscapeProposal);
  const [selectedLandscapeTierKey, setSelectedLandscapeTierKey] = useState<string | null>(
    initialLandscapeProposal.selectedTierKey,
  );
  const [selectedLandscapeCarePlanKey, setSelectedLandscapeCarePlanKey] = useState<string | null>(
    initialLandscapeProposal.selectedCarePlanKey,
  );
  const [landscapeAdditionalLineItems, setLandscapeAdditionalLineItems] = useState<
    LandscapeProposalLineItem[]
  >(initialLandscapeProposal.additionalLineItems ?? []);
  const [landscapeBomLineItems, setLandscapeBomLineItems] = useState<LandscapeBomLineItem[]>(
    () => projectInitialDraft?.bomLineItems ?? [],
  );
  const [landscapeProcurement, setLandscapeProcurement] = useState<
    Record<string, LandscapeProcurementState>
  >(() => projectInitialDraft?.procurement ?? {});

  // Every photo the rep has open, in the order they added them. The *active*
  // shot's drawing lives in the editor reducer (that's what the canvas, palette
  // and undo stack act on); the others hold theirs here until they're switched
  // back to. `liveShots` below is the one place both halves are read together.
  const [shots, setShots] = useState<DesignerShot[]>(() => projectInitialDraft?.shots ?? []);
  const [activeShotId, setActiveShotId] = useState<string | null>(
    () => projectInitialDraft?.activeShotId ?? null,
  );
  const [state, dispatch] = useReducer(editorReducer, undefined, () => {
    const base = initialEditorState();
    const first = projectInitialDraft?.shots[0];
    return {
      ...base,
      design: first?.design ?? base.design,
      dusk: first?.dusk ?? base.dusk,
    };
  });
  const { design, dusk } = state;
  const selectedFixture =
    state.selection?.kind === "item"
      ? (design.items.find((item) => item.id === state.selection?.id) ?? null)
      : null;
  const toolbarMarkerColor = selectedFixture
    ? (selectedFixture.markerColor ?? null)
    : newFixtureMarkerColor;
  const changeToolbarMarkerColor = (color: string) => {
    setNewFixtureMarkerColor(color);
    if (selectedFixture) {
      dispatch({ type: "UPDATE_ITEM", id: selectedFixture.id, patch: { markerColor: color } });
    }
  };

  const dispatchCanvasAction = (action: EditorAction) => {
    if (serverBacked && action.type === "SET_SELECTION" && action.selection) {
      setLandscapeToolsOpen(true);
    }
    dispatch(action);
  };

  const activeShot = shots.find((shot) => shot.id === activeShotId) ?? shots[0] ?? null;
  const photo: PhotoInfo | null = activeShot?.photo ?? null;
  // Shots as they stand right now: the stored list with the active shot's
  // drawing swapped in from the reducer. Everything that has to see the whole
  // job — totals, the save, the strip's "drawn" dots — reads this, never `shots`.
  const liveShots = shots.map((shot) =>
    shot.id === activeShot?.id ? { ...shot, design, dusk } : shot,
  );
  const landscapeLiveStateJson = JSON.stringify({
    activeWorkflowTab: landscapeTab,
    settings: {
      paperSize: landscapeSheetSize,
      planFit: landscapePlanFit,
      planOpacity: landscapePlanOpacity,
      legend: {
        visible: landscapeLegendOpen,
        position: landscapeLegendPosition,
        scale: landscapeLegendScale,
      },
      halosVisible,
      fixtureNumbersVisible,
      measurementsVisible,
      sourceVoltage: landscapeSourceVoltage,
    },
    proposal: {
      ...landscapeProposalSettings,
      selectedTierKey: selectedLandscapeTierKey,
      selectedCarePlanKey: selectedLandscapeCarePlanKey,
      additionalLineItems: landscapeAdditionalLineItems,
    },
    bomLineItems: landscapeBomLineItems,
    procurement: landscapeProcurement,
    precon: preconState,
  } satisfies LandscapeDraftState);
  const emittedServerDraftSignatureRef = useRef(
    landscapeDraftSignature(
      liveShots,
      activeShot?.id ?? null,
      parseLandscapeLiveState(landscapeLiveStateJson),
    ),
  );
  const persistedItemCountRef = useRef(
    liveShots.reduce((total, shot) => total + shot.design.items.length, 0),
  );

  const [viewMode, setViewMode] = useState<ViewMode>("rep");
  // Dedicated project editors lock the catalog to their project type.
  const [services, setServices] = useState<ServiceKey[]>([
    focus === "permanent" ? "permanent" : "landscape",
  ]);
  const sells = useCallback((key: ServiceKey) => services.includes(key), [services]);
  const toggleService = (key: ServiceKey) => {
    if (serviceLocked) return;
    setServices((prev) => {
      // Never let the rep switch every service off because the palette would be
      // empty with no way back. The last one stays on until another is picked.
      if (prev.includes(key)) {
        return prev.length === 1 ? prev : prev.filter((service) => service !== key);
      }
      return SERVICES.filter((spec) => spec.key === key || prev.includes(spec.key)).map(
        (spec) => spec.key,
      );
    });
  };

  // Browser-only landscape sessions restore the latest workspace draft from IndexedDB.
  // Server projects keep their project record as the source of truth.
  useEffect(() => {
    if (!landscapeOnly || serverBacked) return;
    let cancelled = false;
    queueMicrotask(() => {
      if (cancelled) return;
      setDraftReady(false);
      setAutosaveStatus("loading");
      setAutosavedAt(null);
      setShots([]);
      setActiveShotId(null);
      setProposalPreviews({});
      setAiRenderByShot({});
      dispatch({ type: "RESET" });
      void loadLandscapeDraft(workspaceId)
        .then((draft) => {
          if (cancelled) return;
          const restoredState = draft
            ? landscapeStateFromDraft(draft)
            : {
                activeWorkflowTab: "drawing" as const,
                settings: defaultLandscapeSettings(),
                proposal: defaultLandscapeProposal(),
                bomLineItems: [],
                procurement: {},
                precon: defaultLandscapePrecon(),
              };
          if (draft?.shots.length) {
            const restoredShot =
              draft.shots.find((shot) => shot.id === draft.activeShotId) ?? draft.shots[0];
            setShots(draft.shots);
            setActiveShotId(restoredShot.id);
            dispatch({ type: "RESET", design: restoredShot.design });
            dispatch({ type: "SET_DUSK", dusk: restoredShot.dusk });
            setAutosavedAt(draft.savedAt);
          }
          setLandscapeTab(restoredState.activeWorkflowTab);
          setLandscapeSheetSize(restoredState.settings.paperSize);
          setLandscapePlanFit(restoredState.settings.planFit);
          setLandscapePlanOpacity(restoredState.settings.planOpacity);
          setLandscapeLegendOpen(restoredState.settings.legend.visible);
          setLandscapeLegendPosition(restoredState.settings.legend.position);
          setLandscapeLegendScale(restoredState.settings.legend.scale);
          setHalosVisible(restoredState.settings.halosVisible);
          setFixtureNumbersVisible(restoredState.settings.fixtureNumbersVisible);
          setMeasurementsVisible(restoredState.settings.measurementsVisible);
          setLandscapeSourceVoltage(restoredState.settings.sourceVoltage);
          setLandscapeProposalSettings(restoredState.proposal);
          setSelectedLandscapeTierKey(restoredState.proposal.selectedTierKey);
          setSelectedLandscapeCarePlanKey(restoredState.proposal.selectedCarePlanKey);
          setLandscapeAdditionalLineItems(restoredState.proposal.additionalLineItems ?? []);
          setLandscapeBomLineItems(restoredState.bomLineItems);
          setLandscapeProcurement(restoredState.procurement);
          setPreconState(restoredState.precon);
          setAutosaveStatus("saved");
          setDraftReady(true);
        })
        .catch(() => {
          if (cancelled) return;
          setAutosaveStatus("error");
          setDraftReady(true);
        });
    });
    return () => {
      cancelled = true;
    };
  }, [landscapeOnly, serverBacked, setLandscapeTab, workspaceId]);

  // Save every drawing mutation after a short quiet period. IndexedDB is used
  // because full-resolution property photos regularly exceed localStorage limits.
  useEffect(() => {
    if (!landscapeOnly || serverBacked || !draftReady) return;
    let cancelled = false;
    const timer = window.setTimeout(() => {
      setAutosaveStatus("saving");
      void saveLandscapeDraft(
        workspaceId,
        createLandscapeDraft(
          liveShots,
          activeShot?.id ?? null,
          new Date().toISOString(),
          undefined,
          parseLandscapeLiveState(landscapeLiveStateJson),
        ),
      )
        .then((draft) => {
          if (cancelled) return;
          setAutosavedAt(draft.savedAt);
          setAutosaveStatus("saved");
        })
        .catch(() => {
          if (!cancelled) setAutosaveStatus("error");
        });
    }, 700);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [
    activeShot?.id,
    draftReady,
    landscapeLiveStateJson,
    landscapeOnly,
    liveShots,
    serverBacked,
    workspaceId,
  ]);

  // A conflict resolution can replace the entire authoritative project draft.
  // Resetting the reducer also resets its undo history, so undo cannot resurrect
  // the discarded version after the operator deliberately loads Tribunal's copy.
  useEffect(() => {
    if (!serverBacked || !projectInitialDraft) return;
    let cancelled = false;
    queueMicrotask(() => {
      if (cancelled) return;
      const nextActiveShot =
        projectInitialDraft.shots.find((shot) => shot.id === projectInitialDraft.activeShotId) ??
        projectInitialDraft.shots[0];
      const restoredState = landscapeStateFromDraft(projectInitialDraft);
      const normalizedDraft = createLandscapeDraft(
        projectInitialDraft.shots,
        nextActiveShot?.id ?? null,
        projectInitialDraft.updatedAt,
        undefined,
        restoredState,
        projectInitialDraft.projectType,
      );
      emittedServerDraftSignatureRef.current = landscapeDraftSignature(
        normalizedDraft.shots,
        normalizedDraft.activeShotId,
        restoredState,
      );
      persistedItemCountRef.current = projectInitialDraft.shots.reduce(
        (total, shot) => total + shot.design.items.length,
        0,
      );
      setShots(projectInitialDraft.shots);
      setActiveShotId(nextActiveShot?.id ?? null);
      setProposalPreviews({});
      setAiRenderByShot({});
      setLandscapeTab(restoredState.activeWorkflowTab);
      setLandscapeSheetSize(restoredState.settings.paperSize);
      setLandscapePlanFit(restoredState.settings.planFit);
      setLandscapePlanOpacity(restoredState.settings.planOpacity);
      setLandscapeLegendOpen(restoredState.settings.legend.visible);
      setLandscapeLegendPosition(restoredState.settings.legend.position);
      setLandscapeLegendScale(restoredState.settings.legend.scale);
      setHalosVisible(restoredState.settings.halosVisible);
      setFixtureNumbersVisible(restoredState.settings.fixtureNumbersVisible);
      setMeasurementsVisible(restoredState.settings.measurementsVisible);
      setLandscapeSourceVoltage(restoredState.settings.sourceVoltage);
      setLandscapeProposalSettings(restoredState.proposal);
      setSelectedLandscapeTierKey(restoredState.proposal.selectedTierKey);
      setSelectedLandscapeCarePlanKey(restoredState.proposal.selectedCarePlanKey);
      setLandscapeAdditionalLineItems(restoredState.proposal.additionalLineItems ?? []);
      setLandscapeBomLineItems(restoredState.bomLineItems);
      setLandscapeProcurement(restoredState.procurement);
      setPreconState(restoredState.precon);
      dispatch({
        type: "RESET",
        design: nextActiveShot?.design ?? EMPTY_DESIGN,
      });
      if (nextActiveShot) {
        dispatch({ type: "SET_DUSK", dusk: nextActiveShot.dusk });
      }
      setDraftReady(true);
      const needsNormalizedState =
        projectInitialDraft.settings === undefined ||
        projectInitialDraft.proposal === undefined ||
        projectInitialDraft.procurement === undefined ||
        projectInitialDraft.precon === undefined;
      if (needsNormalizedState) emitProjectDraft?.(normalizedDraft);
    });
    return () => {
      cancelled = true;
    };
  }, [emitProjectDraft, projectInitialDraft, projectResetKey, serverBacked, setLandscapeTab]);

  // Fixture placement is the highest-value edit in this workflow. Queue it for
  // server persistence immediately; all other drawing edits keep the quiet-period
  // debounce below so dragging and aiming do not flood the API.
  useEffect(() => {
    const itemCount = liveShots.reduce((total, shot) => total + shot.design.items.length, 0);
    const fixtureWasAdded = itemCount > persistedItemCountRef.current;
    persistedItemCountRef.current = itemCount;
    if (!fixtureWasAdded || !serverBacked || !emitProjectDraft || !draftReady) {
      return;
    }
    const nextActiveShotId = activeShot?.id ?? null;
    const liveState = parseLandscapeLiveState(landscapeLiveStateJson);
    const signature = landscapeDraftSignature(liveShots, nextActiveShotId, liveState);
    emittedServerDraftSignatureRef.current = signature;
    emitProjectDraft(
      createLandscapeDraft(
        liveShots,
        nextActiveShotId,
        new Date().toISOString(),
        undefined,
        liveState,
        projectInitialDraft?.projectType,
      ),
      { immediate: true },
    );
  }, [
    activeShot?.id,
    draftReady,
    emitProjectDraft,
    landscapeLiveStateJson,
    liveShots,
    projectInitialDraft,
    serverBacked,
  ]);

  // Server projects own persistence. Emit the same complete draft shape that the
  // browser-only builder stores, after one quiet period, without saving the
  // workspace-keyed legacy record or emitting the unchanged initial document.
  useEffect(() => {
    if (!serverBacked || !emitProjectDraft || !draftReady) {
      return;
    }
    const nextActiveShotId = activeShot?.id ?? null;
    const liveState = parseLandscapeLiveState(landscapeLiveStateJson);
    const signature = landscapeDraftSignature(liveShots, nextActiveShotId, liveState);
    if (signature === emittedServerDraftSignatureRef.current) return;

    const timer = window.setTimeout(() => {
      emittedServerDraftSignatureRef.current = signature;
      emitProjectDraft(
        createLandscapeDraft(
          liveShots,
          nextActiveShotId,
          new Date().toISOString(),
          undefined,
          liveState,
          projectInitialDraft?.projectType,
        ),
      );
    }, 600);
    return () => window.clearTimeout(timer);
  }, [
    activeShot?.id,
    draftReady,
    emitProjectDraft,
    landscapeLiveStateJson,
    liveShots,
    projectInitialDraft,
    serverBacked,
  ]);

  const [takedown, setTakedown] = useState(false);
  const [storage, setStorage] = useState(false);
  // The rep's chosen Good/Better/Best seasonal package (a ChristmasPackage key).
  // null = no explicit pick yet; the resolver falls back to the most-inclusive
  // package, matching the server so the preview and the shared page agree.
  const [selectedPackage, setSelectedPackage] = useState<string | null>(null);
  const [christmasPerFtOverride, setChristmasPerFtOverride] = useState<number | null>(null);
  const [discountAmount, setDiscountAmount] = useState<number | null>(null);
  const [permanentDepositInput, setPermanentDepositInput] = useState("");
  // Standalone lines the rep typed for work the price book doesn't carry. Held
  // as raw drafts; only complete rows are priced (see `toEstimateCustomLines`).
  const [customLines, setCustomLines] = useState<CustomLineDraft[]>([]);

  const [shareUrl, setShareUrl] = useState<string | null>(null);
  const [shareToken, setShareToken] = useState<string | null>(null);
  const [sentTo, setSentTo] = useState<string | null>(null);
  // Which rail carried it. A bare "Sent to +15551234567" doesn't say whether the
  // homeowner got a text or an email, which is the one thing the rep needs to
  // know before following up.
  const [sentVia, setSentVia] = useState<SendChannel | null>(null);
  // Which rail is mid-send, so only the pressed button shows "Sending…" while
  // both stay disabled — a rep can't fire the text and the email at once.
  const [sendingChannel, setSendingChannel] = useState<SendChannel | null>(null);
  const [clientName, setClientName] = useState("");
  const [clientEmail, setClientEmail] = useState("");
  const [clientPhone, setClientPhone] = useState("");
  const [savedToCustomer, setSavedToCustomer] = useState(false);
  // The draft quote created from the current proposal inputs. Its signature keeps
  // delivery from reusing a stale quote after pricing, customer, or design changes.
  const [quoteResult, setQuoteResult] = useState<{
    id: string;
    side: "permanent" | "seasonal";
    signature: string;
    number: string;
    depositAmount: number | null;
  } | null>(null);
  const [aiOpen, setAiOpen] = useState(false);

  // ---- Catalog (drawable palette) ---------------------------------------
  // Independent of the current design, so products are available the moment a
  // photo loads and the design→estimate mapping never chases its own tail.
  const { data: catalog } = useQuery({
    queryKey: queryKeys.estimator.compute(workspaceId, CATALOG_PARAMS),
    queryFn: () => estimatorApi.estimate(workspaceId, CATALOG_PARAMS),
    enabled: Boolean(photo),
    staleTime: 5 * 60_000,
  });

  // The landscape half of the palette is the workspace price book, so a fixture
  // drawn on the photo is a real inventory item with a SKU behind it.
  const { data: priceBook } = useQuery({
    queryKey: queryKeys.salesWizard.catalog(workspaceId),
    queryFn: () => salesWizardApi.listCatalog(workspaceId),
    enabled: Boolean(photo),
    staleTime: 5 * 60_000,
  });

  // Pricing config drives both the fixture-type resolution and whether the
  // client-facing roofline comparison is shown.
  const { data: pricing } = useQuery({
    queryKey: queryKeys.salesWizard.pricing(workspaceId),
    queryFn: () => salesWizardApi.getPricing(workspaceId),
    staleTime: 5 * 60_000,
  });

  // Which package the fixture types resolve against. Dedicated landscape projects
  // keep their Good/Better/Best choice with the saved project.
  const configuredTierKeys = pricing?.tier_order?.length
    ? pricing.tier_order
    : (pricing?.tiers ?? []).map((tier) => tier.key);
  const effectiveLandscapeTierKey = configuredTierKeys.includes(selectedLandscapeTierKey ?? "")
    ? selectedLandscapeTierKey
    : (configuredTierKeys[0] ?? null);
  const landscapePricingTiers = configuredTierKeys.flatMap((key) => {
    const tier = (pricing?.tiers ?? []).find((candidate) => candidate.key === key);
    return tier ? [tier] : [];
  });
  const tierKey = landscapeOnly ? effectiveLandscapeTierKey : (configuredTierKeys[0] ?? null);
  const tierLabel =
    (pricing?.tiers ?? []).find((t) => t.key === tierKey)?.tab ??
    (pricing?.tiers ?? []).find((t) => t.key === tierKey)?.label ??
    "this package";
  const fixtureResolution = useMemo(
    () => resolveTierFixtures(pricing, priceBook, tierKey),
    [pricing, priceBook, tierKey],
  );
  const transformerResolution = useMemo(
    () => resolveTierTransformer(pricing, priceBook, tierKey),
    [pricing, priceBook, tierKey],
  );
  const sellsLandscape =
    hasLandscapeFixtures(fixtureResolution) || transformerResolution.item !== null;

  // The palette carries only the selected services, so a Christmas-only quote
  // never shows uplights and a landscape-only quote never shows wreaths.
  const configuredProducts = useMemo(() => {
    const landscape = sells("landscape")
      ? [
          ...(sellsLandscape ? buildFixturePalette(fixtureResolution, transformerResolution) : []),
          ...buildBistroCatalog(priceBook, { installationVariants: landscapeOnly }),
          ...(landscapeOnly ? [BISTRO_POLE_PRODUCT] : []),
        ]
      : [];
    const holiday = buildCatalog(catalog).filter((product) =>
      product.style === "permanent" ? sells("permanent") : sells("christmas"),
    );
    return [...landscape, ...holiday];
  }, [
    sells,
    sellsLandscape,
    fixtureResolution,
    transformerResolution,
    priceBook,
    landscapeOnly,
    catalog,
  ]);
  const products = [
    ...configuredProducts,
    ...buildSavedBistroFallbacks(
      liveShots.flatMap((shot) => shot.design.runs.map((run) => run.productId)),
      configuredProducts,
    ),
  ];
  const productById = indexProducts(products);
  const bistroScheduleRows: LandscapeBistroRunRow[] = liveShots
    .flatMap((shot, shotIndex) => {
      const poleCounts = new Map<string, number>();
      for (const item of shot.design.items) {
        if (item.bistroRunId && productById.get(item.productId)?.target.field === "bistroPole") {
          poleCounts.set(item.bistroRunId, (poleCounts.get(item.bistroRunId) ?? 0) + 1);
        }
      }
      return shot.design.runs.flatMap((run) => {
        const product = productById.get(run.productId);
        if (!product || product.style !== "bistro") return [];
        const scale = runScale(shot.design, run, shot.photo.width);
        return [
          {
            runId: run.id,
            number: 0,
            sheetLabel: `L-${shotIndex + 1}`,
            installation:
              product.target.field === "bistro" ? (product.target.installation ?? null) : null,
            productName: product.name,
            sku: product.sku ?? null,
            poleCount: poleCounts.get(run.id) ?? 0,
            lengthFeet: scale.calibrated ? polylineLength(run.points) * scale.ftPerPx : null,
          },
        ];
      });
    })
    .map((row, index) => ({ ...row, number: index + 1 }));
  const hasBistroRuns = bistroScheduleRows.length > 0;

  // ---- Design → server estimate inputs ----------------------------------
  // Totalled across every photo: front elevation plus back patio is one job and
  // one price. Each run measures on its assigned calibration before it's summed,
  // so photo planes and shots taken from different distances add up correctly.
  const inputs = sumEstimateInputs(
    liveShots.map((shot) => designToEstimateInputs(shot.design, productById, shot.photo.width)),
  );
  const feet = inputs.feet;
  const permanentComplexityFeet = (() => {
    const totals = { aerial: 0, easy: 0, standard: 0, complex: 0 };
    for (const shot of liveShots) {
      for (const run of shot.design.runs) {
        const product = productById.get(run.productId);
        if (product?.category !== "permanent") continue;
        totals[run.permanentComplexity ?? "standard"] +=
          polylineLength(run.points) * runScale(shot.design, run, shot.photo.width).ftPerPx;
      }
    }
    return totals;
  })();
  const selectedPermanentRun =
    state.selection?.kind === "run"
      ? (design.runs.find((run) => {
          if (run.id !== state.selection?.id) return false;
          return productById.get(run.productId)?.category === "permanent";
        }) ?? null)
      : null;
  /** Anything drawn on the photo that's on screen (gates the AI render). */
  const activeDesignHas = hasDesign(design);
  const activeDesignSignature = JSON.stringify(design);
  const activeAIRender = activeShot ? aiRenderByShot[activeShot.id] : undefined;
  const activeAIRenderImage =
    activeAIRender?.designSignature === activeDesignSignature ? activeAIRender.image : null;
  const aiRenderDisabledReason = activeDesignHas
    ? null
    : landscapeOnly
      ? "Place at least one fixture before creating the client render."
      : "Place at least one fixture before creating a photorealistic render.";
  const { calibrated } = designScale(design, photo?.width ?? 0);

  // Placed fixtures, resolved through the current package into the product the
  // crew will actually pull. Counts only — the estimate is priced server-side.
  const fixtureLines = FIXTURE_TYPES.map((spec) => {
    const count = inputs.fixtures[spec.type] ?? 0;
    const resolved = fixtureResolution[spec.type];
    return {
      type: spec.type,
      label: spec.label,
      count,
      productName: resolved.item?.name ?? null,
      sku: resolved.itemId,
    };
  }).filter((line) => line.count > 0);
  // Types the rep drew that this package doesn't sell. Never substituted with a
  // product from another package — the rep is told, and picks.
  const unresolvedFixtures = fixtureLines.filter((line) => !line.sku);
  const fixtureCount = fixtureLines.reduce((sum, line) => sum + line.count, 0);
  const transformerCount = liveShots.reduce(
    (total, shot) =>
      total +
      shot.design.items.filter((item) => productById.get(item.productId)?.style === "transformer")
        .length,
    0,
  );
  const perFixtureSchedule = buildPerFixtureSchedule(liveShots, products, priceBook ?? []);
  const landscapeFixturePricing = splitLandscapeFixturePricing(perFixtureSchedule, inputs.fixtures);
  const fixtureScheduleRows: LandscapeFixtureScheduleRow[] = (() => {
    const rows: LandscapeFixtureScheduleRow[] = fixtureLines.map((line) => {
      const beamLabels = new Set<string>();
      for (const shot of liveShots) {
        for (const item of shot.design.items) {
          const product = productById.get(item.productId);
          if (product?.target.field !== "landscape" || product.target.fixtureType !== line.type) {
            continue;
          }
          const beamAngle = beamAngleFor(product.style, item.beamAngleDeg);
          beamLabels.add(beamAngle === null ? "Ground pool" : `${Math.round(beamAngle)}°`);
        }
      }
      return {
        id: line.type,
        label: line.label,
        productName: line.productName,
        sku: line.sku,
        count: line.count,
        beam: [...beamLabels].join(", ") || "Fixed",
      };
    });
    if (transformerCount > 0) {
      rows.push({
        id: "transformer",
        label: "Transformer",
        productName: transformerResolution.item?.name ?? null,
        sku: transformerResolution.itemId,
        count: transformerCount,
        beam: "Power equipment",
      });
    }
    return rows;
  })();
  const electricalLoad = calculateLandscapeElectricalLoad(
    fixtureLines.map((line) => ({
      id: line.type,
      label: line.label,
      quantity: line.count,
      item: fixtureResolution[line.type].item,
    })),
    { item: transformerResolution.item, quantity: transformerCount },
  );
  const circuitLoads = (() => {
    const circuitInputs = liveShots.flatMap((shot, shotIndex) => {
      return shot.design.runs.flatMap((run, circuitIndex) => {
        if (productById.get(run.productId)?.style !== "wire") return [];
        const fixtures = shot.design.items.flatMap((item) => {
          if (item.circuitId !== run.id) return [];
          const product = productById.get(item.productId);
          if (product?.target.field !== "landscape") return [];
          const type = product.target.fixtureType as FixtureType;
          if (!FIXTURE_TYPES.some((spec) => spec.type === type)) return [];
          return [{ item: fixtureResolution[type].item }];
        });
        const transformerAssigned = shot.design.items.some(
          (item) =>
            item.id === run.transformerId &&
            productById.get(item.productId)?.style === "transformer",
        );
        const scale = runScale(shot.design, run, shot.photo.width);
        return [
          {
            id: run.id,
            label: `${liveShots.length > 1 ? `L-${shotIndex + 1} · ` : ""}${
              run.circuitLabel ?? `C${circuitIndex + 1}`
            }`,
            lengthFeet: scale.calibrated ? polylineLength(run.points) * scale.ftPerPx : null,
            wireGauge: run.wireGauge ?? 12,
            sourceVoltage: run.sourceVoltage ?? landscapeSourceVoltage,
            transformerAssigned,
            fixtures,
          },
        ];
      });
    });
    return calculateLandscapeCircuits(circuitInputs);
  })();
  const selectedTierWireItems = useMemo(
    () =>
      new Map<10 | 12, CatalogItemResponse | null>([
        [12, resolveTierWire(pricing, priceBook, tierKey, 12)],
        [10, resolveTierWire(pricing, priceBook, tierKey, 10)],
      ]),
    [priceBook, pricing, tierKey],
  );
  const generatedSupplierRows = (() => {
    const fixtures: SupplierFixtureInput[] = fixtureLines.map((line) => ({
      label: line.label,
      quantity: line.count,
      item: fixtureResolution[line.type].item,
      category: "fixture",
    }));
    if (transformerCount > 0) {
      fixtures.push({
        label: "Transformer",
        quantity: transformerCount,
        item: transformerResolution.item,
        category: "transformer",
      });
    }
    return buildSupplierCsvRows(
      fixtures,
      circuitLoads.map((circuit) => ({
        label: circuit.label,
        wireGauge: circuit.wireGauge,
        lengthFeet: circuit.lengthFeet,
        item:
          circuit.wireGauge === 10 || circuit.wireGauge === 12
            ? selectedTierWireItems.get(circuit.wireGauge)
            : null,
      })),
    );
  })();
  const procurementSupplements = generatedSupplierRows.flatMap((row) => {
    const supplement = procurementSupplementFromSupplierRow(row);
    return supplement ? [supplement] : [];
  });
  const procurementRows = buildLandscapeProcurement(
    perFixtureSchedule,
    priceBook ?? [],
    landscapeProcurement,
    procurementSupplements,
  );
  const supplierRows = [
    ...procurementRowsToSupplierCsv(procurementRows),
    ...buildManualSupplierCsvRows(landscapeBomLineItems),
  ];
  const updateLandscapeProcurementRow = useCallback(
    (row: LandscapeProcurementRow, patch: Partial<LandscapeProcurementRow>) => {
      const nextRow = { ...row, ...patch };
      setLandscapeProcurement((current) => ({
        ...current,
        [row.key]: procurementStateForRow(nextRow),
      }));
    },
    [],
  );
  const hasLandscape = fixtureCount > 0 || transformerCount > 0 || inputs.bistro_feet > 0;

  const landscapeProposalPayload: ProposalWizardPayload | null =
    !landscapeOnly || !pricing || !priceBook || !effectiveLandscapeTierKey
      ? null
      : buildLandscapeProposalPayload({
          pricing,
          catalog: priceBook,
          fixtureCounts: landscapeFixturePricing.fixtureCounts,
          transformerCount,
          fixedItems: landscapeFixturePricing.fixedItems,
          wireRuns: circuitLoads.map((circuit) => ({
            gauge: circuit.wireGauge,
            lengthFeet: circuit.lengthFeet,
          })),
          bistroRuns: bistroScheduleRows,
          selectedTierKey: effectiveLandscapeTierKey,
          selectedCarePlanKey: selectedLandscapeCarePlanKey,
          additionalLineItems: landscapeAdditionalLineItems,
          contactId: landscapeProject?.contactId,
          opportunityId: landscapeProject?.opportunityId,
          serviceLocationId: landscapeProject?.serviceLocationId,
          lightingProjectId: landscapeProject?.installationShotId
            ? landscapeProject.projectId
            : undefined,
          title: landscapeProjectName,
        });
  const landscapeProposalSignature = JSON.stringify(landscapeProposalPayload);
  const landscapeProposalHasRequirements = Boolean(
    landscapeProposalPayload &&
    (landscapeProposalPayload.quantities?.length ||
      landscapeProposalPayload.fixed_items?.length ||
      landscapeProposalPayload.bistro?.runs?.length),
  );
  const landscapeProposalQuery = useQuery({
    queryKey: queryKeys.lightingProjects.proposalPreview(workspaceId, landscapeProposalSignature),
    queryFn: () => salesWizardApi.preview(workspaceId, landscapeProposalPayload!),
    enabled: landscapeProposalHasRequirements,
    placeholderData: keepPreviousData,
  });
  const landscapeInventoryAvailabilityQuery = useQuery({
    queryKey: queryKeys.lightingProjects.proposalInventoryAvailability(
      workspaceId,
      landscapeProposalSignature,
    ),
    queryFn: () => salesWizardApi.inventoryAvailability(workspaceId, landscapeProposalPayload!),
    enabled: landscapeProposalHasRequirements,
    placeholderData: keepPreviousData,
  });
  useEffect(() => {
    if (
      !landscapeOnly ||
      !effectiveLandscapeTierKey ||
      selectedLandscapeTierKey === effectiveLandscapeTierKey
    ) {
      return;
    }
    let cancelled = false;
    queueMicrotask(() => {
      if (!cancelled) setSelectedLandscapeTierKey(effectiveLandscapeTierKey);
    });
    return () => {
      cancelled = true;
    };
  }, [effectiveLandscapeTierKey, landscapeOnly, selectedLandscapeTierKey]);
  useEffect(() => {
    if (
      !selectedLandscapeCarePlanKey ||
      !landscapeProposalQuery.data ||
      (landscapeProposalQuery.data.care_plan?.options ?? []).some(
        (option) => option.key === selectedLandscapeCarePlanKey,
      )
    ) {
      return;
    }
    let cancelled = false;
    queueMicrotask(() => {
      if (!cancelled) setSelectedLandscapeCarePlanKey(null);
    });
    return () => {
      cancelled = true;
    };
  }, [landscapeProposalQuery.data, selectedLandscapeCarePlanKey]);
  const [savedLandscapeQuote, setSavedLandscapeQuote] = useState<{
    quote: QuoteDetail;
    signature: string;
  } | null>(null);
  const landscapeQuoteMutation = useMutation({
    mutationFn: (payload: ProposalWizardPayload) => salesWizardApi.save(workspaceId, payload),
    onSuccess: (quote, payload) =>
      setSavedLandscapeQuote({
        quote,
        signature: JSON.stringify({ ...payload, night_preview: null }),
      }),
  });
  const [landscapeDeliveryStatus, setLandscapeDeliveryStatus] = useState<string | null>(null);
  const landscapeDeliveryMutation = useMutation({
    mutationFn: (channel: "email" | "sms") => {
      if (!currentSavedLandscapeQuote) throw new Error("Create a draft quote before sending it.");
      return salesWizardApi.deliver(workspaceId, currentSavedLandscapeQuote.id, channel);
    },
    onSuccess: (result) =>
      setLandscapeDeliveryStatus(
        result.channel === "sms"
          ? `Proposal texted to ${result.to}.`
          : `Proposal emailed to ${result.to}.`,
      ),
    onError: (error: unknown) =>
      setLandscapeDeliveryStatus(getApiErrorMessage(error, "Unable to deliver the proposal.")),
  });
  const currentSavedLandscapeQuote =
    savedLandscapeQuote?.signature === landscapeProposalSignature
      ? savedLandscapeQuote.quote
      : null;
  const approvedLandscapeQuoteQuery = useQuery({
    queryKey: queryKeys.quotes.detail(workspaceId, currentSavedLandscapeQuote?.id ?? ""),
    queryFn: () => quotesApi.get(workspaceId, currentSavedLandscapeQuote!.id),
    enabled: Boolean(
      currentSavedLandscapeQuote?.id && currentSavedLandscapeQuote.status === "approved",
    ),
  });
  const closeoutQuote =
    approvedLandscapeQuoteQuery.data ??
    (currentSavedLandscapeQuote?.status === "approved"
      ? ({ ...currentSavedLandscapeQuote } as unknown as import("@/types").Quote)
      : null);
  const [landscapeCloseoutOpen, setLandscapeCloseoutOpen] = useState(false);

  useEffect(() => {
    if (!landscapeOnly || landscapeTab !== "proposal") return;
    const drawn = liveShots.filter((shot) => hasDesign(shot.design));
    let cancelled = false;
    queueMicrotask(() => {
      if (cancelled) return;
      if (!drawn.length) {
        setProposalPreviews({});
        setProposalPreviewsPending(false);
        return;
      }
      setProposalPreviewsPending(true);
      void Promise.all(
        drawn.map(
          async (shot) =>
            [
              shot.id,
              await exportDesignJpeg(shot.photo, shot.design, productById, { dusk: shot.dusk }),
            ] as const,
        ),
      )
        .then((entries) => {
          if (!cancelled) setProposalPreviews(Object.fromEntries(entries));
        })
        .catch(() => {
          if (!cancelled) setProposalPreviews({});
        })
        .finally(() => {
          if (!cancelled) setProposalPreviewsPending(false);
        });
    });
    return () => {
      cancelled = true;
    };
  }, [landscapeOnly, landscapeTab, liveShots, productById]);

  const customLineInputs = useMemo(() => toEstimateCustomLines(customLines), [customLines]);
  const proposalSide: LinearFeetEstimateRequest["proposal_side"] = sells("permanent")
    ? sells("christmas")
      ? "comparison"
      : "permanent"
    : sells("christmas")
      ? "seasonal"
      : "comparison";

  const estimateParams: LinearFeetEstimateRequest = {
    feet,
    channels: 0,
    takedown,
    storage,
    permanent_complexity: dominantPermanentComplexity(permanentComplexityFeet),
    permanent_complexity_feet: permanentComplexityFeet,
    proposal_side: proposalSide,
    discount_amount: discountAmount ?? 0,
    per_ft_override: null,
    christmas_per_ft_override: christmasPerFtOverride,
    christmas_items: inputs.christmas_items,
    selected_package: selectedPackage,
    custom_lines: customLineInputs,
  };
  const estimateSignature = JSON.stringify(estimateParams);
  const [shareEstimateSignature, setShareEstimateSignature] = useState(estimateSignature);
  if (shareEstimateSignature !== estimateSignature) {
    setShareEstimateSignature(estimateSignature);
    setShareUrl(null);
    setShareToken(null);
    setSentTo(null);
    setSentVia(null);
    setSavedToCustomer(false);
    setQuoteResult(null);
  }

  // Holiday pricing only: a landscape-only design has nothing for the roofline
  // comparison endpoint to price; saved landscape projects own that pricing. A
  // standalone line item is priced on its own, with or without a drawing — that
  // is the point of it — so it counts as something to price, share, and quote.
  const hasHolidayDesign =
    feet > 0 || Object.keys(inputs.christmas_items).length > 0 || customLineInputs.length > 0;
  const hasHolidayProposal = hasHolidayDesign && (sells("permanent") || sells("christmas"));

  const {
    data: estimate,
    isFetching,
    isError: estimateFailed,
    error: estimateError,
  } = useQuery({
    queryKey: queryKeys.estimator.compute(workspaceId, estimateParams),
    queryFn: () => estimatorApi.estimate(workspaceId, estimateParams),
    enabled: Boolean(photo) && hasHolidayDesign,
    placeholderData: keepPreviousData,
    staleTime: 60_000,
  });

  const sides = {
    permanent: Boolean((estimate ?? catalog)?.permanent.enabled),
    seasonal: Boolean((estimate ?? catalog)?.christmas.enabled),
  };
  // Customer-facing totals follow the selected service tabs, not every service
  // the workspace happens to support.
  const proposalSides = {
    permanent: sells("permanent") && sides.permanent,
    seasonal: sells("christmas") && sides.seasonal,
  };

  // Resolve the seasonal package the rep is selling (explicit pick, else the
  // most-inclusive one). When packages are active the client sees this package's
  // total as the seasonal price, so the preview and the persisted share both
  // adopt it in place of the à la carte roofline+decor total.
  const selectedPkg = resolveSelectedPackage(estimate?.christmas_packages ?? [], selectedPackage);
  // The package's own total plus any standalone lines (which sit outside every
  // package); à la carte uses its undiscounted subtotal. The flat discount is
  // then applied exactly once to the proposal side the rep selected.
  const christmasSubtotal = seasonalTotal(
    {
      total: estimate?.christmas.subtotal ?? 0,
      custom_total: estimate?.christmas.custom_total,
    },
    selectedPkg,
  );
  const christmasTotal = round2(
    Math.max(
      0,
      christmasSubtotal - (proposalSides.seasonal ? (estimate?.discount_amount ?? 0) : 0),
    ),
  );

  // Mirror of the server's ``build_public_roofline_comparison`` so the preview
  // shows exactly what the shared page will render (same pattern as
  // ``resolveSelectedPackage`` mirroring the backend's recommended-package rule).
  // Roofline against roofline from the à la carte costs — never a package's,
  // which is $0 for a package that excludes the roofline.
  const rooflineView = useMemo(() => {
    if (!pricing?.roofline_comparison_enabled || !estimate) return null;
    if (!proposalSides.permanent || !proposalSides.seasonal) return null;
    const seasonal = estimate.christmas.roofline_cost;
    const multiYear = round2(seasonal * estimate.years);
    return {
      permanent_total: estimate.permanent.roofline_cost,
      seasonal_total: seasonal,
      seasonal_multi_year: multiYear,
      savings: round2(multiYear - estimate.permanent.roofline_cost),
    };
  }, [
    pricing?.roofline_comparison_enabled,
    estimate,
    proposalSides.permanent,
    proposalSides.seasonal,
  ]);

  const resetShare = () => {
    setShareUrl(null);
    setShareToken(null);
    setSentTo(null);
    setSentVia(null);
    setSavedToCustomer(false);
    setQuoteResult(null);
  };

  // ---- Shots (photos in this design) -------------------------------------
  /**
   * Park the active shot's drawing back in the list. Called before anything that
   * moves the reducer off it — switching, removing, adding — so a drawing is
   * never left behind in a reducer that's about to be reset.
   */
  const commitActive = (list: DesignerShot[]) =>
    list.map((shot) => (shot.id === activeShot?.id ? { ...shot, design, dusk } : shot));

  /** Load a shot into the editor. History is per-shot, so it starts clean. */
  const openShot = (target: DesignerShot) => {
    dispatch({ type: "RESET", design: target.design });
    dispatch({ type: "SET_DUSK", dusk: target.dusk });
    setActiveShotId(target.id);
    setViewMode("rep");
  };

  const selectShot = (id: string) => {
    if (id === activeShot?.id) return;
    const target = shots.find((shot) => shot.id === id);
    if (!target) return;
    const next = commitActive(shots);
    setShots(next);
    openShot(next.find((shot) => shot.id === id) ?? target);
  };

  const removeShot = (id: string) => {
    const index = shots.findIndex((shot) => shot.id === id);
    if (index < 0) return;
    // Committing first keeps the *other* shots' edits: if the rep deletes a
    // photo they aren't on, the one they were drawing must not lose its work.
    const next = commitActive(shots).filter((shot) => shot.id !== id);
    setShots(next);
    if (id !== activeShot?.id) return;
    const fallback = next[index] ?? next[index - 1] ?? null;
    if (fallback) {
      openShot(fallback);
      return;
    }
    // Last base image gone: return to the welcome screen with a clean editor.
    setActiveShotId(null);
    dispatch({ type: "RESET" });
  };

  const duplicateActiveShot = () => {
    if (!activeShot || shots.length >= MAX_SHOTS) return;
    const committed = commitActive(shots);
    const sourceIndex = committed.findIndex((shot) => shot.id === activeShot.id);
    if (sourceIndex < 0) return;
    const duplicate: DesignerShot = {
      ...committed[sourceIndex],
      id: nextId("shot"),
    };
    const next = [
      ...committed.slice(0, sourceIndex + 1),
      duplicate,
      ...committed.slice(sourceIndex + 1),
    ];
    setShots(next);
    openShot(duplicate);
  };

  const atShotCap = shots.length >= MAX_SHOTS;

  // ---- Base-image upload -------------------------------------------------
  // Landscape sheets use top-down aerials; the shared seasonal designer still
  // accepts elevation photos. Adding either never replaces an existing drawing.
  const addPhotoFile = async (file: File) => {
    if (atShotCap) return;
    try {
      const info = await fileToPhoto(file);
      const shot: DesignerShot = {
        id: nextId("shot"),
        photo: info,
        design: EMPTY_DESIGN,
        dusk,
      };
      const next = [...commitActive(shots), shot];
      setShots(next);
      openShot(shot);
      // Only the first base image starts the estimate over. Later aerials/photos
      // are more of the same job, so estimate inputs stay in place.
      if (!shots.length) {
        setTakedown(false);
        setStorage(false);
        setChristmasPerFtOverride(null);
        setDiscountAmount(null);
        setSelectedPackage(null);
        setCustomLines([]);
      }
      resetShare();
    } catch {
      window.alert("Could not read that image file.");
    }
  };

  const onFile = async (ev: React.ChangeEvent<HTMLInputElement>) => {
    const file = ev.target.files?.[0];
    ev.target.value = "";
    if (file) await addPhotoFile(file);
  };

  // ---- Save / share / email ---------------------------------------------
  const shareParams = {
    ...estimateParams,
    // Persist the concrete package key (resolved default included) so the public
    // page folds this package's total instead of falling back to à la carte.
    selected_package: selectedPkg?.key ?? null,
    client_name: clientName.trim() || null,
    client_email: clientEmail.trim() || null,
    client_phone: clientPhone.trim() || null,
  };
  const shareMutation = useMutation({
    mutationFn: () => estimatorApi.share(workspaceId, shareParams),
    onSuccess: (result) => {
      setShareUrl(result.url);
      setShareToken(result.token);
      setSavedToCustomer(result.saved_to_customer);
      setSentTo(null);
      setSentVia(null);
    },
  });

  const deliverMutation = useMutation({
    mutationFn: ({ token, channel }: { token: string; channel: SendChannel }) =>
      estimatorApi.deliver(
        workspaceId,
        token,
        (channel === "email" ? clientEmail : clientPhone).trim() || null,
        channel,
      ),
    onSuccess: (result) => {
      setSentTo(result.to);
      setSentVia(result.channel);
    },
  });

  const parsedPermanentDeposit = Number(permanentDepositInput);
  const permanentDepositValid =
    permanentDepositInput === "" ||
    (Number.isFinite(parsedPermanentDeposit) &&
      parsedPermanentDeposit > 0 &&
      parsedPermanentDeposit <= 100);
  const permanentDepositPercentage =
    permanentDepositInput !== "" && permanentDepositValid ? parsedPermanentDeposit : null;
  const permanentDepositAmount =
    permanentDepositPercentage != null
      ? round2((estimate?.permanent.total ?? 0) * permanentDepositPercentage * 0.01)
      : null;
  const permanentPreviewShot = liveShots.find((shot) => shot.id === activeShotId);
  const permanentProjectPreviewReady =
    !landscapeProject ||
    Boolean(
      landscapeProject.projectId &&
        permanentPreviewShot &&
        hasDesign(permanentPreviewShot.design),
    );

  const quoteSignature = (side: "permanent" | "seasonal") =>
    JSON.stringify({
      side,
      inputs: shareParams,
      deposit_percentage: side === "permanent" ? permanentDepositPercentage : null,
      lighting_project_id: side === "permanent" ? (landscapeProject?.projectId ?? null) : null,
      preview:
        side === "permanent" && permanentPreviewShot
          ? {
              shot_id: permanentPreviewShot.id,
              design: permanentPreviewShot.design,
              dusk: permanentPreviewShot.dusk,
            }
          : null,
    });
  const permanentQuoteSignature = quoteSignature("permanent");
  const currentPermanentQuote =
    quoteResult?.side === "permanent" && quoteResult.signature === permanentQuoteSignature
      ? quoteResult
      : null;

  // Convert the drawn design into a real draft quote. ``side`` picks which
  // priced option the customer is buying; the seasonal side carries the chosen
  // package. Every line is recomputed server-side, so this only sends inputs.
  const createQuoteMutation = useMutation({
    mutationFn: async ({ side }: { side: "permanent" | "seasonal"; signature: string }) => {
      await landscapeProject?.flushBeforeProposal?.();
      const lightingProjectId = landscapeProject?.projectId ?? null;
      const proposalPreview =
        side === "permanent" &&
        lightingProjectId &&
        permanentPreviewShot &&
        hasDesign(permanentPreviewShot.design)
          ? {
              shot_id: permanentPreviewShot.id,
              image: await exportDesignJpeg(
                permanentPreviewShot.photo,
                permanentPreviewShot.design,
                productById,
                { dusk: permanentPreviewShot.dusk },
              ),
            }
          : undefined;
      if (side === "permanent" && landscapeProject && !proposalPreview) {
        throw new Error("Save a lighting design on the selected photo before creating its proposal");
      }
      return estimatorApi.createQuote(workspaceId, {
        ...shareParams,
        side,
        lighting_project_id: lightingProjectId,
        proposal_preview: proposalPreview,
        ...(side === "permanent" && permanentDepositPercentage != null
          ? { deposit_percentage: permanentDepositPercentage }
          : {}),
      });
    },
    onSuccess: (quote, { side, signature }) =>
      setQuoteResult({
        id: quote.id,
        side,
        signature,
        number: quote.number,
        depositAmount: quote.deposit_amount ?? null,
      }),
  });
  const quoteDeliveryMutation = useMutation({
    mutationFn: ({ quoteId, channel }: { quoteId: string; channel: SendChannel }) =>
      quotesApi.deliver(
        workspaceId,
        quoteId,
        channel,
        (channel === "email" ? clientEmail : clientPhone).trim() || null,
      ),
    onSuccess: (result) => {
      // Do not leave a preview-only comparison URL beside a successful quote
      // delivery; it is not the acceptance link the customer just received.
      setShareUrl(null);
      setShareToken(null);
      setSavedToCustomer(false);
      setSentTo(result.to);
      setSentVia(result.channel);
    },
  });
  const quotePending = createQuoteMutation.isPending;

  // A single-side permanent send must create and deliver the real quote. The
  // old comparison link only displayed pricing, so customers could neither
  // accept nor reach the existing Stripe deposit checkout.
  const sendPending =
    shareMutation.isPending ||
    deliverMutation.isPending ||
    createQuoteMutation.isPending ||
    quoteDeliveryMutation.isPending;
  // The server's own words, not a generic retry line: a failed text usually
  // means something the rep can fix right now ("add a number under Settings",
  // "this number has opted out"), and that is exactly what gets swallowed by a
  // hardcoded "couldn't send".
  const sendFailure =
    proposalSide === "permanent"
      ? (quoteDeliveryMutation.error ?? createQuoteMutation.error)
      : (deliverMutation.error ?? shareMutation.error);
  const sendError = sendFailure
    ? getApiErrorMessage(
        sendFailure,
        proposalSide === "permanent"
          ? "Couldn’t send the proposal — try again."
          : "Couldn’t send the estimate — try again.",
      )
    : null;
  const canSend = (channel: SendChannel) =>
    hasHolidayProposal &&
    (channel === "email" ? clientEmail : clientPhone).trim().length > 0 &&
    (proposalSide !== "permanent" ||
      (permanentDepositValid && permanentProjectPreviewReady));
  const sendEstimate = async (channel: SendChannel) => {
    if (!canSend(channel) || sendPending) return;
    setSendingChannel(channel);
    try {
      if (proposalSide === "permanent") {
        const quote =
          currentPermanentQuote ??
          (await createQuoteMutation.mutateAsync({
            side: "permanent",
            signature: permanentQuoteSignature,
          }));
        await quoteDeliveryMutation.mutateAsync({ quoteId: quote.id, channel });
        return;
      }

      let comparisonToken = shareToken;
      if (!comparisonToken) {
        const shared = await shareMutation.mutateAsync();
        comparisonToken = shared.token;
      }
      if (comparisonToken) {
        await deliverMutation.mutateAsync({ token: comparisonToken, channel });
      }
    } catch {
      // Surfaced via the matching create/share/delivery mutation above.
    } finally {
      setSendingChannel(null);
    }
  };

  const editCustomer = (setter: (value: string) => void) => (value: string) => {
    setter(value);
    resetShare();
  };

  const makeRateHandler = (setRate: (v: number | null) => void) => (raw: string) => {
    const n = Number(raw);
    setRate(raw === "" || Number.isNaN(n) ? null : Math.max(0, n));
  };
  const onChristmasRateChange = makeRateHandler(setChristmasPerFtOverride);

  // The AI render prompt follows what was actually drawn: a landscape design
  // must never come back looking like a Christmas installation.
  const renderMode: EstimateRenderRequest["mode"] = hasLandscape
    ? "landscape"
    : estimate?.permanent.enabled && !estimate?.christmas.enabled
      ? "permanent"
      : "seasonal";

  const clientPermanentTotal = proposalSides.permanent ? (estimate?.permanent.total ?? 0) : 0;
  const clientSeasonalTotal = proposalSides.seasonal ? christmasTotal : 0;
  const clientShowsBoth = proposalSides.permanent && proposalSides.seasonal;
  const clientTemporaryMultiYear = round2(clientSeasonalTotal * (estimate?.years ?? 0));
  const clientView: ComparisonView | null =
    estimate && !isFetching && (proposalSides.permanent || proposalSides.seasonal)
      ? {
          currency: "USD",
          discountAmount: estimate.discount_amount,
          permanent: { ...estimate.permanent, enabled: proposalSides.permanent },
          christmas: { enabled: proposalSides.seasonal, total: clientSeasonalTotal },
          christmasName: proposalSides.seasonal && selectedPkg ? packageName(selectedPkg) : null,
          difference: clientShowsBoth
            ? round2(Math.abs(clientPermanentTotal - clientSeasonalTotal))
            : 0,
          years: estimate.years,
          temporary_multi_year: clientTemporaryMultiYear,
          permanent_one_time: clientPermanentTotal,
          multi_year_savings: clientShowsBoth
            ? round2(clientTemporaryMultiYear - clientPermanentTotal)
            : 0,
          permanent_perks: proposalSides.permanent ? estimate.permanent_perks : [],
          christmas_perks: proposalSides.seasonal ? estimate.christmas_perks : [],
          // Feet-free ladder for the client preview: only each package's total
          // crosses over (never the roofline breakdown), so the rep sees exactly
          // the Good/Better/Best cards the homeowner gets, with their pick flagged.
          christmasPackages: proposalSides.seasonal
            ? (estimate.christmas_packages ?? []).map((pkg) => ({
                key: pkg.key,
                name: packageName(pkg),
                marker: pkg.marker,
                total: round2(Math.max(0, pkg.pricing.total - estimate.discount_amount)),
                valueTag: pkg.value_tag,
                popular: pkg.popular,
                recommended: pkg.key === selectedPkg?.key,
                points: pkg.points,
                experience: pkg.experience,
              }))
            : [],
          roofline: clientShowsBoth ? rooflineView : null,
          // Server-priced add-ons are restricted to the proposal side and chosen
          // package, matching the shared customer payload.
          customLines: (estimate.custom_lines ?? [])
            .filter(
              (line) =>
                (!line.package_key || line.package_key === selectedPkg?.key) &&
                ((line.side === "permanent" && proposalSides.permanent) ||
                  (line.side === "seasonal" && proposalSides.seasonal)),
            )
            .map((line) => ({
              label: line.label,
              description: line.description,
              quantity: line.quantity,
              amount: line.amount,
              side: line.side,
              packageKey: line.package_key,
            })),
        }
      : null;

  const copyLink = () => {
    if (shareUrl) void navigator.clipboard?.writeText(shareUrl);
  };

  const autosaveLabel =
    autosaveStatus === "loading"
      ? "Restoring draft…"
      : autosaveStatus === "saving"
        ? "Saving…"
        : autosaveStatus === "error"
          ? "Autosave unavailable"
          : autosavedAt
            ? `Saved locally ${new Date(autosavedAt).toLocaleTimeString([], {
                hour: "numeric",
                minute: "2-digit",
              })}`
            : "Local autosave on";
  const landscapePricingError = landscapeProposalQuery.isError
    ? getApiErrorMessage(landscapeProposalQuery.error, "Unable to price this lighting plan.")
    : null;
  const landscapeInventoryAvailabilityError = landscapeInventoryAvailabilityQuery.isError
    ? getApiErrorMessage(
        landscapeInventoryAvailabilityQuery.error,
        "Unable to check inventory availability.",
      )
    : null;
  const landscapeCreateQuoteError = landscapeQuoteMutation.isError
    ? getApiErrorMessage(landscapeQuoteMutation.error, "Unable to create the draft quote.")
    : null;
  const landscapeQuoteDisabledReason = !serverBacked
    ? "Open a customer lighting project to create a CRM quote here."
    : !landscapeProject?.installationShotId
      ? "Select and save an installation sheet before creating a quote."
      : hasUnpriceableBistroRuns(bistroScheduleRows)
        ? "Set the drawing scale and installation type for every Bistro run before creating a quote."
        : fixtureCount === 0 && !hasBistroRuns
          ? "Place at least one fixture or Bistro run before creating a quote."
          : unresolvedFixtures.length > 0
            ? `Resolve ${unresolvedFixtures.map((line) => line.label).join(", ")} in this package before creating a quote.`
            : circuitLoads.some((circuit) => circuit.lengthFeet === null)
              ? "Set the drawing scale so traced wire routes can be priced or clearly marked unpriced."
              : !landscapeProposalPayload
                ? "Pricing configuration is still loading."
                : landscapeProposalQuery.isFetching
                  ? "Pricing this package now."
                  : landscapePricingError
                    ? "Retry proposal pricing before creating a quote."
                    : null;
  const createLandscapeQuote = async () => {
    if (!landscapeProposalPayload || landscapeQuoteDisabledReason) return;
    try {
      await landscapeProject?.flushBeforeProposal?.();
    } catch (error: unknown) {
      setLandscapeDeliveryStatus(
        getApiErrorMessage(error, "Finish syncing the selected installation sheet first."),
      );
      return;
    }
    const previewImages = liveShots.flatMap((shot) => {
      const aiRender = aiRenderByShot[shot.id];
      if (aiRender?.designSignature === JSON.stringify(shot.design)) return [aiRender.image];
      return proposalPreviews[shot.id] ? [proposalPreviews[shot.id]] : [];
    });
    landscapeQuoteMutation.mutate({
      ...landscapeProposalPayload,
      night_preview: previewImages.length
        ? { image: previewImages[0], images: previewImages, services: ["landscape"] }
        : null,
    });
  };

  const drawingPaperDimensions = {
    tabloid: { width: 1240, height: 802 },
    "super-b": { width: 1240, height: 849 },
    letter: { width: 1080, height: 835 },
    "arch-c": { width: 1280, height: 960 },
    "arch-d": { width: 1280, height: 853 },
    "ansi-d": { width: 1280, height: 828 },
  }[landscapeSheetSize] ?? { width: 1240, height: 802 };
  const supportingDocumentLabel =
    LANDSCAPE_WORKSPACE_TABS.find((tab) => tab.key === landscapeTab)?.label ?? "Project";
  const supportingDocumentActions =
    landscapeTab === "drawing" ? null : (
      <>
        {landscapeTab === "bom" ? (
          <>
            <DocumentActionButton onClick={() => handleStudioAction("recount")}>
              <RefreshCcw className="size-3.5" aria-hidden="true" />
              Recount plan
            </DocumentActionButton>
            <DocumentActionButton
              disabled={!supplierRows.length}
              title={
                supplierRows.length
                  ? "Download supplier bill of materials as CSV"
                  : "Complete a BOM line item or add fixtures before exporting a supplier CSV."
              }
              onClick={() => downloadSupplierCsv(supplierRows, landscapeProjectName)}
            >
              <FileDown className="size-3.5" aria-hidden="true" />
              Supplier CSV
            </DocumentActionButton>
          </>
        ) : null}
        {landscapeTab !== "schedule" ? (
          <DocumentActionButton
            aria-label="Save active sheet as PDF using the print dialog"
            title="Open the print dialog to save this sheet as PDF"
            onClick={() => window.print()}
          >
            <FileDown className="size-3.5" aria-hidden="true" />
            PDF
          </DocumentActionButton>
        ) : null}
        <DocumentActionButton onClick={() => window.print()}>
          <Printer className="size-3.5" aria-hidden="true" />
          Print
        </DocumentActionButton>
      </>
    );

  return (
    <div className={`cmp-view est-app${landscapeOnly ? " est-landscape-builder" : ""}`}>
      {!serverBacked ? (
        <div className="est-topbar">
          {landscapeOnly ? (
            <div className="ll-project-identity">
              <Link href="/landscape-lighting">
                <ArrowLeft aria-hidden="true" />
                Projects
              </Link>
              <span className="ll-project-divider" aria-hidden="true" />
              <span>
                <strong>Untitled lighting project</strong>
                <small>{workspaceName}</small>
              </span>
            </div>
          ) : (
            <div className="cmp-brand">Light Designer</div>
          )}
          <div className="est-topbar-actions">
            {landscapeOnly ? (
              <div
                className={`ll-autosave-status ${autosaveStatus}`}
                role="status"
                title="Drafts are saved automatically in this browser"
              >
                {autosaveStatus === "error" ? (
                  <TriangleAlert aria-hidden="true" />
                ) : autosaveStatus === "saved" ? (
                  <CheckCircle2 aria-hidden="true" />
                ) : (
                  <Circle aria-hidden="true" />
                )}
                {autosaveLabel}
              </div>
            ) : null}
            {!landscapeOnly || photo ? (
              <button
                className="est-btn"
                type="button"
                disabled={atShotCap}
                title={
                  atShotCap
                    ? `Up to ${MAX_SHOTS} ${landscapeOnly ? "aerial plans" : "photos"} in one design`
                    : landscapeOnly
                      ? "Add another top-down aerial plan. Existing drawings stay in place."
                      : "Add another photo of this job. Existing drawings stay in place."
                }
                onClick={() => fileRef.current?.click()}
              >
                <ImagePlus aria-hidden="true" />
                {landscapeOnly
                  ? photo
                    ? "Add aerial"
                    : "Upload aerial plan"
                  : photo
                    ? "Add photo"
                    : "Upload house photo"}
              </button>
            ) : null}
            {photo && !serviceLocked ? (
              <div className="est-service-toggle" role="group" aria-label="Services in this design">
                {SERVICES.map((spec) => (
                  <button
                    key={spec.key}
                    type="button"
                    className={sells(spec.key) ? "active" : ""}
                    aria-pressed={sells(spec.key)}
                    title={spec.summary}
                    onClick={() => toggleService(spec.key)}
                  >
                    {spec.label}
                  </button>
                ))}
              </div>
            ) : null}
            {photo && !landscapeOnly ? (
              <div className="est-mode-toggle" role="group" aria-label="View mode">
                <button
                  type="button"
                  className={viewMode === "rep" ? "active" : ""}
                  aria-pressed={viewMode === "rep"}
                  onClick={() => setViewMode("rep")}
                >
                  Rep view
                </button>
                <button
                  type="button"
                  className={viewMode === "client" ? "active" : ""}
                  aria-pressed={viewMode === "client"}
                  onClick={() => setViewMode("client")}
                >
                  Client preview
                </button>
              </div>
            ) : null}
            {photo ? (
              <button
                className="est-btn"
                type="button"
                disabled={Boolean(aiRenderDisabledReason)}
                title={aiRenderDisabledReason ?? undefined}
                onClick={() => setAiOpen(true)}
              >
                <Sparkles aria-hidden="true" />
                AI render
              </button>
            ) : null}
            {landscapeOnly ? (
              <button
                className="est-btn primary"
                type="button"
                aria-label="Open proposal pricing"
                onClick={() => setLandscapeTab("proposal")}
              >
                Quote
              </button>
            ) : null}
          </div>
        </div>
      ) : null}
      <input
        ref={fileRef}
        type="file"
        accept="image/*"
        aria-label={landscapeOnly ? "Upload aerial plan" : "Upload house photo"}
        hidden
        onChange={onFile}
      />
      <input
        ref={projectImportRef}
        type="file"
        accept="application/json,.json"
        hidden
        onChange={(event) => {
          const file = event.target.files?.[0];
          if (!file) return;
          void file.text().then((text) => {
            try {
              const imported = normalizeLandscapeDocument(JSON.parse(text));
              if (!imported) throw new Error("Invalid project file");
              const first =
                imported.shots.find((shot) => shot.id === imported.activeShotId) ??
                imported.shots[0];
              const restoredState = landscapeStateFromDraft(imported);
              setShots(imported.shots);
              setActiveShotId(first?.id ?? null);
              setLandscapeTab(restoredState.activeWorkflowTab);
              setLandscapeSheetSize(restoredState.settings.paperSize);
              setLandscapePlanFit(restoredState.settings.planFit);
              setLandscapePlanOpacity(restoredState.settings.planOpacity);
              setLandscapeLegendOpen(restoredState.settings.legend.visible);
              setLandscapeLegendPosition(restoredState.settings.legend.position);
              setLandscapeLegendScale(restoredState.settings.legend.scale);
              setHalosVisible(restoredState.settings.halosVisible);
              setFixtureNumbersVisible(restoredState.settings.fixtureNumbersVisible);
              setMeasurementsVisible(restoredState.settings.measurementsVisible);
              setLandscapeSourceVoltage(restoredState.settings.sourceVoltage);
              setLandscapeProposalSettings(restoredState.proposal);
              setSelectedLandscapeTierKey(restoredState.proposal.selectedTierKey);
              setSelectedLandscapeCarePlanKey(restoredState.proposal.selectedCarePlanKey);
              setLandscapeAdditionalLineItems(restoredState.proposal.additionalLineItems ?? []);
              setLandscapeBomLineItems(restoredState.bomLineItems);
              setLandscapeProcurement(restoredState.procurement);
              setPreconState(restoredState.precon);
              dispatch({ type: "RESET", design: first?.design ?? EMPTY_DESIGN });
              if (first) dispatch({ type: "SET_DUSK", dusk: first.dusk });
              setStudioNotice("Editable Tribunal project imported.");
            } catch {
              setStudioNotice(
                "Project import failed. Choose a valid Tribunal version 2 JSON file.",
              );
            }
          });
          event.currentTarget.value = "";
        }}
      />

      {landscapeOnly && !serverBacked ? (
        <LandscapeWorkspaceNav activeTab={landscapeTab} onChange={setLandscapeTab} />
      ) : null}

      {landscapeOnly && landscapeTab === "drawing" ? (
        <>
          <LandscapeDraftingToolbar
            products={products}
            workspaceName={workspaceName}
            activeTool={state.tool}
            design={design}
            hasPhoto={Boolean(photo)}
            canUndo={state.past.length > 0}
            markerColor={toolbarMarkerColor}
            onMarkerColorChange={changeToolbarMarkerColor}
            duskPreview={dusk > 0}
            onTogglePreview={() =>
              dispatch({ type: "SET_DUSK", dusk: dusk > 0 ? 0 : DEFAULT_DUSK })
            }
            planFit={landscapePlanFit}
            planOpacity={landscapePlanOpacity}
            legendScale={landscapeLegendScale}
            sourceVoltage={landscapeSourceVoltage}
            toolsOpen={landscapeToolsOpen}
            legendOpen={landscapeLegendOpen}
            helpOpen={landscapeHelpOpen}
            sheetSize={landscapeSheetSize}
            onSheetSizeChange={setLandscapeSheetSize}
            onPlaceAerial={() => fileRef.current?.click()}
            onSelect={() => dispatch({ type: "SET_TOOL", tool: { type: "select" } })}
            onSetScale={() => dispatch({ type: "SET_TOOL", tool: { type: "calibrate" } })}
            onPlaceFixture={(product) =>
              dispatch({ type: "SET_TOOL", tool: { type: "place", productId: product.id } })
            }
            onStartWiring={(product) =>
              dispatch({ type: "SET_TOOL", tool: { type: "draw", productId: product.id } })
            }
            onUndo={() => dispatch({ type: "UNDO" })}
            onToggleTools={() => setLandscapeToolsOpen((open) => !open)}
            onToggleLegend={() => setLandscapeLegendOpen((open) => !open)}
            onToggleHelp={() => setLandscapeHelpOpen((open) => !open)}
            onOpenSchedule={() => setLandscapeTab("schedule")}
            onOpenElectrical={() => setLandscapeTab("electrical")}
            onPresent={() => setLandscapeTab("proposal")}
            onRender={() => setAiOpen(true)}
            onPrint={() => window.print()}
            studio={serverBacked}
            studioSettings={{
              fixtureNumbersVisible,
              measurementsVisible,
              legendVisible: landscapeLegendOpen,
              halosVisible,
            }}
            onStudioAction={handleStudioAction}
          />
          {serverBacked && landscapeHelpOpen ? (
            <aside className="ll-studio-help" aria-label="Drawing help">
              <div>
                <strong>Drawing help</strong>
                <span>
                  Select a labeled tool, then activate the aerial where the fixture or route
                  belongs. Use arrow keys to nudge a selected fixture and Delete to remove it.
                </span>
              </div>
              <button
                type="button"
                aria-label="Close drawing help"
                onClick={() => setLandscapeHelpOpen(false)}
              >
                <X aria-hidden="true" />
              </button>
            </aside>
          ) : null}
          {studioNotice ? (
            <div className="sr-only" role="status" aria-live="polite">
              {studioNotice}
            </div>
          ) : null}
          <LandscapeSheetBar
            shots={liveShots}
            activeShotId={activeShot?.id ?? null}
            installationShotId={landscapeProject?.installationShotId}
            atShotCap={atShotCap}
            onSelect={selectShot}
            onSelectInstallation={(shotId) => {
              void landscapeProject?.onSelectInstallationShot?.(shotId);
            }}
            onAdd={() => fileRef.current?.click()}
            onDuplicate={duplicateActiveShot}
            onRemove={() => activeShot && removeShot(activeShot.id)}
          />
        </>
      ) : null}

      {landscapeOnly && landscapeTab !== "drawing" ? (
        <>
          <DocumentViewport
            label={supportingDocumentLabel}
            paperWidth={1050}
            minimumPaperHeight={680}
            actions={supportingDocumentActions}
          >
            <LandscapeWorkspacePanel
              tab={landscapeTab}
              projectName={landscapeProject?.projectName?.trim() || "Landscape lighting plan"}
              contactName={landscapeProject?.contactName}
              mockupImage={activeShot ? (proposalPreviews[activeShot.id] ?? null) : null}
              aiImage={activeAIRenderImage}
              aiRenderDisabledReason={aiRenderDisabledReason}
              onAIRender={() => setAiOpen(true)}
              shots={liveShots}
              rows={fixtureScheduleRows}
              scheduleRows={perFixtureSchedule}
              bistroRows={bistroScheduleRows}
              procurementRows={procurementRows}
              catalogItems={priceBook ?? []}
              onUpdateSchedule={(itemId, update) => {
                const next = updateFixtureScheduleSelection(liveShots, itemId, update);
                setShots(next);
                const nextActive = next.find((shot) => shot.id === activeShot?.id);
                if (nextActive) dispatch({ type: "RESET", design: nextActive.design });
              }}
              onCopyScheduleType={(itemId) => {
                const next = copyScheduleSelectionToType(liveShots, itemId);
                setShots(next);
                const nextActive = next.find((shot) => shot.id === activeShot?.id);
                if (nextActive) dispatch({ type: "RESET", design: nextActive.design });
              }}
              onUpdateProcurement={updateLandscapeProcurementRow}
              electricalLoad={electricalLoad}
              circuitLoads={circuitLoads}
              previews={proposalPreviews}
              previewsPending={proposalPreviewsPending}
              bomLineItems={landscapeBomLineItems}
              onBomLineItemsChange={setLandscapeBomLineItems}
              pricingTiers={landscapePricingTiers}
              proposalDocument={landscapeProposalQuery.data}
              inventoryAvailability={landscapeInventoryAvailabilityQuery.data}
              inventoryAvailabilityPending={landscapeInventoryAvailabilityQuery.isFetching}
              inventoryAvailabilityError={landscapeInventoryAvailabilityError}
              selectedTierKey={effectiveLandscapeTierKey}
              selectedCarePlanKey={selectedLandscapeCarePlanKey}
              wireItems={selectedTierWireItems}
              additionalLineItems={landscapeAdditionalLineItems}
              pricingPending={landscapeProposalQuery.isFetching}
              pricingError={landscapePricingError}
              onRetryPricing={() => void landscapeProposalQuery.refetch()}
              onSelectTier={setSelectedLandscapeTierKey}
              onSelectCarePlan={setSelectedLandscapeCarePlanKey}
              onAdditionalLineItemsChange={setLandscapeAdditionalLineItems}
              onCreateQuote={createLandscapeQuote}
              createQuotePending={landscapeQuoteMutation.isPending}
              createQuoteError={landscapeCreateQuoteError}
              createdQuote={currentSavedLandscapeQuote}
              quoteDisabledReason={landscapeQuoteDisabledReason}
              onDeliverQuote={(channel) => landscapeDeliveryMutation.mutate(channel)}
              deliveryPending={landscapeDeliveryMutation.isPending}
              deliveryStatus={landscapeDeliveryStatus}
              preconState={preconState}
              contractAmount={currentSavedLandscapeQuote?.total ?? null}
              onPreconChange={setPreconState}
              onUpload={() => fileRef.current?.click()}
            />
          </DocumentViewport>
          {closeoutQuote ? (
            <div className="mx-auto mt-4 flex max-w-3xl items-center justify-between gap-4 rounded-xl border bg-card p-4">
              <div>
                <p className="font-medium">Accepted proposal · installation next</p>
                <p className="text-sm text-muted-foreground">
                  {closeoutQuote.deposit_paid
                    ? "Deposit paid. Choose the installation window and team."
                    : closeoutQuote.deposit_required
                      ? `${formatCurrency(closeoutQuote.deposit_amount ?? 0)} deposit is still due.`
                      : "No deposit required. Choose the installation window and team."}
                </p>
              </div>
              <button
                className="est-btn primary"
                type="button"
                onClick={() => setLandscapeCloseoutOpen(true)}
              >
                Schedule installation
              </button>
            </div>
          ) : null}
          <ConvertQuoteDialog
            workspaceId={workspaceId}
            quote={closeoutQuote}
            open={landscapeCloseoutOpen}
            onOpenChange={setLandscapeCloseoutOpen}
          />
        </>
      ) : (
        <>
          {shots.length && !landscapeOnly ? (
            <div className="est-shotbar" aria-label="Photos in this design">
              {liveShots.map((shot, i) => {
                const drawn = hasDesign(shot.design);
                const isActive = shot.id === activeShot?.id;
                return (
                  <div className={`est-shot${isActive ? " active" : ""}`} key={shot.id}>
                    <button
                      type="button"
                      // Not a tablist: the canvas it switches isn't a tabpanel, and
                      // claiming the relationship would lie to a screen reader.
                      // `aria-current` is the honest read — which of the set is open.
                      aria-current={isActive}
                      className="est-shot-pick"
                      aria-label={`Photo ${i + 1}${drawn ? ", designed" : ", nothing drawn yet"}`}
                      onClick={() => selectShot(shot.id)}
                    >
                      {/* eslint-disable-next-line @next/next/no-img-element -- in-memory data URL */}
                      <img src={shot.photo.dataUrl} alt="" />
                      <span className="est-shot-no">{i + 1}</span>
                      {drawn ? <span className="est-shot-dot" aria-hidden /> : null}
                    </button>
                    <button
                      type="button"
                      className="est-shot-del"
                      aria-label={`Remove photo ${i + 1}`}
                      onClick={() => removeShot(shot.id)}
                    >
                      &times;
                    </button>
                  </div>
                );
              })}
              <button
                type="button"
                className="est-shot-add"
                disabled={atShotCap}
                onClick={() => fileRef.current?.click()}
              >
                <Plus aria-hidden="true" />
                {atShotCap ? `Max ${MAX_SHOTS} photos` : "Add photo"}
              </button>
              <span className="est-shot-hint">
                Each photo keeps its own design. Measurements add up across all of them.
              </span>
            </div>
          ) : null}

          {photo ? (
            <>
              {landscapeOnly ? (
                <div className="ll-drawing-document-shell">
                  <DocumentViewport
                    label="Drawing sheet"
                    paperWidth={drawingPaperDimensions.width}
                    minimumPaperHeight={drawingPaperDimensions.height}
                    className={`ll-sheet-size-${landscapeSheetSize}`}
                  >
                    <div className="ll-live-sheet">
                      <div className="ll-live-sheet-main">
                        <LightCanvas
                          photo={photo}
                          products={products}
                          state={state}
                          dispatch={dispatchCanvasAction}
                          perspective="aerial"
                          placementMarkerColor={newFixtureMarkerColor}
                          planFit={landscapePlanFit}
                          planOpacity={landscapePlanOpacity}
                          fixtureNumbersVisible={fixtureNumbersVisible}
                          measurementsVisible={measurementsVisible}
                          halosVisible={halosVisible}
                          defaultSourceVoltage={landscapeSourceVoltage}
                          planImageRequestToken={planImageRequestToken}
                          onPlanImageRequestHandled={() => setPlanImageRequestToken(0)}
                        />
                        {landscapeLegendOpen ? (
                          <LandscapeLiveLegend
                            rows={fixtureScheduleRows}
                            position={landscapeLegendPosition}
                            scale={landscapeLegendScale}
                          />
                        ) : null}
                      </div>
                      <LandscapeSheetTitleBlock
                        fixtureCount={fixtureScheduleRows.reduce(
                          (sum, row) => sum + (row.id === "transformer" ? 0 : row.count),
                          0,
                        )}
                        bistroRunCount={
                          design.runs.filter(
                            (run) => productById.get(run.productId)?.style === "bistro",
                          ).length
                        }
                        calibrated={Boolean(design.calibration)}
                        sheetNumber={
                          Math.max(
                            liveShots.findIndex((shot) => shot.id === activeShot?.id),
                            0,
                          ) + 1
                        }
                        workspaceName={workspaceName}
                        workspaceLogoUrl={workspaceLogoUrl}
                        projectName={landscapeProjectName}
                        contactName={landscapeContactName}
                      />
                    </div>
                  </DocumentViewport>
                  {landscapeToolsOpen ? (
                    <aside className="ll-tool-drawer" aria-label="Fixture and drawing tools">
                      <header>
                        <span>
                          <strong>Add fixtures</strong>
                          <small>Select a fixture, then place it on the aerial plan.</small>
                        </span>
                        <button
                          type="button"
                          aria-label="Close fixture tools"
                          onClick={() => setLandscapeToolsOpen(false)}
                        >
                          <X aria-hidden="true" />
                        </button>
                      </header>
                      <ToolPalette products={products} state={state} dispatch={dispatch} />
                    </aside>
                  ) : null}
                </div>
              ) : (
                <div className="est-main">
                  <ToolPalette
                    products={products}
                    state={state}
                    dispatch={dispatch}
                    enableSecondaryScale
                  />
                  <LightCanvas
                    // Remount per shot: zoom, pan and any half-drawn run belong to the
                    // photo they were made on and must not follow the rep to the next.
                    key={activeShot?.id}
                    photo={photo}
                    products={products}
                    state={state}
                    dispatch={dispatchCanvasAction}
                  />
                  <div className="est-side">
                    {hasLandscape ? (
                      <div className="ep-panel">
                        <div className="ep-title">Landscape fixtures</div>
                        <div className="ep-lines">
                          {fixtureLines.map((line) => (
                            <div className="ep-line" key={line.type}>
                              <span className="ep-line-name">
                                {line.label}
                                <span className={`ep-line-sku${line.sku ? "" : " missing"}`}>
                                  {line.sku
                                    ? `${line.productName} · ${line.sku}`
                                    : `Not sold in ${tierLabel}`}
                                </span>
                              </span>
                              <span className="ep-line-amount">×{line.count}</span>
                            </div>
                          ))}
                          {inputs.bistro_feet > 0 ? (
                            <div className="ep-line">
                              <span className="ep-line-name">Bistro / string lighting</span>
                              <span className="ep-line-amount">{inputs.bistro_feet} ft</span>
                            </div>
                          ) : null}
                        </div>
                        {unresolvedFixtures.length > 0 ? (
                          <p className="ep-pkg-warn">
                            {tierLabel} doesn’t include{" "}
                            {unresolvedFixtures.map((l) => l.label.toLowerCase()).join(" or ")}.
                            Pick a package that sells{" "}
                            {unresolvedFixtures.length > 1 ? "them" : "it"}, or remove{" "}
                            {unresolvedFixtures.length > 1 ? "those" : "that"} from the photo.
                          </p>
                        ) : null}
                        <p className="ep-pkg-hint">
                          Showing {tierLabel} products. Saved Landscape Lighting projects price
                          fixtures server-side and expand each fixture&rsquo;s parts list.
                        </p>
                        <Link className="est-btn est-save-btn" href="/landscape-lighting">
                          Open Landscape Lighting
                        </Link>
                      </div>
                    ) : null}

                    {hasHolidayDesign || !hasLandscape ? (
                      <EstimatePanel
                        estimate={estimate}
                        isFetching={isFetching}
                        feet={feet}
                        calibrated={calibrated}
                        hasDesign={hasHolidayDesign}
                        selectedPackage={selectedPackage}
                        onSelectPackage={setSelectedPackage}
                        customLines={customLines}
                        onChangeCustomLines={setCustomLines}
                        sides={sides}
                      />
                    ) : null}

                    {!landscapeOnly ? (
                      <>
                        <div className="est-options">
                          {sides.seasonal ? (
                            <>
                              <label className="est-opt-check">
                                <input
                                  type="checkbox"
                                  checked={takedown}
                                  onChange={(e) => setTakedown(e.target.checked)}
                                />
                                Include seasonal takedown
                              </label>
                              <label className="est-opt-check">
                                <input
                                  type="checkbox"
                                  checked={storage}
                                  onChange={(e) => setStorage(e.target.checked)}
                                />
                                Include off-season storage
                              </label>
                            </>
                          ) : null}
                          {sides.permanent ? (
                            selectedPermanentRun ? (
                              <label className="est-opt-rate">
                                <span>Selected run complexity</span>
                                <select
                                  className="est-input"
                                  value={selectedPermanentRun.permanentComplexity ?? "standard"}
                                  onChange={(event) =>
                                    dispatch({
                                      type: "UPDATE_RUN",
                                      id: selectedPermanentRun.id,
                                      patch: {
                                        permanentComplexity: event.target
                                          .value as PermanentComplexity,
                                      },
                                    })
                                  }
                                  aria-label="Selected permanent run complexity"
                                >
                                  {PERMANENT_COMPLEXITY_OPTIONS.map(({ value, label }) => (
                                    <option key={value} value={value}>
                                      {label}
                                    </option>
                                  ))}
                                </select>
                                <span className="est-internal-badge">Internal</span>
                              </label>
                            ) : (
                              <p className="text-xs text-muted-foreground">
                                Select a permanent-lighting run to set its install complexity.
                              </p>
                            )
                          ) : null}
                          {sides.seasonal ? (
                            <label className="est-opt-rate">
                              <span>Seasonal $/ft</span>
                              <input
                                className="est-input"
                                type="number"
                                min={0}
                                step={1}
                                inputMode="decimal"
                                value={christmasPerFtOverride ?? ""}
                                placeholder={String(
                                  estimate?.christmas.per_ft ?? catalog?.christmas.per_ft ?? "",
                                )}
                                onChange={(e) => onChristmasRateChange(e.target.value)}
                                aria-label="Internal seasonal linear-foot rate override"
                              />
                              <span className="est-internal-badge">Internal</span>
                            </label>
                          ) : null}
                          {sides.permanent || sides.seasonal ? (
                            <label className="est-opt-rate">
                              <span>Overall proposal discount</span>
                              <input
                                className="est-input"
                                type="number"
                                min={0}
                                step={1}
                                inputMode="decimal"
                                value={discountAmount ?? ""}
                                placeholder="0"
                                onChange={(event) => {
                                  const value = Number(event.target.value);
                                  setDiscountAmount(
                                    event.target.value === "" || Number.isNaN(value)
                                      ? null
                                      : Math.max(0, value),
                                  );
                                }}
                                aria-label="Overall proposal discount"
                              />
                              <span className="est-internal-badge">USD</span>
                            </label>
                          ) : null}
                          {estimateFailed ? (
                            <p className="est-send-error">
                              {getApiErrorMessage(estimateError, "Unable to price this proposal.")}
                            </p>
                          ) : null}
                        </div>

                        <div className="est-customer">
                          <div className="est-customer-title">Save to customer</div>
                          <div className="est-customer-fields">
                            <ContactCombobox
                              className="est-input"
                              unstyled
                              workspaceId={workspaceId}
                              placeholder="Customer name"
                              aria-label="Customer name"
                              value={clientName}
                              onValueChange={editCustomer(setClientName)}
                              // Taking a saved customer fills the block it
                              // belongs to, so the estimate attaches to that
                              // record instead of minting a near-duplicate.
                              onSelectContact={(contact) => {
                                editCustomer(setClientEmail)(contact.email ?? "");
                                editCustomer(setClientPhone)(contact.phone_number ?? "");
                              }}
                            />
                            <input
                              className="est-input"
                              type="email"
                              placeholder="Email"
                              autoComplete="off"
                              value={clientEmail}
                              onChange={(e) => editCustomer(setClientEmail)(e.target.value)}
                              aria-label="Customer email"
                            />
                            <input
                              className="est-input"
                              type="tel"
                              placeholder="Phone"
                              autoComplete="off"
                              value={clientPhone}
                              onChange={(e) => editCustomer(setClientPhone)(e.target.value)}
                              aria-label="Customer phone"
                            />
                          </div>
                          <div className="est-customer-hint">
                            Add a phone number to save this estimate to a customer record. Without
                            one you can still share the link.
                          </div>
                          <div className="est-send-actions">
                            <button
                              className="est-btn primary est-save-btn"
                              type="button"
                              disabled={!canSend("email") || sendPending}
                              title={
                                canSend("email")
                                  ? `${proposalSide === "permanent" ? "Email the proposal" : "Email the estimate"} to ${clientEmail.trim()}`
                                  : "Draw the design and add a customer email to send"
                              }
                              onClick={() => void sendEstimate("email")}
                            >
                              {sendingChannel === "email" ? (
                                "Sending…"
                              ) : (
                                <>
                                  <Mail aria-hidden="true" />
                                  {proposalSide === "permanent" ? "Email proposal" : "Email estimate"}
                                </>
                              )}
                            </button>
                            <button
                              className="est-btn primary est-save-btn"
                              type="button"
                              disabled={!canSend("sms") || sendPending}
                              title={
                                canSend("sms")
                                  ? `${proposalSide === "permanent" ? "Text the proposal" : "Text the estimate"} to ${clientPhone.trim()}`
                                  : "Draw the design and add a customer phone to send"
                              }
                              onClick={() => void sendEstimate("sms")}
                            >
                              {sendingChannel === "sms" ? (
                                "Sending…"
                              ) : (
                                <>
                                  <MessageSquareText aria-hidden="true" />
                                  {proposalSide === "permanent" ? "Text proposal" : "Text estimate"}
                                </>
                              )}
                            </button>
                          </div>
                          {proposalSide === "permanent" ? (
                            <div className="est-customer-hint">
                              Email or text creates and sends the full proposal. The customer accepts
                              it there, then pays the deposit by card.
                            </div>
                          ) : null}
                          <button
                            className="est-btn est-save-btn"
                            type="button"
                            disabled={!hasHolidayProposal || shareMutation.isPending}
                            onClick={() => shareMutation.mutate()}
                          >
                            {shareMutation.isPending
                              ? "Saving…"
                              : proposalSide === "permanent"
                                ? "Save & share link only — preview, no approval or payment"
                                : "Save & share link only"}
                          </button>
                          {sendError ? (
                            <div className="est-send-row">
                              <span className="est-send-error">{sendError}</span>
                            </div>
                          ) : null}

                          {estimate && (sides.permanent || sides.seasonal) ? (
                            <div className="est-quote-convert">
                              <div className="est-quote-convert-title">
                                Turn this design into a quote
                              </div>
                              {sides.permanent ? (
                                <>
                                  <label className="est-quote-deposit">
                                    <span>Permanent quote deposit</span>
                                    <span className="est-quote-deposit-input">
                                      <input
                                        className="est-input"
                                        type="number"
                                        min="0.01"
                                        max="100"
                                        step="0.01"
                                        inputMode="decimal"
                                        placeholder="50"
                                        value={permanentDepositInput}
                                        aria-invalid={!permanentDepositValid}
                                        onChange={(event) => {
                                          setPermanentDepositInput(event.target.value);
                                          setQuoteResult(null);
                                        }}
                                      />
                                      <span aria-hidden="true">%</span>
                                    </span>
                                  </label>
                                  <div
                                    className={
                                      permanentDepositValid ? "est-customer-hint" : "est-send-error"
                                    }
                                  >
                                    {!permanentDepositValid
                                      ? "Enter a deposit from 0.01% to 100%."
                                      : permanentDepositAmount != null
                                        ? `${formatCurrency(permanentDepositAmount)} due when the customer approves.`
                                        : "Optional override. Leave blank to use the workspace default; the customer can approve and pay by card from the proposal."}
                                  </div>
                                  <button
                                    className="est-btn primary est-save-btn"
                                    type="button"
                                    disabled={
                                      !hasHolidayDesign ||
                                      !permanentProjectPreviewReady ||
                                      quotePending ||
                                      !permanentDepositValid
                                    }
                                    onClick={() =>
                                      createQuoteMutation.mutate({
                                        side: "permanent",
                                        signature: permanentQuoteSignature,
                                      })
                                    }
                                  >
                                    {quotePending
                                      ? "Creating…"
                                      : sides.seasonal
                                        ? "Create permanent quote"
                                        : "Create quote"}
                                  </button>
                                </>
                              ) : null}
                              {sides.seasonal ? (
                                <button
                                  className="est-btn est-save-btn"
                                  type="button"
                                  disabled={!hasHolidayDesign || quotePending}
                                  onClick={() =>
                                    createQuoteMutation.mutate({
                                      side: "seasonal",
                                      signature: quoteSignature("seasonal"),
                                    })
                                  }
                                >
                                  {quotePending
                                    ? "Creating…"
                                    : sides.permanent
                                      ? "Create seasonal quote"
                                      : "Create quote"}
                                </button>
                              ) : null}
                              <div className="est-customer-hint">
                                {sides.permanent
                                  ? "Permanent quotes include the current customer-photo preview. Acceptance and payment status stay with the calendar job."
                                  : "Creates a draft quote with itemized, server-priced lines. Review and send it from Quotes."}
                              </div>
                              {quoteResult ? (
                                <div className="est-saved-note">
                                  Quote {quoteResult.number} created
                                  {quoteResult.depositAmount != null
                                    ? ` · ${formatCurrency(quoteResult.depositAmount)} deposit`
                                    : ""}
                                  {" · "}
                                  <Link href="/quotes" className="est-quote-link">
                                    Open in Quotes
                                  </Link>
                                  {quoteResult.depositAmount != null ? (
                                    <div className="est-customer-hint">
                                      Email or text the proposal from Quotes. Customer approval
                                      opens secure card checkout.
                                    </div>
                                  ) : null}
                                </div>
                              ) : null}
                              {createQuoteMutation.isError ? (
                                <div className="est-send-row">
                                  <span className="est-send-error">
                                    Couldn’t create the quote — draw a design, then try again.
                                  </span>
                                </div>
                              ) : null}
                            </div>
                          ) : null}
                        </div>

                        {shareUrl ? (
                          <div className="est-share">
                            {savedToCustomer ? (
                              <div className="est-saved-note">
                                Saved to customer
                                {clientName.trim() ? ` · ${clientName.trim()}` : ""}
                              </div>
                            ) : null}
                            <div className="est-share-link">
                              <input value={shareUrl} readOnly aria-label="Client link" />
                              <button className="est-btn" type="button" onClick={copyLink}>
                                Copy
                              </button>
                            </div>
                          </div>
                        ) : null}
                        {sentTo ? (
                          <div className="est-send-row">
                            <span className="est-sent-note">
                              {sentVia === "sms" ? "Texted to" : "Emailed to"} {sentTo}
                            </span>
                          </div>
                        ) : null}
                      </>
                    ) : null}
                  </div>
                </div>
              )}

              {viewMode === "client" ? (
                // The client theme follows what's being sold: a Christmas quote gets
                // the holiday palette, a landscape quote stays brass-on-black. The
                // preview mirrors whatever the homeowner will actually see.
                <div className={`est-client-preview ${clientThemeClass(services)}`.trim()}>
                  <ServiceValueProps services={services} pricing={pricing} tierKey={tierKey} />
                  {clientView ? <ComparisonCard view={clientView} /> : null}
                </div>
              ) : null}
            </>
          ) : landscapeOnly ? (
            draftReady ? (
              <LandscapeWelcome
                workspaceName={workspaceName}
                workspaceLogoUrl={workspaceLogoUrl}
                projectName={landscapeProjectName}
                contactName={landscapeContactName}
                onUpload={() => fileRef.current?.click()}
                onDropFile={(file) => void addPhotoFile(file)}
              />
            ) : (
              <div className="ll-draft-loading" role="status">
                <Circle aria-hidden="true" />
                Restoring your latest lighting draft…
              </div>
            )
          ) : (
            <div className="est-welcome">
              <div className="est-welcome-card">
                <div className="est-welcome-bulbs" aria-hidden>
                  <i style={{ background: "#ffd98a" }} />
                  <i style={{ background: "#ff5252" }} />
                  <i style={{ background: "#54ff77" }} />
                  <i style={{ background: "#5aa2ff" }} />
                </div>
                <h1>Design their lights on a photo</h1>
                <p>
                  Upload a straight-on photo of the home, set the scale, then place landscape
                  fixtures and draw glowing roofline, mini-lights, and wreaths. Drag the dusk slider
                  to show it lit.
                </p>
                <p>
                  Add a photo for every angle you’re selling: front, back, and walkway. Each keeps
                  its own design, and the quote covers all of them.
                </p>
                <button
                  className="est-btn primary"
                  type="button"
                  onClick={() => fileRef.current?.click()}
                >
                  <ImagePlus aria-hidden="true" />
                  Upload house photo
                </button>
              </div>
            </div>
          )}
        </>
      )}

      {aiOpen && photo ? (
        <AIRenderModal
          workspaceId={workspaceId}
          photo={photo}
          design={design}
          productById={productById}
          mode={renderMode}
          onGenerated={(image) => {
            if (!activeShot) return;
            setAiRenderByShot((current) => ({
              ...current,
              [activeShot.id]: { image, designSignature: activeDesignSignature },
            }));
          }}
          onClose={() => setAiOpen(false)}
        />
      ) : null}
    </div>
  );
}
