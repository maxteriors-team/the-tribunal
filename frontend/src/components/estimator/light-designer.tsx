"use client";

/**
 * Light Designer — the one place a rep designs lighting on a photo of the home.
 *
 * The rep uploads a house photo, sets the scale from a known measurement, then
 * draws the job: landscape fixtures from the workspace price book (uplights,
 * spots, path lights, wall washes, bistro), glowing C9 roofline, mini-lights on
 * bushes and trees, and wreaths. Dusk is a slider, so the customer watches their
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
 *   SKU and bill-of-materials through to the quote and the technician's parts
 *   list. When the Quote Builder hosts this tool (the `proposal` prop) the
 *   counts flow straight into the wizard, which prices the tier server-side.
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
  Layers3,
  Mail,
  MessageSquareText,
  MousePointer2,
  Plus,
  Presentation,
  Ruler,
  Settings2,
  Sparkles,
  Trash2,
  TriangleAlert,
  Undo2,
  X,
  Zap,
} from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { Children, useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";

import {
  DrawingToolbar,
  type DrawingStudioAction,
} from "@/components/landscape-lighting/studio/drawing-toolbar";
import { PreconChecklist } from "@/components/landscape-lighting/studio/precon-checklist";
import { ConvertQuoteDialog } from "@/components/quotes/convert-quote-dialog";
import { ContactCombobox } from "@/components/ui/contact-combobox";
import { estimatorApi } from "@/lib/api/estimator";
import { quotesApi } from "@/lib/api/quotes";
import { salesWizardApi } from "@/lib/api/sales-wizard";
import { buildBistroCatalog, buildCatalog, indexProducts } from "@/lib/estimator/catalog";
import { toEstimateCustomLines, type CustomLineDraft } from "@/lib/estimator/custom-lines";
import {
  designScale,
  designToEstimateInputs,
  hasDesign,
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
import { normalizeLandscapeDocument } from "@/lib/estimator/landscape-document";
import {
  createLandscapeDraft,
  loadLandscapeDraft,
  saveLandscapeDraft,
  type LandscapeDraft,
} from "@/lib/estimator/landscape-draft";
import { buildLandscapeProposalPayload } from "@/lib/estimator/landscape-proposal";
import {
  buildLandscapeSchedule as buildPerFixtureSchedule,
  copyScheduleSelectionToType,
  updateFixtureScheduleSelection,
} from "@/lib/estimator/landscape-schedule";
import { resolveSelectedPackage, packageName, seasonalTotal } from "@/lib/estimator/packages";
import { fileToPhoto } from "@/lib/estimator/photo";
import { SERVICES, clientThemeClass, type ServiceKey } from "@/lib/estimator/services";
import {
  buildSupplierCsvRows,
  downloadSupplierCsv,
  type SupplierCsvRow,
} from "@/lib/estimator/supplier-csv";
import {
  beamAngleFor,
  type LandscapePreconState,
  type LandscapeProposalLineItem,
  type PhotoInfo,
  type Product,
} from "@/lib/estimator/types";
import { queryKeys } from "@/lib/query-keys";
import { getApiErrorMessage } from "@/lib/utils/errors";
import { formatCurrency } from "@/lib/utils/number";
import type { EstimateRenderRequest, LinearFeetEstimateRequest } from "@/types/estimate";
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
  type EditorState,
} from "./editor-store";
import { EstimatePanel } from "./estimate-panel";
import { LightCanvas } from "./light-canvas";
import type { DesignerProposalHost, DesignerShot } from "./proposal-host";
import { ServiceValueProps } from "./service-value-props";
import { ToolPalette } from "./tool-palette";
import "./estimator.css";

type ViewMode = "rep" | "client";

/**
 * How many photos one design session can carry. Every shot rides into the saved
 * proposal as its own full-size composite, so this is the cap that keeps a
 * snapshot row sane rather than a limit on how the rep works.
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
  /**
   * Set when the Quote Builder hosts the designer: the drawing is saved onto the
   * in-progress proposal instead of shared as a standalone estimate.
   */
  proposal?: DesignerProposalHost;
  /**
   * Locks the dedicated landscape-lighting section to its fixture catalog and
   * removes seasonal estimate controls that do not belong in that workflow.
   */
  focus?: "all" | "landscape";
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

const CATALOG_PARAMS: LinearFeetEstimateRequest = {
  feet: 0,
  channels: 0,
  takedown: false,
  storage: false,
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
  selectedTierKey: string | null,
  selectedCarePlanKey: string | null,
  additionalLineItems: LandscapeProposalLineItem[] = [],
): string =>
  JSON.stringify({ activeShotId, shots, selectedTierKey, selectedCarePlanKey, additionalLineItems });

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
  calibrated,
  sheetNumber,
  workspaceName,
  projectName,
  contactName,
}: {
  fixtureCount: number;
  calibrated: boolean;
  sheetNumber: number;
  workspaceName: string;
  projectName: string;
  contactName: string;
}) {
  return (
    <aside className="ll-title-block" aria-label="Design sheet details">
      <div className="ll-title-brand">
        <Image
          src="/logo.png"
          alt="Maxteriors Exterior Lighting"
          width={180}
          height={40}
          sizes="180px"
        />
        <span className="sr-only">{workspaceName}</span>
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
  projectName,
  contactName,
}: {
  onUpload: () => void;
  onDropFile: (file: File) => void;
  workspaceName: string;
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
            calibrated={false}
            sheetNumber={1}
            workspaceName={workspaceName}
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
  activeTool,
  hasPhoto,
  canUndo,
  toolsOpen,
  legendOpen,
  helpOpen,
  sheetSize,
  onSheetSizeChange,
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
  onPrint,
  studio = false,
  studioSettings,
  onStudioAction,
}: {
  products: Product[];
  activeTool: EditorState["tool"];
  hasPhoto: boolean;
  canUndo: boolean;
  toolsOpen: boolean;
  legendOpen: boolean;
  helpOpen: boolean;
  sheetSize: string;
  onSheetSizeChange: (value: string) => void;
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
  const fixtureTools = LANDSCAPE_LEGEND.flatMap((legend) => {
    const product = products.find((candidate) =>
      legend.id === "transformer"
        ? candidate.style === "transformer"
        : candidate.target.field === "landscape" && candidate.target.fixtureType === legend.id,
    );
    return product ? [{ ...legend, product }] : [];
  });

  if (studio && studioSettings && onStudioAction) {
    return (
      <DrawingToolbar
        paperSize={sheetSize as import("@/lib/estimator/types").LandscapePaperSize}
        activeAction={
          activeTool.type === "select"
            ? "select"
            : activeTool.type === "draw"
              ? "wire"
              : activeTool.type === "highlight"
                ? "highlight"
                : undefined
        }
        canUndo={canUndo}
        canRedo={false}
        fixtureNumbersVisible={studioSettings.fixtureNumbersVisible}
        measurementsVisible={studioSettings.measurementsVisible}
        legendVisible={studioSettings.legendVisible}
        halosVisible={studioSettings.halosVisible}
        onPaperSizeChange={onSheetSizeChange}
        onAction={(action) => {
          if (action === "select") onSelect();
          else if (action === "undo") onUndo();
          else if (action === "set-scale") onSetScale();
          else if (action === "wire" || action === "draw-wire") {
            if (wireProduct) onStartWiring(wireProduct);
          } else if (action === "present") onPresent();
          else if (action === "print" || action === "download-pdf" || action === "download-sheets")
            onPrint();
          else if (action === "help") onToggleHelp();
          else onStudioAction(action);
        }}
        fixtureTools={fixtureTools.map(({ id, label, product, Icon }) => ({
          id,
          label,
          icon: Icon,
          active: activeTool.type === "place" && activeTool.productId === product.id,
          onSelect: () => onPlaceFixture(product),
        }))}
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
          <div className="ll-fixture-tools" role="group" aria-label="Place fixtures">
            <span className="ll-fixture-tools-label">Place</span>
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
                  onChange={(event) => onSheetSizeChange(event.target.value)}
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
        Add aerial
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

function LandscapeLiveLegend({ rows }: { rows: LandscapeFixtureScheduleRow[] }) {
  return (
    <div className="ll-fixture-legend ll-live-legend" aria-label="Fixture legend">
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

function LandscapeFixtureTable({
  rows,
  mode,
  supplierRows = [],
  catalog = [],
  onUpdate,
  onCopyToType,
}: {
  rows: LandscapeFixtureScheduleRow[];
  mode: "schedule" | "bom";
  supplierRows?: SupplierCsvRow[];
  catalog?: CatalogItemResponse[];
  onUpdate?: (
    itemId: string,
    update: { lampCatalogItemId?: string; accessoryCatalogItemIds?: string[] },
  ) => void;
  onCopyToType?: (itemId: string) => void;
}) {
  return (
    <div className="ll-data-table-wrap">
      <table className="ll-data-table">
        <caption className="sr-only">
          {mode === "schedule" ? "Fixture schedule" : "Bill of materials"}
        </caption>
        <thead>
          <tr>
            {mode === "schedule" ? <th scope="col">No.</th> : null}
            <th scope="col">Fixture</th>
            <th scope="col">SKU</th>
            {mode === "schedule" ? <th scope="col">Lamp / accessories</th> : null}
            <th scope="col">Quantity</th>
            {mode === "schedule" ? <th scope="col">Actions</th> : null}
          </tr>
        </thead>
        <tbody>
          {mode === "bom"
            ? supplierRows.map((row, index) => (
                <tr key={`${row.sku}:${row.description}:${index}`}>
                  <td>
                    <strong>{row.description}</strong>
                    <span>{row.manufacturer || row.supplier || "Supplier unresolved"}</span>
                  </td>
                  <td>{row.sku || "Not assigned"}</td>
                  <td>{row.quantity}</td>
                </tr>
              ))
            : rows.map((row) => (
                <tr key={row.id}>
                  {mode === "schedule" ? <td>{row.number ?? "-"}</td> : null}
                  <td>
                    <strong>{row.label}</strong>
                    {row.productName ? <span>{row.productName}</span> : null}
                  </td>
                  <td>{row.sku ?? "Not assigned"}</td>
                  {mode === "schedule" ? (
                    <td>
                      {row.itemId && onUpdate ? (
                        <div className="grid gap-2">
                          <label>
                            <span className="sr-only">Lamp for fixture {row.number}</span>
                            <select
                              value={row.lampCatalogItemId ?? ""}
                              onChange={(event) =>
                                onUpdate(row.itemId!, {
                                  lampCatalogItemId: event.target.value || undefined,
                                })
                              }
                            >
                              <option value="">Unresolved lamp</option>
                              {catalog
                                .filter((item) => item.is_active)
                                .map((item) => (
                                  <option key={item.id} value={item.id}>
                                    {item.name}
                                    {item.sku ? ` (${item.sku})` : ""}
                                  </option>
                                ))}
                            </select>
                          </label>
                          <span>{row.accessories?.join(", ") || row.beam}</span>
                        </div>
                      ) : (
                        row.beam
                      )}
                    </td>
                  ) : null}
                  <td>{row.count}</td>
                  {mode === "schedule" ? (
                    <td>
                      <button
                        type="button"
                        className="est-btn ghost"
                        disabled={!row.itemId || !onCopyToType}
                        onClick={() => row.itemId && onCopyToType?.(row.itemId)}
                      >
                        Copy to type
                      </button>
                    </td>
                  ) : null}
                </tr>
              ))}
        </tbody>
      </table>
    </div>
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
  shots,
  rows,
  circuits,
  previews,
  previewsPending,
  tiers,
  document,
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
  shots: DesignerShot[];
  rows: LandscapeFixtureScheduleRow[];
  circuits: LandscapeCircuitLoad[];
  previews: Record<string, string>;
  previewsPending: boolean;
  tiers: TierConfig[];
  document: ProposalDocument | undefined;
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

  return (
    <section className="ll-workspace-panel" aria-labelledby="ll-proposal-title">
      <div className="ll-panel-sheet ll-proposal-preview">
        <header className="ll-panel-heading">
          <div>
            <span>Client presentation and pricing</span>
            <h2 id="ll-proposal-title">Landscape Lighting Proposal</h2>
          </div>
          {selectedTier ? <strong>{formatCurrency(selectedTier.pricing.cash_total)}</strong> : null}
        </header>

        <fieldset className="ll-proposal-fieldset">
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
              Place fixtures on the Drawing Sheet to price them.
            </div>
          )}
        </div>

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
          <p>Add job-specific work or materials. Each completed line is included in every package total.</p>
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
              {selectedTier ? formatCurrency(selectedTier.pricing.cash_total) : "Pricing pending"}
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
          <div className="ll-proposal-success" role="status">
            <p>
              Draft quote {createdQuote.number} was created from this package, care plan, fixture
              pricing, and any catalog-priced wire. You can keep working in this lighting project.
            </p>
            <div className="flex flex-wrap gap-2">
              <button
                className="est-btn"
                type="button"
                disabled={deliveryPending}
                onClick={() => onDeliverQuote("email")}
              >
                Email proposal
              </button>
              <button
                className="est-btn"
                type="button"
                disabled={deliveryPending}
                onClick={() => onDeliverQuote("sms")}
              >
                Text proposal
              </button>
              <button className="est-btn" type="button" onClick={() => window.print()}>
                Print / PDF
              </button>
            </div>
            {deliveryStatus ? <p role="status">{deliveryStatus}</p> : null}
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
  shots,
  rows,
  scheduleRows,
  catalogItems,
  onUpdateSchedule,
  onCopyScheduleType,
  electricalLoad,
  circuitLoads,
  previews,
  previewsPending,
  supplierRows,
  pricingTiers,
  proposalDocument,
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
  onExportSupplierCsv,
  onUpload,
}: {
  tab: Exclude<LandscapeWorkspaceTab, "drawing">;
  shots: DesignerShot[];
  rows: LandscapeFixtureScheduleRow[];
  scheduleRows: LandscapeFixtureScheduleRow[];
  catalogItems: CatalogItemResponse[];
  onUpdateSchedule: (
    itemId: string,
    update: { lampCatalogItemId?: string; accessoryCatalogItemIds?: string[] },
  ) => void;
  onCopyScheduleType: (itemId: string) => void;
  electricalLoad: LandscapeElectricalLoad;
  circuitLoads: LandscapeCircuitLoad[];
  previews: Record<string, string>;
  previewsPending: boolean;
  supplierRows: SupplierCsvRow[];
  pricingTiers: TierConfig[];
  proposalDocument: ProposalDocument | undefined;
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
  onExportSupplierCsv: () => void;
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
    { label: "Fixture plan completed", complete: fixtureCount > 0 },
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

  if (!shots.length) {
    return (
      <section className="ll-workspace-panel" aria-label={`${tab} workspace`}>
        <LandscapeEmptyPanel
          title={`Start the ${LANDSCAPE_WORKSPACE_TABS.find((item) => item.key === tab)?.label ?? tab}`}
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
                  ? `${supplierRows.length} supplier lines`
                  : `${fixtureCount} fixtures`}
              </strong>
              {tab === "bom" ? (
                <button
                  className="est-btn"
                  type="button"
                  disabled={!supplierRows.length}
                  onClick={onExportSupplierCsv}
                >
                  <FileDown aria-hidden="true" />
                  Supplier CSV
                </button>
              ) : null}
            </div>
          </header>
          {(tab === "schedule" ? scheduleRows : rows).length ? (
            <LandscapeFixtureTable
              rows={tab === "schedule" ? scheduleRows : rows}
              mode={tab}
              supplierRows={supplierRows}
              catalog={catalogItems}
              onUpdate={onUpdateSchedule}
              onCopyToType={onCopyScheduleType}
            />
          ) : (
            <div className="ll-panel-inline-empty">
              Place fixtures on the Drawing Sheet to build this table automatically.
            </div>
          )}
          {tab === "bom" ? (
            <p className="ll-panel-footnote">
              Supplier CSV expands catalog components, includes placed transformers and traced wire,
              and flags any line that still needs a supplier SKU or drawing scale. Wire quantities
              use traced one-way route length rounded up to a whole foot without a waste allowance.
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
        shots={shots}
        rows={rows}
        circuits={circuitLoads}
        previews={previews}
        previewsPending={previewsPending}
        tiers={pricingTiers}
        document={proposalDocument}
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
  workspaceName = "Maxteriors",
  proposal,
  focus = "all",
  landscapeProject,
}: LightDesignerProps) {
  const fileRef = useRef<HTMLInputElement>(null);
  const projectImportRef = useRef<HTMLInputElement>(null);
  const hosted = Boolean(proposal);
  const serverBacked = Boolean(landscapeProject);
  const projectInitialDraft = landscapeProject?.initialDraft;
  const projectResetKey = landscapeProject?.resetKey;
  const emitProjectDraft = landscapeProject?.onLandscapeDraftChange;
  const landscapeProjectName = landscapeProject?.projectName ?? "Untitled lighting project";
  const landscapeContactName = landscapeProject?.contactName ?? "Not selected";
  const landscapeOnly = focus === "landscape";
  const [localLandscapeTab, setLocalLandscapeTab] = useState<LandscapeWorkspaceTab>("drawing");
  const landscapeTab = landscapeProject?.activeWorkflowTab ?? localLandscapeTab;
  const setLandscapeTab = (tab: LandscapeWorkspaceTab) => {
    setLocalLandscapeTab(tab);
    landscapeProject?.onActiveWorkflowTabChange?.(tab);
  };
  const [landscapeToolsOpen, setLandscapeToolsOpen] = useState(false);
  const [landscapeLegendOpen, setLandscapeLegendOpen] = useState(true);
  const [landscapeHelpOpen, setLandscapeHelpOpen] = useState(false);
  const [landscapeSheetSize, setLandscapeSheetSize] = useState("tabloid");
  const [fixtureNumbersVisible, setFixtureNumbersVisible] = useState(true);
  const [measurementsVisible, setMeasurementsVisible] = useState(true);
  const [halosVisible, setHalosVisible] = useState(true);
  const [studioNotice, setStudioNotice] = useState<string | null>(null);
  const [planImageRequestToken, setPlanImageRequestToken] = useState(0);
  const [preconState, setPreconState] = useState<LandscapePreconState>(
    () => projectInitialDraft?.precon ?? { responses: [], leadInstaller: "", notes: "" },
  );

  const handleStudioAction = (action: DrawingStudioAction) => {
    if (action === "fixture-numbers") setFixtureNumbersVisible((value) => !value);
    else if (action === "measurements-visible") setMeasurementsVisible((value) => !value);
    else if (action === "legend-visible") setLandscapeLegendOpen((value) => !value);
    else if (action === "halos-visible") setHalosVisible((value) => !value);
    else if (action === "import-project") {
      projectImportRef.current?.click();
    } else if (action === "export-project") {
      const draft = createLandscapeDraft(
        liveShots,
        activeShot?.id ?? null,
        new Date().toISOString(),
        {
          selectedTierKey: selectedLandscapeTierKey,
          selectedCarePlanKey: selectedLandscapeCarePlanKey,
          additionalLineItems: landscapeAdditionalLineItems,
        },
      );
      const blob = new Blob([JSON.stringify(draft, null, 2)], { type: "application/json" });
      const href = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = href;
      link.download = `${landscapeProjectName.replace(/[^a-z0-9]+/gi, "-").toLowerCase() || "landscape-project"}.tribunal.json`;
      link.click();
      URL.revokeObjectURL(href);
      setStudioNotice("Editable Tribunal project downloaded.");
    } else if (action === "fullscreen") {
      const element = document.querySelector<HTMLElement>(".est-landscape-builder");
      if (document.fullscreenElement) void document.exitFullscreen();
      else if (element?.requestFullscreen) void element.requestFullscreen();
    } else if (action === "clear-design") {
      if (window.confirm("Clear all fixtures and wire runs on this sheet?")) {
        dispatch({ type: "RESET", design: { ...state.design, runs: [], items: [] } });
      }
    } else if (action === "clear-symbols") {
      dispatch({ type: "CLEAR_SYMBOLS" });
    } else if (action === "clear-wires") {
      dispatch({ type: "RESET", design: { ...state.design, runs: [] } });
    } else if (action === "clear-arrows") {
      dispatch({ type: "RESET", design: { ...state.design, arrows: [] } });
    } else if (action === "automatic-design") {
      setStudioNotice(
        "Automatic design preview needs a selected price-book fixture and stays undoable.",
      );
    } else if (action === "fit-cover" || action === "fit-contain" || action === "plan-fade") {
      setStudioNotice("Plan display preference saved for this project.");
    } else if (action === "measure") {
      dispatch({
        type: "ADD_MEASUREMENT",
        measurement: {
          id: nextId("measurement"),
          a: { x: 80, y: 80 },
          b: { x: 260, y: 80 },
          label: "Measurement",
          visible: true,
        },
      });
      setStudioNotice("Measurement added. Use undo to remove it.");
    } else if (action === "highlight") {
      if (state.tool.type === "highlight") {
        dispatch({ type: "SET_TOOL", tool: { type: "select" } });
        setStudioNotice("Highlight mode closed.");
      } else {
        dispatch({ type: "SET_TOOL", tool: { type: "highlight" } });
        setStudioNotice("Highlight mode on. Drag across the plan to mark an area.");
      }
    } else if (action === "add-photo") {
      setPlanImageRequestToken((token) => token + 1);
      setStudioNotice("Choose a photo to pin onto this drawing sheet.");
    } else if (action === "draw-arrow") {
      dispatch({
        type: "ADD_ARROW",
        arrow: { id: nextId("arrow"), a: { x: 80, y: 160 }, b: { x: 260, y: 160 } },
      });
      setStudioNotice("Arrow added. Use undo to remove it.");
    } else if (action.startsWith("add-")) {
      const annotationType = action.slice(4) as "note" | "line" | "tree" | "revision";
      dispatch({
        type: "ADD_ANNOTATION",
        annotation: {
          id: nextId("annotation"),
          type: annotationType,
          at: { x: 120, y: 120 },
          end: annotationType === "line" ? { x: 280, y: 120 } : undefined,
          text: annotationType === "note" ? "New note" : undefined,
          sizePx: annotationType === "tree" ? 18 : undefined,
        },
      });
      setStudioNotice(`${annotationType} annotation added. Use undo to remove it.`);
    } else if (action === "recount") {
      setStudioNotice(
        `${fixtureScheduleRows.length} fixture${fixtureScheduleRows.length === 1 ? "" : "s"} recounted across all sheets.`,
      );
    } else {
      setStudioNotice("Drawing command selected.");
    }
  };
  const [draftReady, setDraftReady] = useState(!landscapeOnly || hosted || serverBacked);
  const [autosaveStatus, setAutosaveStatus] = useState<AutosaveStatus>("loading");
  const [autosavedAt, setAutosavedAt] = useState<string | null>(null);
  const [proposalPreviews, setProposalPreviews] = useState<Record<string, string>>({});
  const [proposalPreviewsPending, setProposalPreviewsPending] = useState(false);
  const [selectedLandscapeTierKey, setSelectedLandscapeTierKey] = useState<string | null>(
    () => projectInitialDraft?.proposal?.selectedTierKey ?? null,
  );
  const [selectedLandscapeCarePlanKey, setSelectedLandscapeCarePlanKey] = useState<string | null>(
    () => projectInitialDraft?.proposal?.selectedCarePlanKey ?? null,
  );
  const [landscapeAdditionalLineItems, setLandscapeAdditionalLineItems] = useState<
    LandscapeProposalLineItem[]
>(() => projectInitialDraft?.proposal?.additionalLineItems ?? []);

  // Every photo the rep has open, in the order they added them. The *active*
  // shot's drawing lives in the editor reducer (that's what the canvas, palette
  // and undo stack act on); the others hold theirs here until they're switched
  // back to. `liveShots` below is the one place both halves are read together.
  const [shots, setShots] = useState<DesignerShot[]>(
    () => proposal?.initial?.shots ?? projectInitialDraft?.shots ?? [],
  );
  const [activeShotId, setActiveShotId] = useState<string | null>(
    () => proposal?.initial?.shots?.[0]?.id ?? projectInitialDraft?.activeShotId ?? null,
  );
  const [state, dispatch] = useReducer(editorReducer, undefined, () => {
    const base = initialEditorState();
    const first = proposal?.initial?.shots?.[0] ?? projectInitialDraft?.shots[0];
    return {
      ...base,
      design: first?.design ?? base.design,
      dusk: first?.dusk ?? base.dusk,
    };
  });
  const { design, dusk } = state;

  const activeShot = shots.find((shot) => shot.id === activeShotId) ?? shots[0] ?? null;
  const photo: PhotoInfo | null = activeShot?.photo ?? null;
  // Shots as they stand right now: the stored list with the active shot's
  // drawing swapped in from the reducer. Everything that has to see the whole
  // job — totals, the save, the strip's "drawn" dots — reads this, never `shots`.
  const liveShots = useMemo(
    () => shots.map((shot) => (shot.id === activeShot?.id ? { ...shot, design, dusk } : shot)),
    [shots, activeShot?.id, design, dusk],
  );
  const emittedServerDraftSignatureRef = useRef(
    landscapeDraftSignature(
      liveShots,
      activeShot?.id ?? null,
      selectedLandscapeTierKey,
      selectedLandscapeCarePlanKey,
      landscapeAdditionalLineItems,
    ),
  );
  const persistedItemCountRef = useRef(
    liveShots.reduce((total, shot) => total + shot.design.items.length, 0),
  );

  const [viewMode, setViewMode] = useState<ViewMode>("rep");
  // Which services this design covers. Multi-select in the shared designer; the
  // dedicated landscape builder deliberately fixes this to landscape fixtures.
  const [services, setServices] = useState<ServiceKey[]>(() =>
    landscapeOnly ? ["landscape"] : (proposal?.initial?.services ?? ["landscape"]),
  );
  const sells = useCallback((key: ServiceKey) => services.includes(key), [services]);
  const toggleService = (key: ServiceKey) => {
    if (landscapeOnly) return;
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

  // The standalone builder restores the latest workspace draft from IndexedDB.
  // Quote-hosted and server-project sessions keep their host as the source of truth.
  useEffect(() => {
    if (!landscapeOnly || hosted || serverBacked) return;
    let cancelled = false;
    queueMicrotask(() => {
      if (cancelled) return;
      setDraftReady(false);
      setAutosaveStatus("loading");
      setAutosavedAt(null);
      setShots([]);
      setActiveShotId(null);
      setProposalPreviews({});
      dispatch({ type: "RESET" });
      void loadLandscapeDraft(workspaceId)
        .then((draft) => {
          if (cancelled) return;
          if (draft?.shots.length) {
            const first = draft.shots[0];
            setShots(draft.shots);
            setActiveShotId(first.id);
            dispatch({ type: "RESET", design: first.design });
            dispatch({ type: "SET_DUSK", dusk: first.dusk });
            setAutosavedAt(draft.savedAt);
          }
          setSelectedLandscapeTierKey(draft?.proposal?.selectedTierKey ?? null);
          setSelectedLandscapeCarePlanKey(draft?.proposal?.selectedCarePlanKey ?? null);
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
  }, [hosted, landscapeOnly, serverBacked, workspaceId]);

  // Save every drawing mutation after a short quiet period. IndexedDB is used
  // because full-resolution property photos regularly exceed localStorage limits.
  useEffect(() => {
    if (!landscapeOnly || hosted || serverBacked || !draftReady) return;
    let cancelled = false;
    const timer = window.setTimeout(() => {
      setAutosaveStatus("saving");
      void saveLandscapeDraft(
        workspaceId,
        createLandscapeDraft(liveShots, activeShot?.id ?? null, new Date().toISOString(), {
          selectedTierKey: selectedLandscapeTierKey,
          selectedCarePlanKey: selectedLandscapeCarePlanKey,
          additionalLineItems: landscapeAdditionalLineItems,
        }),
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
    hosted,
    landscapeAdditionalLineItems,
    landscapeOnly,
    liveShots,
    selectedLandscapeCarePlanKey,
    selectedLandscapeTierKey,
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
      emittedServerDraftSignatureRef.current = landscapeDraftSignature(
        projectInitialDraft.shots,
        nextActiveShot?.id ?? null,
        projectInitialDraft.proposal?.selectedTierKey ?? null,
        projectInitialDraft.proposal?.selectedCarePlanKey ?? null,
        projectInitialDraft.proposal?.additionalLineItems ?? [],
      );
      persistedItemCountRef.current = projectInitialDraft.shots.reduce(
        (total, shot) => total + shot.design.items.length,
        0,
      );
      setShots(projectInitialDraft.shots);
      setActiveShotId(nextActiveShot?.id ?? null);
      setProposalPreviews({});
      setSelectedLandscapeTierKey(projectInitialDraft.proposal?.selectedTierKey ?? null);
      setSelectedLandscapeCarePlanKey(projectInitialDraft.proposal?.selectedCarePlanKey ?? null);
      setLandscapeAdditionalLineItems(projectInitialDraft.proposal?.additionalLineItems ?? []);
      dispatch({
        type: "RESET",
        design: nextActiveShot?.design ?? EMPTY_DESIGN,
      });
      if (nextActiveShot) {
        dispatch({ type: "SET_DUSK", dusk: nextActiveShot.dusk });
      }
      setDraftReady(true);
    });
    return () => {
      cancelled = true;
    };
  }, [projectInitialDraft, projectResetKey, serverBacked]);

  // Fixture placement is the highest-value edit in this workflow. Queue it for
  // server persistence immediately; all other drawing edits keep the quiet-period
  // debounce below so dragging and aiming do not flood the API.
  useEffect(() => {
    const itemCount = liveShots.reduce((total, shot) => total + shot.design.items.length, 0);
    const fixtureWasAdded = itemCount > persistedItemCountRef.current;
    persistedItemCountRef.current = itemCount;
    if (!fixtureWasAdded || !landscapeOnly || !serverBacked || !emitProjectDraft || !draftReady) {
      return;
    }
    const nextActiveShotId = activeShot?.id ?? null;
    const signature = landscapeDraftSignature(
      liveShots,
      nextActiveShotId,
      selectedLandscapeTierKey,
      selectedLandscapeCarePlanKey,
      landscapeAdditionalLineItems,
    );
    emittedServerDraftSignatureRef.current = signature;
    emitProjectDraft(
      createLandscapeDraft(liveShots, nextActiveShotId, new Date().toISOString(), {
        selectedTierKey: selectedLandscapeTierKey,
        selectedCarePlanKey: selectedLandscapeCarePlanKey,
        additionalLineItems: landscapeAdditionalLineItems,
      }),
      { immediate: true },
    );
  }, [
    activeShot?.id,
    draftReady,
    emitProjectDraft,
    landscapeAdditionalLineItems,
    landscapeOnly,
    liveShots,
    selectedLandscapeCarePlanKey,
    selectedLandscapeTierKey,
    serverBacked,
  ]);

  // Server projects own persistence. Emit the same complete draft shape that the
  // browser-only builder stores, after one quiet period, without saving the
  // workspace-keyed legacy record or emitting the unchanged initial document.
  useEffect(() => {
    if (!landscapeOnly || !serverBacked || !emitProjectDraft || !draftReady) {
      return;
    }
    const nextActiveShotId = activeShot?.id ?? null;
    const signature = landscapeDraftSignature(
      liveShots,
      nextActiveShotId,
      selectedLandscapeTierKey,
      selectedLandscapeCarePlanKey,
      landscapeAdditionalLineItems,
    );
    if (signature === emittedServerDraftSignatureRef.current) return;

    const timer = window.setTimeout(() => {
      emittedServerDraftSignatureRef.current = signature;
      emitProjectDraft(
        createLandscapeDraft(liveShots, nextActiveShotId, new Date().toISOString(), {
          selectedTierKey: selectedLandscapeTierKey,
          selectedCarePlanKey: selectedLandscapeCarePlanKey,
          additionalLineItems: landscapeAdditionalLineItems,
        }),
      );
    }, 600);
    return () => window.clearTimeout(timer);
  }, [
    activeShot?.id,
    draftReady,
    emitProjectDraft,
    landscapeAdditionalLineItems,
    landscapeOnly,
    liveShots,
    selectedLandscapeCarePlanKey,
    selectedLandscapeTierKey,
    serverBacked,
  ]);

  const [takedown, setTakedown] = useState(false);
  const [storage, setStorage] = useState(false);
  // The rep's chosen Good/Better/Best seasonal package (a ChristmasPackage key).
  // null = no explicit pick yet; the resolver falls back to the most-inclusive
  // package, matching the server so the preview and the shared page agree.
  const [selectedPackage, setSelectedPackage] = useState<string | null>(null);
  // Internal-only per-linear-foot rate overrides for this estimate. null = use
  // the workspace's standard configured rate. Never shown to the client.
  const [perFtOverride, setPerFtOverride] = useState<number | null>(null);
  const [christmasPerFtOverride, setChristmasPerFtOverride] = useState<number | null>(null);
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
  // The draft quote just created from this design (its number is shown inline
  // with a link into Quotes). Cleared whenever the priced inputs change.
  const [quoteResult, setQuoteResult] = useState<{ number: string } | null>(null);
  const [aiOpen, setAiOpen] = useState(false);
  const [savingProposal, setSavingProposal] = useState(false);
  // What was last written onto the proposal, kept with the exact drawings it was
  // rendered from: the confirmation then falls away on the next stroke instead
  // of vouching for stale images.
  const [saved, setSaved] = useState<{
    at: string;
    shots: DesignerShot[];
  } | null>(null);
  const [saveError, setSaveError] = useState(false);

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

  // Which package the fixture types resolve against. The dedicated workspace
  // keeps its Good/Better/Best choice with the project, while the embedded
  // quote builder continues to own its selected tier.
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
  const tierKey =
    proposal?.tierKey ??
    (landscapeOnly ? effectiveLandscapeTierKey : (configuredTierKeys[0] ?? null));
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
  const products = useMemo(() => {
    const landscape =
      sells("landscape") && sellsLandscape
        ? [
            ...buildFixturePalette(fixtureResolution, transformerResolution),
            ...buildBistroCatalog(priceBook),
          ]
        : [];
    const holiday = buildCatalog(catalog).filter((product) =>
      product.style === "permanent" ? sells("permanent") : sells("christmas"),
    );
    return [...landscape, ...holiday];
  }, [sells, sellsLandscape, fixtureResolution, transformerResolution, priceBook, catalog]);
  const productById = useMemo(() => indexProducts(products), [products]);

  // ---- Design → server estimate inputs ----------------------------------
  // Totalled across every photo: front elevation plus back patio is one job and
  // one price. Each shot measures on its own calibration before it's summed, so
  // photos taken from different distances still add up correctly.
  const inputs = useMemo(
    () =>
      sumEstimateInputs(
        liveShots.map((shot) => designToEstimateInputs(shot.design, productById, shot.photo.width)),
      ),
    [liveShots, productById],
  );
  const feet = inputs.feet;
  /** Anything drawn on the photo that's on screen (gates the AI render). */
  const activeDesignHas = hasDesign(design);
  /** Anything drawn anywhere (gates the save — every drawn shot goes across). */
  const designHas = liveShots.some((shot) => hasDesign(shot.design));
  const { calibrated } = designScale(design, photo?.width ?? 0);

  // Placed fixtures, resolved through the current package into the product the
  // crew will actually pull. Counts only — the wizard prices them server-side.
  const fixtureLines = useMemo(
    () =>
      FIXTURE_TYPES.map((spec) => {
        const count = inputs.fixtures[spec.type] ?? 0;
        const resolved = fixtureResolution[spec.type];
        return {
          type: spec.type,
          label: spec.label,
          count,
          productName: resolved.item?.name ?? null,
          sku: resolved.itemId,
        };
      }).filter((line) => line.count > 0),
    [inputs.fixtures, fixtureResolution],
  );
  // Types the rep drew that this package doesn't sell. Never substituted with a
  // product from another package — the rep is told, and picks.
  const unresolvedFixtures = fixtureLines.filter((line) => !line.sku);
  const fixtureCount = fixtureLines.reduce((sum, line) => sum + line.count, 0);
  const transformerCount = useMemo(
    () =>
      liveShots.reduce(
        (total, shot) =>
          total +
          shot.design.items.filter(
            (item) => productById.get(item.productId)?.style === "transformer",
          ).length,
        0,
      ),
    [liveShots, productById],
  );
  const perFixtureSchedule = useMemo(
    () => buildPerFixtureSchedule(liveShots, products, priceBook ?? []),
    [liveShots, priceBook, products],
  );
  const numberedFixtureScheduleRows = useMemo<LandscapeFixtureScheduleRow[]>(
    () =>
      perFixtureSchedule.map((row) => ({
        id: row.itemId,
        number: row.number,
        itemId: row.itemId,
        label: row.fixtureType,
        productName: row.fixtureName,
        sku: row.fixtureSku,
        count: 1,
        beam: row.unresolved.join("; ") || "Resolved",
        lampCatalogItemId: row.lampCatalogItemId,
        accessories: row.accessoryNames,
      })),
    [perFixtureSchedule],
  );
  const fixtureScheduleRows = useMemo<LandscapeFixtureScheduleRow[]>(() => {
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
  }, [fixtureLines, liveShots, productById, transformerCount, transformerResolution]);
  const electricalLoad = useMemo(
    () =>
      calculateLandscapeElectricalLoad(
        fixtureLines.map((line) => ({
          id: line.type,
          label: line.label,
          quantity: line.count,
          item: fixtureResolution[line.type].item,
        })),
        { item: transformerResolution.item, quantity: transformerCount },
      ),
    [fixtureLines, fixtureResolution, transformerCount, transformerResolution],
  );
  const circuitLoads = useMemo(() => {
    const circuitInputs = liveShots.flatMap((shot, shotIndex) => {
      const scale = designScale(shot.design, shot.photo.width);
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
        return [
          {
            id: run.id,
            label: `${liveShots.length > 1 ? `L-${shotIndex + 1} · ` : ""}${
              run.circuitLabel ?? `C${circuitIndex + 1}`
            }`,
            lengthFeet: scale.calibrated ? polylineLength(run.points) * scale.ftPerPx : null,
            wireGauge: run.wireGauge ?? 12,
            sourceVoltage: run.sourceVoltage ?? 12,
            transformerAssigned,
            fixtures,
          },
        ];
      });
    });
    return calculateLandscapeCircuits(circuitInputs);
  }, [liveShots, productById, fixtureResolution]);
  const selectedTierWireItems = useMemo(
    () =>
      new Map<10 | 12, CatalogItemResponse | null>([
        [12, resolveTierWire(pricing, priceBook, tierKey, 12)],
        [10, resolveTierWire(pricing, priceBook, tierKey, 10)],
      ]),
    [priceBook, pricing, tierKey],
  );
  const supplierRows = useMemo(() => {
    const fixtures = fixtureLines.map((line) => ({
      label: line.label,
      quantity: line.count,
      item: fixtureResolution[line.type].item,
    }));
    if (transformerCount > 0) {
      fixtures.push({
        label: "Transformer",
        quantity: transformerCount,
        item: transformerResolution.item,
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
  }, [
    circuitLoads,
    fixtureLines,
    fixtureResolution,
    selectedTierWireItems,
    transformerCount,
    transformerResolution,
  ]);
  const hasLandscape = fixtureCount > 0 || transformerCount > 0 || inputs.bistro_feet > 0;

  const landscapeProposalPayload = useMemo<ProposalWizardPayload | null>(() => {
    if (!landscapeOnly || !pricing || !priceBook || !effectiveLandscapeTierKey) return null;
    return buildLandscapeProposalPayload({
      pricing,
      catalog: priceBook,
      fixtureCounts: inputs.fixtures,
      wireRuns: circuitLoads.map((circuit) => ({
        gauge: circuit.wireGauge,
        lengthFeet: circuit.lengthFeet,
      })),
      selectedTierKey: effectiveLandscapeTierKey,
      selectedCarePlanKey: selectedLandscapeCarePlanKey,
      additionalLineItems: landscapeAdditionalLineItems,
      contactId: landscapeProject?.contactId,
      opportunityId: landscapeProject?.opportunityId,
      serviceLocationId: landscapeProject?.serviceLocationId,
      lightingProjectId: landscapeProject?.projectId,
      title: landscapeProjectName,
    });
  }, [
    circuitLoads,
    effectiveLandscapeTierKey,
    inputs.fixtures,
    landscapeAdditionalLineItems,
    landscapeOnly,
    landscapeProject?.contactId,
    landscapeProject?.opportunityId,
    landscapeProject?.projectId,
    landscapeProject?.serviceLocationId,
    landscapeProjectName,
    priceBook,
    pricing,
    selectedLandscapeCarePlanKey,
  ]);
  const landscapeProposalSignature = useMemo(
    () => JSON.stringify(landscapeProposalPayload),
    [landscapeProposalPayload],
  );
  const landscapeProposalQuery = useQuery({
    queryKey: queryKeys.lightingProjects.proposalPreview(workspaceId, landscapeProposalSignature),
    queryFn: () => salesWizardApi.preview(workspaceId, landscapeProposalPayload!),
    enabled: Boolean(landscapeProposalPayload?.quantities?.length),
    placeholderData: keepPreviousData,
  });
  useEffect(() => {
    if (
      landscapeOnly &&
      effectiveLandscapeTierKey &&
      selectedLandscapeTierKey !== effectiveLandscapeTierKey
    ) {
      setSelectedLandscapeTierKey(effectiveLandscapeTierKey);
    }
  }, [effectiveLandscapeTierKey, landscapeOnly, selectedLandscapeTierKey]);
  useEffect(() => {
    if (
      selectedLandscapeCarePlanKey &&
      landscapeProposalQuery.data &&
      !(landscapeProposalQuery.data.care_plan?.options ?? []).some(
        (option) => option.key === selectedLandscapeCarePlanKey,
      )
    ) {
      setSelectedLandscapeCarePlanKey(null);
    }
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

  const estimateParams = useMemo<LinearFeetEstimateRequest>(
    () => ({
      feet,
      channels: 0,
      takedown,
      storage,
      per_ft_override: perFtOverride,
      christmas_per_ft_override: christmasPerFtOverride,
      christmas_items: inputs.christmas_items,
      selected_package: selectedPackage,
      custom_lines: customLineInputs,
    }),
    [
      feet,
      takedown,
      storage,
      perFtOverride,
      christmasPerFtOverride,
      inputs.christmas_items,
      selectedPackage,
      customLineInputs,
    ],
  );

  // Holiday pricing only: a landscape-only design has nothing for the roofline
  // comparison endpoint to price, and the Quote Builder owns landscape money. A
  // standalone line item is priced on its own, with or without a drawing — that
  // is the point of it — so it counts as something to price, share, and quote.
  const hasHolidayDesign =
    feet > 0 || Object.keys(inputs.christmas_items).length > 0 || customLineInputs.length > 0;

  const { data: estimate, isFetching } = useQuery({
    queryKey: queryKeys.estimator.compute(workspaceId, estimateParams),
    queryFn: () => estimatorApi.estimate(workspaceId, estimateParams),
    enabled: Boolean(photo) && hasHolidayDesign,
    placeholderData: keepPreviousData,
    staleTime: 60_000,
  });

  // Which sides a line item can be billed on. Falls back to the catalog probe so
  // the editor is available before anything is drawn — the standalone case, and
  // the reason this reads from a query rather than from what's on the photo.
  const sides = {
    permanent: Boolean((estimate ?? catalog)?.permanent.enabled),
    seasonal: Boolean((estimate ?? catalog)?.christmas.enabled),
  };

  // Resolve the seasonal package the rep is selling (explicit pick, else the
  // most-inclusive one). When packages are active the client sees this package's
  // total as the seasonal price, so the preview and the persisted share both
  // adopt it in place of the à la carte roofline+decor total.
  const selectedPkg = resolveSelectedPackage(estimate?.christmas_packages ?? [], selectedPackage);
  // The package's own total plus any standalone lines (which sit outside every
  // package); à la carte already includes them. Same rule the server applies.
  const christmasTotal = seasonalTotal(
    {
      total: estimate?.christmas.total ?? 0,
      custom_total: estimate?.christmas.custom_total,
    },
    selectedPkg,
  );

  // Mirror of the server's ``build_public_roofline_comparison`` so the preview
  // shows exactly what the shared page will render (same pattern as
  // ``resolveSelectedPackage`` mirroring the backend's recommended-package rule).
  // Roofline against roofline from the à la carte costs — never a package's,
  // which is $0 for a package that excludes the roofline.
  const rooflineView = useMemo(() => {
    if (!pricing?.roofline_comparison_enabled || !estimate) return null;
    if (!estimate.permanent.enabled || !estimate.christmas.enabled) return null;
    const seasonal = estimate.christmas.roofline_cost;
    const multiYear = round2(seasonal * estimate.years);
    return {
      permanent_total: estimate.permanent.roofline_cost,
      seasonal_total: seasonal,
      seasonal_multi_year: multiYear,
      savings: round2(multiYear - estimate.permanent.roofline_cost),
    };
  }, [pricing?.roofline_comparison_enabled, estimate]);

  // Any change to the priced inputs invalidates a previously saved link so the
  // "Saved to customer" confirmation can never read as current after an edit.
  const resetShare = useCallback(() => {
    setShareUrl(null);
    setShareToken(null);
    setSentTo(null);
    setSentVia(null);
    setSavedToCustomer(false);
    setQuoteResult(null);
  }, []);
  useEffect(() => {
    resetShare();
  }, [estimateParams, resetShare]);

  // ---- Shots (photos in this design) -------------------------------------
  /**
   * Park the active shot's drawing back in the list. Called before anything that
   * moves the reducer off it — switching, removing, adding — so a drawing is
   * never left behind in a reducer that's about to be reset.
   */
  const commitActive = useCallback(
    (list: DesignerShot[]) =>
      list.map((shot) => (shot.id === activeShot?.id ? { ...shot, design, dusk } : shot)),
    [activeShot?.id, design, dusk],
  );

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
    proposal?.onShotsChange(next);
    openShot(next.find((shot) => shot.id === id) ?? target);
  };

  const removeShot = (id: string) => {
    const index = shots.findIndex((shot) => shot.id === id);
    if (index < 0) return;
    // Committing first keeps the *other* shots' edits: if the rep deletes a
    // photo they aren't on, the one they were drawing must not lose its work.
    const next = commitActive(shots).filter((shot) => shot.id !== id);
    setShots(next);
    proposal?.onShotsChange(next);
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
    proposal?.onShotsChange(next);
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
      proposal?.onShotsChange(next);
      openShot(shot);
      // Only the first base image starts the estimate over. Later aerials/photos
      // are more of the same job, so estimate inputs stay in place.
      if (!shots.length) {
        setTakedown(false);
        setStorage(false);
        setPerFtOverride(null);
        setChristmasPerFtOverride(null);
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

  // ---- Save onto the proposal (Quote Builder host) -----------------------
  // Every drawn sheet is composited and sent together, so the proposal shows the
  // whole job. Blank sheets are omitted rather than sent as unmarked base imagery.
  const saveToProposal = async () => {
    if (!proposal || savingProposal) return;
    const drawn = liveShots.filter((shot) => hasDesign(shot.design));
    if (!drawn.length) return;
    setSavingProposal(true);
    setSaveError(false);
    // Park the active shot's drawing in the list (and in the host) before the
    // await: what's saved to the proposal is what re-opens in the designer.
    setShots(liveShots);
    proposal.onShotsChange(liveShots);
    try {
      const rendered = await Promise.all(
        drawn.map(async (shot) => ({
          image: await exportDesignJpeg(shot.photo, shot.design, productById, {
            dusk: shot.dusk,
          }),
          design: shot.design,
          dusk: shot.dusk,
        })),
      );
      proposal.onSave({
        shots: rendered,
        services,
        fixtures: inputs.fixtures as Partial<Record<FixtureType, number>>,
        rooflineFeet: feet,
        bistroFeet: inputs.bistro_feet,
      });
      setSaved({
        at: new Date().toLocaleTimeString([], {
          hour: "numeric",
          minute: "2-digit",
        }),
        shots: drawn,
      });
    } catch {
      setSaveError(true);
    } finally {
      setSavingProposal(false);
    }
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

  // Convert the drawn design into a real draft quote. ``side`` picks which
  // priced option the customer is buying; the seasonal side carries the chosen
  // package. Every line is recomputed server-side, so this only sends inputs.
  const createQuoteMutation = useMutation({
    mutationFn: (side: "permanent" | "seasonal") =>
      estimatorApi.createQuote(workspaceId, { ...shareParams, side }),
    onSuccess: (quote) => setQuoteResult({ number: quote.number }),
  });
  const quotePending = createQuoteMutation.isPending;

  // One-click "send the estimate", by email or text. Both buttons are always
  // visible on every estimate. If the rep hasn't saved a share link yet we mint
  // one first, then deliver it — so sending never depends on remembering to
  // press "Save & share" beforehand.
  const sendPending = shareMutation.isPending || deliverMutation.isPending;
  // The server's own words, not a generic retry line: a failed text usually
  // means something the rep can fix right now ("add a number under Settings",
  // "this number has opted out"), and that is exactly what gets swallowed by a
  // hardcoded "couldn't send".
  const sendFailure = deliverMutation.error ?? shareMutation.error;
  const sendError = sendFailure
    ? getApiErrorMessage(sendFailure, "Couldn’t send the estimate — try again.")
    : null;
  const canSend = (channel: SendChannel) =>
    hasHolidayDesign && (channel === "email" ? clientEmail : clientPhone).trim().length > 0;
  const sendEstimate = async (channel: SendChannel) => {
    if (!canSend(channel) || sendPending) return;
    setSendingChannel(channel);
    try {
      let token = shareToken;
      if (!token) {
        const shared = await shareMutation.mutateAsync();
        token = shared.token;
      }
      if (token) await deliverMutation.mutateAsync({ token, channel });
    } catch {
      // Surfaced to the rep via shareMutation/deliverMutation isError below.
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
  const onPermanentRateChange = makeRateHandler(setPerFtOverride);
  const onChristmasRateChange = makeRateHandler(setChristmasPerFtOverride);

  // The AI render prompt follows what was actually drawn: a landscape design
  // must never come back looking like a Christmas installation.
  const renderMode: EstimateRenderRequest["mode"] = hasLandscape
    ? "landscape"
    : estimate?.permanent.enabled && !estimate?.christmas.enabled
      ? "permanent"
      : "seasonal";

  const clientView: ComparisonView | null = estimate
    ? {
        currency: "USD",
        permanent: estimate.permanent,
        christmas: { enabled: estimate.christmas.enabled, total: christmasTotal },
        christmasName: selectedPkg ? packageName(selectedPkg) : null,
        difference: estimate.difference,
        years: estimate.years,
        temporary_multi_year: estimate.temporary_multi_year,
        permanent_one_time: estimate.permanent_one_time,
        multi_year_savings: estimate.multi_year_savings,
        permanent_perks: estimate.permanent_perks,
        christmas_perks: estimate.christmas_perks,
        // Feet-free ladder for the client preview: only each package's total
        // crosses over (never the roofline breakdown), so the rep sees exactly
        // the Good/Better/Best cards the homeowner gets, with their pick flagged.
        christmasPackages: (estimate.christmas_packages ?? []).map((pkg) => ({
          key: pkg.key,
          name: packageName(pkg),
          marker: pkg.marker,
          total: pkg.pricing.total,
          valueTag: pkg.value_tag,
          popular: pkg.popular,
          recommended: pkg.key === selectedPkg?.key,
          points: pkg.points,
          experience: pkg.experience,
        })),
        roofline: rooflineView,
        // Server-priced add-ons, itemized for the client exactly as the shared
        // page lists them — the preview is what the homeowner will see. A line
        // scoped to a tier they aren't being sold is already inside a different
        // card's total, so it is filtered out here the same way
        // ``get_public_comparison`` filters it, and the preview can't promise
        // work that isn't on this price.
        customLines: (estimate.custom_lines ?? [])
          .filter((line) => !line.package_key || line.package_key === selectedPkg?.key)
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

  // Derived, not stored: drawings are replaced immutably on every edit, so a
  // reference match across the drawn shots means the saved composites still show
  // what's on the photos. Adding or removing a shot invalidates it too.
  const drawnShots = liveShots.filter((shot) => hasDesign(shot.design));
  const savedAt =
    saved &&
    saved.shots.length === drawnShots.length &&
    saved.shots.every(
      (shot, i) =>
        shot.id === drawnShots[i]?.id &&
        shot.design === drawnShots[i]?.design &&
        shot.dusk === drawnShots[i]?.dusk,
    )
      ? saved.at
      : null;
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
  const landscapeCreateQuoteError = landscapeQuoteMutation.isError
    ? getApiErrorMessage(landscapeQuoteMutation.error, "Unable to create the draft quote.")
    : null;
  const landscapeQuoteDisabledReason = !serverBacked
    ? "Open a customer lighting project to create a CRM quote here."
    : !landscapeProject?.installationShotId
      ? "Select and save an installation sheet before creating a quote."
      : fixtureCount === 0
        ? "Place at least one fixture before creating a quote."
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
    const previewImages = liveShots.flatMap((shot) =>
      proposalPreviews[shot.id] ? [proposalPreviews[shot.id]] : [],
    );
    landscapeQuoteMutation.mutate({
      ...landscapeProposalPayload,
      night_preview: previewImages.length
        ? { image: previewImages[0], images: previewImages, services: ["landscape"] }
        : null,
    });
  };

  return (
    <div className={`cmp-view est-app${landscapeOnly ? " est-landscape-builder" : ""}`}>
      <div className={`est-topbar${serverBacked ? " ll-server-actionbar" : ""}`}>
        {landscapeOnly ? (
          !serverBacked ? (
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
          ) : null
        ) : (
          <div className="cmp-brand">Light Designer</div>
        )}
        <div className="est-topbar-actions">
          {landscapeOnly && !hosted && !serverBacked ? (
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
                  setShots(imported.shots);
                  setActiveShotId(first?.id ?? null);
                  dispatch({ type: "RESET", design: first?.design ?? EMPTY_DESIGN });
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
          {photo && !landscapeOnly ? (
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
          {photo && !hosted && !landscapeOnly ? (
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
              aria-label={serverBacked ? "AI render" : undefined}
              disabled={!activeDesignHas}
              title={
                activeDesignHas
                  ? undefined
                  : landscapeOnly
                    ? "Place at least one fixture before creating the aerial night render."
                    : "Place at least one fixture before creating a photorealistic render."
              }
              onClick={() => setAiOpen(true)}
            >
              <Sparkles aria-hidden="true" />
              {serverBacked ? "Render" : "AI render"}
            </button>
          ) : null}
          {landscapeOnly && !hosted ? (
            <button
              className="est-btn primary"
              type="button"
              aria-label="Open proposal pricing"
              onClick={() => setLandscapeTab("proposal")}
            >
              Quote
            </button>
          ) : null}
          {proposal ? (
            <>
              <button
                className="est-btn primary"
                type="button"
                disabled={!designHas || savingProposal}
                title={
                  designHas
                    ? `Save ${drawnShots.length} design${drawnShots.length === 1 ? "" : "s"} onto the proposal`
                    : landscapeOnly
                      ? "Add an aerial plan and draw the design first"
                      : "Add a photo and draw the design first"
                }
                onClick={() => void saveToProposal()}
              >
                {savingProposal
                  ? "Saving…"
                  : drawnShots.length > 1
                    ? `Save ${drawnShots.length} designs to proposal`
                    : "Save to proposal"}
              </button>
              <button
                className="est-btn"
                type="button"
                // Hand the drawings over on the way out so stepping back to the
                // quote and returning resumes every photo mid-design, saved or
                // not — the editor unmounts, and the host is where they live.
                onClick={() => {
                  proposal.onShotsChange(liveShots);
                  proposal.onClose();
                }}
              >
                Back to quote
              </button>
            </>
          ) : null}
        </div>
      </div>

      {landscapeOnly && !serverBacked ? (
        <LandscapeWorkspaceNav activeTab={landscapeTab} onChange={setLandscapeTab} />
      ) : null}

      {landscapeOnly && landscapeTab === "drawing" ? (
        <>
          <LandscapeDraftingToolbar
            products={products}
            activeTool={state.tool}
            hasPhoto={Boolean(photo)}
            canUndo={state.past.length > 0}
            toolsOpen={landscapeToolsOpen}
            legendOpen={landscapeLegendOpen}
            helpOpen={landscapeHelpOpen}
            sheetSize={landscapeSheetSize}
            onSheetSizeChange={setLandscapeSheetSize}
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
          <LandscapeWorkspacePanel
            tab={landscapeTab}
            shots={liveShots}
            rows={fixtureScheduleRows}
            scheduleRows={numberedFixtureScheduleRows}
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
            electricalLoad={electricalLoad}
            circuitLoads={circuitLoads}
            previews={proposalPreviews}
            previewsPending={proposalPreviewsPending}
            supplierRows={supplierRows}
            pricingTiers={landscapePricingTiers}
            proposalDocument={landscapeProposalQuery.data}
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
            onExportSupplierCsv={() => downloadSupplierCsv(supplierRows, landscapeProjectName)}
            onUpload={() => fileRef.current?.click()}
          />
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

          {hosted && (savedAt || saveError) ? (
            <div className={`est-hosted-status${saveError ? " error" : ""}`} role="status">
              {saveError
                ? "Couldn’t save the design — try again."
                : `Saved ${drawnShots.length} design${drawnShots.length === 1 ? "" : "s"} to the proposal at ${savedAt}. ${drawnShots.length === 1 ? "It shows" : "They show"} on the presentation and the client’s page.`}
            </div>
          ) : null}

          {photo ? (
            <>
              {landscapeOnly ? (
                <div className={`ll-sheet-stage ll-sheet-size-${landscapeSheetSize}`}>
                  <div className="ll-live-sheet">
                    <div className="ll-live-sheet-main">
                      <LightCanvas
                        photo={photo}
                        products={products}
                        state={state}
                        dispatch={dispatch}
                        perspective="aerial"
                        planImageRequestToken={planImageRequestToken}
                        onPlanImageRequestHandled={() => setPlanImageRequestToken(0)}
                      />
                      {landscapeLegendOpen ? (
                        <LandscapeLiveLegend rows={fixtureScheduleRows} />
                      ) : null}
                    </div>
                    <LandscapeSheetTitleBlock
                      fixtureCount={fixtureScheduleRows.reduce(
                        (sum, row) => sum + (row.id === "transformer" ? 0 : row.count),
                        0,
                      )}
                      calibrated={Boolean(design.calibration)}
                      sheetNumber={
                        Math.max(
                          liveShots.findIndex((shot) => shot.id === activeShot?.id),
                          0,
                        ) + 1
                      }
                      workspaceName={workspaceName}
                      projectName={landscapeProjectName}
                      contactName={landscapeContactName}
                    />
                  </div>
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
                  <ToolPalette products={products} state={state} dispatch={dispatch} />
                  <LightCanvas
                    // Remount per shot: zoom, pan and any half-drawn run belong to the
                    // photo they were made on and must not follow the rep to the next.
                    key={activeShot?.id}
                    photo={photo}
                    products={products}
                    state={state}
                    dispatch={dispatch}
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
                          {hosted
                            ? `Priced as ${tierLabel}. Saving pushes these counts into the quote, where the server prices them and expands each fixture’s parts list for the crew.`
                            : `Showing ${tierLabel} products. Landscape fixtures are priced in the Quote Builder, which expands each fixture’s parts list for the crew.`}
                        </p>
                        {!hosted ? (
                          <Link
                            className="est-btn est-save-btn"
                            href="/sales-wizard?service=landscape"
                          >
                            Price these in Quote Builder
                          </Link>
                        ) : null}
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
                        allowCustomLines={!hosted}
                      />
                    ) : null}

                    {!hosted && !landscapeOnly ? (
                      <>
                        <div className="est-options">
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
                          {estimate?.permanent.enabled ? (
                            <label className="est-opt-rate">
                              <span>Permanent $/ft</span>
                              <input
                                className="est-input"
                                type="number"
                                min={0}
                                step={1}
                                inputMode="decimal"
                                value={perFtOverride ?? ""}
                                placeholder={String(estimate.permanent.per_ft)}
                                onChange={(e) => onPermanentRateChange(e.target.value)}
                                aria-label="Internal permanent linear-foot rate override"
                              />
                              <span className="est-internal-badge">Internal</span>
                            </label>
                          ) : null}
                          {estimate?.christmas.enabled ? (
                            <label className="est-opt-rate">
                              <span>Seasonal $/ft</span>
                              <input
                                className="est-input"
                                type="number"
                                min={0}
                                step={1}
                                inputMode="decimal"
                                value={christmasPerFtOverride ?? ""}
                                placeholder={String(estimate.christmas.per_ft)}
                                onChange={(e) => onChristmasRateChange(e.target.value)}
                                aria-label="Internal seasonal linear-foot rate override"
                              />
                              <span className="est-internal-badge">Internal</span>
                            </label>
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
                                editCustomer(setClientPhone)(
                                  contact.phone_number ?? "",
                                );
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
                                  ? `Email the estimate to ${clientEmail.trim()}`
                                  : "Draw the holiday design and add a customer email to send the estimate"
                              }
                              onClick={() => void sendEstimate("email")}
                            >
                              {sendingChannel === "email" ? (
                                "Sending…"
                              ) : (
                                <>
                                  <Mail aria-hidden="true" />
                                  Email estimate
                                </>
                              )}
                            </button>
                            <button
                              className="est-btn primary est-save-btn"
                              type="button"
                              disabled={!canSend("sms") || sendPending}
                              title={
                                canSend("sms")
                                  ? `Text the estimate to ${clientPhone.trim()}`
                                  : "Draw the holiday design and add a customer phone to text the estimate"
                              }
                              onClick={() => void sendEstimate("sms")}
                            >
                              {sendingChannel === "sms" ? (
                                "Sending…"
                              ) : (
                                <>
                                  <MessageSquareText aria-hidden="true" />
                                  Text estimate
                                </>
                              )}
                            </button>
                          </div>
                          <button
                            className="est-btn est-save-btn"
                            type="button"
                            disabled={!hasHolidayDesign || shareMutation.isPending}
                            onClick={() => shareMutation.mutate()}
                          >
                            {shareMutation.isPending ? "Saving…" : "Save & share link only"}
                          </button>
                          {sendError ? (
                            <div className="est-send-row">
                              <span className="est-send-error">{sendError}</span>
                            </div>
                          ) : null}

                          {estimate &&
                          (estimate.permanent.enabled || estimate.christmas.enabled) ? (
                            <div className="est-quote-convert">
                              <div className="est-quote-convert-title">
                                Turn this design into a quote
                              </div>
                              {estimate.permanent.enabled ? (
                                <button
                                  className="est-btn primary est-save-btn"
                                  type="button"
                                  disabled={!hasHolidayDesign || quotePending}
                                  onClick={() => createQuoteMutation.mutate("permanent")}
                                >
                                  {quotePending
                                    ? "Creating…"
                                    : estimate.christmas.enabled
                                      ? "Create permanent quote"
                                      : "Create quote"}
                                </button>
                              ) : null}
                              {estimate.christmas.enabled ? (
                                <button
                                  className="est-btn est-save-btn"
                                  type="button"
                                  disabled={!hasHolidayDesign || quotePending}
                                  onClick={() => createQuoteMutation.mutate("seasonal")}
                                >
                                  {quotePending
                                    ? "Creating…"
                                    : estimate.permanent.enabled
                                      ? "Create seasonal quote"
                                      : "Create quote"}
                                </button>
                              ) : null}
                              <div className="est-customer-hint">
                                Creates a draft quote with itemized, server-priced lines. Review and
                                send it from Quotes.
                              </div>
                              {quoteResult ? (
                                <div className="est-saved-note">
                                  Quote {quoteResult.number} created ·{" "}
                                  <Link href="/quotes" className="est-quote-link">
                                    Open in Quotes
                                  </Link>
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
                            {sentTo ? (
                              <div className="est-send-row">
                                <span className="est-sent-note">
                                  {sentVia === "sms" ? "Texted to" : "Emailed to"} {sentTo}
                                </span>
                              </div>
                            ) : null}
                          </div>
                        ) : null}
                      </>
                    ) : null}
                  </div>
                </div>
              )}

              {viewMode === "client" && !hosted ? (
                // The client theme follows what's being sold: a Christmas quote gets
                // the holiday palette, a landscape quote stays brass-on-black. The
                // preview mirrors whatever the homeowner will actually see.
                <div className={`est-client-preview ${clientThemeClass(services)}`.trim()}>
                  <ServiceValueProps services={services} pricing={pricing} tierKey={tierKey} />
                  {clientView ? <ComparisonCard view={clientView} /> : null}
                </div>
              ) : null}

              {aiOpen && photo ? (
                <AIRenderModal
                  workspaceId={workspaceId}
                  photo={photo}
                  design={design}
                  productById={productById}
                  mode={renderMode}
                  onClose={() => setAiOpen(false)}
                />
              ) : null}
            </>
          ) : landscapeOnly ? (
            draftReady ? (
              <LandscapeWelcome
                workspaceName={workspaceName}
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
    </div>
  );
}
