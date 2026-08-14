"use client";

import {
  Cable,
  Check,
  ChevronDown,
  CircleDot,
  Download,
  Eye,
  FileJson,
  Fullscreen,
  HelpCircle,
  Highlighter,
  ImageIcon,
  MousePointer2,
  Presentation,
  RotateCcw,
  Ruler,
  Sparkles,
  Trash2,
  Undo2,
  Upload,
} from "lucide-react";
import { forwardRef, useId, type ButtonHTMLAttributes, type ComponentType } from "react";

import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { FIXTURE_MARKER_COLORS } from "@/lib/estimator/marker-colors";
import type { LandscapePaperSize, LandscapePlanFit } from "@/lib/estimator/types";
import { cn } from "@/lib/utils";

export type DrawingStudioAction =
  | "place-aerial"
  | "select"
  | "undo"
  | "wire"
  | "highlight"
  | "fixture-numbers"
  | "set-scale"
  | "measurements-visible"
  | "fit-contain"
  | "fit-cover"
  | "opacity-25"
  | "opacity-50"
  | "opacity-75"
  | "opacity-100"
  | "clear-design"
  | "clear-symbols"
  | "add-photo"
  | "clear-wires"
  | "source-voltage-12"
  | "source-voltage-13"
  | "source-voltage-15"
  | "legend-visible"
  | "legend-left"
  | "legend-right"
  | "legend-up"
  | "legend-down"
  | "legend-smaller"
  | "legend-larger"
  | "recount"
  | "halos-visible"
  | "import-project"
  | "export-project"
  | "fullscreen"
  | "present"
  | "toggle-preview"
  | "render"
  | "download-pdf"
  | "help";

interface DrawingToolbarProps {
  paperSize: LandscapePaperSize;
  activeAction?: DrawingStudioAction;
  hasAerial: boolean;
  hasDrawing: boolean;
  hasPlanSymbols: boolean;
  canUndo: boolean;
  canWire: boolean;
  canRender: boolean;
  duskPreview: boolean;
  renderDisabledReason?: string;
  markerColor: string | null;
  planFit: LandscapePlanFit;
  planOpacity: number;
  legendScale: number;
  sourceVoltage: number;
  fixtureNumbersVisible: boolean;
  measurementsVisible: boolean;
  legendVisible: boolean;
  halosVisible: boolean;
  onPaperSizeChange: (size: LandscapePaperSize) => void;
  onMarkerColorChange: (color: string) => void;
  onAction: (action: DrawingStudioAction) => void;
  fixtureTools?: Array<{
    id: string;
    label: string;
    icon: ComponentType<{ className?: string; "aria-hidden"?: boolean }>;
    active?: boolean;
    onSelect: () => void;
  }>;
}

const paperSizeLabels: Record<LandscapePaperSize, string> = {
  tabloid: "Tabloid - 17 x 11 in",
  "super-b": "Super B - 19 x 13 in",
  letter: "Letter - 11 x 8.5 in",
  "arch-c": "ARCH C - 24 x 18 in",
  "arch-d": "ARCH D - 36 x 24 in",
  "ansi-d": "ANSI D - 34 x 22 in",
};

interface ToolbarButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  icon?: ComponentType<{ className?: string; "aria-hidden"?: boolean }>;
  active?: boolean;
}

const ToolbarButton = forwardRef<HTMLButtonElement, ToolbarButtonProps>(
  ({ icon: Icon, active, className, children, ...props }, ref) => (
    <button
      ref={ref}
      type="button"
      aria-pressed={active === undefined ? undefined : active}
      className={cn(
        "inline-flex h-8 min-w-8 items-center justify-center gap-1.5 rounded border border-white/15 bg-[#1a1a1a] px-2.5 text-[11px] font-semibold text-[#e5e3de] transition-[color,background-color,border-color] duration-150 hover:border-white/30 hover:bg-[#242424] hover:text-white focus-visible:z-10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#e2b35f] focus-visible:ring-offset-1 focus-visible:ring-offset-[#0b0b0b] disabled:cursor-not-allowed disabled:opacity-45 motion-reduce:transition-none",
        active &&
          "border-[#d0a153] bg-[#d0a153] text-[#15130f] hover:bg-[#ddb465] hover:text-black",
        className,
      )}
      {...props}
    >
      {Icon ? <Icon className="size-3.5 shrink-0" aria-hidden /> : null}
      {children}
    </button>
  ),
);
ToolbarButton.displayName = "ToolbarButton";

const MenuButton = forwardRef<HTMLButtonElement, ToolbarButtonProps & { label: string }>(
  ({ label, ...props }, ref) => (
    <ToolbarButton ref={ref} {...props}>
      {label}
      <ChevronDown className="size-3.5 shrink-0" aria-hidden="true" />
    </ToolbarButton>
  ),
);
MenuButton.displayName = "MenuButton";

function MarkerPalette({
  value,
  onChange,
}: {
  value: string | null;
  onChange: (color: string) => void;
}) {
  const groupName = useId();
  return (
    <fieldset className="flex min-w-0 items-center gap-2" aria-label="Fixture marker color">
      <legend className="sr-only">Fixture marker color</legend>
      <span
        className="shrink-0 text-[10px] font-semibold uppercase tracking-[0.11em] text-[#a9a69f]"
        aria-hidden="true"
      >
        Marker
      </span>
      <div className="grid grid-cols-8 gap-1">
        {FIXTURE_MARKER_COLORS.map((marker) => {
          const selected = value?.toLowerCase() === marker.value.toLowerCase();
          return (
            <label
              key={marker.value}
              className="relative grid size-6 cursor-pointer place-items-center rounded-full"
              title={marker.name}
            >
              <input
                className="peer sr-only"
                type="radio"
                name={groupName}
                value={marker.value}
                checked={selected}
                onChange={() => onChange(marker.value)}
              />
              <span
                className="ll-marker-swatch grid size-[18px] place-items-center rounded-full border border-white/45 shadow-[0_0_0_1px_rgba(0,0,0,0.75)] transition-[box-shadow] duration-150 peer-checked:shadow-[0_0_0_2px_#0b0b0b,0_0_0_4px_#e2b35f] peer-focus-visible:shadow-[0_0_0_2px_#0b0b0b,0_0_0_5px_#ffffff] motion-reduce:transition-none"
                style={{ backgroundColor: marker.value }}
                aria-hidden="true"
              >
                <Check
                  className={cn(
                    "size-3 stroke-[3] transition-opacity duration-150 motion-reduce:transition-none",
                    selected ? "opacity-100" : "opacity-0",
                    marker.darkForeground ? "text-black" : "text-white",
                  )}
                />
              </span>
              <span className="sr-only">{marker.name}</span>
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}

export function DrawingToolbar(props: DrawingToolbarProps) {
  const action = props.onAction;
  const noAerialReason = "Place a top-down aerial before using this drawing tool.";

  return (
    <section
      className="ll-drawing-toolbar border-b border-[#a98336] bg-[#0b0b0b] text-white"
      aria-label="Drawing toolbar"
    >
      <div className="flex flex-wrap items-center gap-2 border-b border-white/10 px-2 py-2 sm:px-3">
        <div className="flex shrink-0 items-center gap-2" role="group" aria-label="Drawing sheet">
          <strong className="px-1 text-[11px] font-black uppercase tracking-[0.24em] text-[#f2f0eb]">
            Maxteriors
          </strong>
          <label className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-[0.1em] text-[#aaa69e]">
            Sheet
            <select
              value={props.paperSize}
              onChange={(event) =>
                props.onPaperSizeChange(event.target.value as LandscapePaperSize)
              }
              className="h-8 max-w-48 rounded border border-white/20 bg-[#1a1a1a] ps-2 pe-8 text-[11px] normal-case tracking-normal text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#e2b35f]"
            >
              {Object.entries(paperSizeLabels).map(([size, label]) => (
                <option key={size} value={size}>
                  {label}
                </option>
              ))}
            </select>
          </label>
        </div>

        <ToolbarButton icon={ImageIcon} onClick={() => action("place-aerial")}>
          {props.hasAerial ? "Replace aerial" : "Place aerial"}
        </ToolbarButton>

        <MarkerPalette value={props.markerColor} onChange={props.onMarkerColorChange} />

        <div className="inline-flex shrink-0 gap-1" role="group" aria-label="Primary drawing modes">
          <ToolbarButton
            icon={MousePointer2}
            active={props.activeAction === "select"}
            disabled={!props.hasAerial}
            title={props.hasAerial ? "Select and edit plan items" : noAerialReason}
            onClick={() => action("select")}
          >
            Select
          </ToolbarButton>
          <ToolbarButton
            icon={Undo2}
            disabled={!props.canUndo}
            title={props.canUndo ? "Undo the last drawing change" : "Nothing to undo."}
            onClick={() => action("undo")}
          >
            Undo
          </ToolbarButton>
        </div>

        <div className="inline-flex shrink-0 gap-1" role="group" aria-label="Plan display modes">
          <ToolbarButton
            icon={Cable}
            active={props.activeAction === "wire"}
            disabled={!props.hasAerial || !props.canWire}
            title={
              !props.hasAerial
                ? noAerialReason
                : props.canWire
                  ? "Toggle wire drawing mode"
                  : "No wire product is configured in the price book."
            }
            onClick={() => action("wire")}
          >
            Wiring: {props.activeAction === "wire" ? "On" : "Off"}
          </ToolbarButton>
          <ToolbarButton
            icon={Highlighter}
            active={props.activeAction === "highlight"}
            disabled={!props.hasAerial}
            title={props.hasAerial ? "Toggle highlight drawing mode" : noAerialReason}
            onClick={() => action("highlight")}
          >
            Highlight
          </ToolbarButton>
          <ToolbarButton
            icon={CircleDot}
            active={props.fixtureNumbersVisible}
            onClick={() => action("fixture-numbers")}
          >
            Fixture #: {props.fixtureNumbersVisible ? "On" : "Off"}
          </ToolbarButton>
        </div>

        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <MenuButton label="Plan" />
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start" className="w-64">
            {!props.hasAerial ? <DropdownMenuLabel>{noAerialReason}</DropdownMenuLabel> : null}
            <DropdownMenuItem disabled={!props.hasAerial} onSelect={() => action("set-scale")}>
              <Ruler />
              Set scale
            </DropdownMenuItem>
            <DropdownMenuCheckboxItem
              checked={props.measurementsVisible}
              onCheckedChange={() => action("measurements-visible")}
            >
              Show saved measurements
            </DropdownMenuCheckboxItem>
            <DropdownMenuSeparator />
            <DropdownMenuLabel>Base aerial fit</DropdownMenuLabel>
            <DropdownMenuRadioGroup
              value={props.planFit}
              onValueChange={(value) => action(value === "cover" ? "fit-cover" : "fit-contain")}
            >
              <DropdownMenuRadioItem value="contain">Contain full aerial</DropdownMenuRadioItem>
              <DropdownMenuRadioItem value="cover">Cover drawing area</DropdownMenuRadioItem>
            </DropdownMenuRadioGroup>
            <DropdownMenuLabel>Base aerial opacity</DropdownMenuLabel>
            <DropdownMenuRadioGroup
              value={String(Math.round(props.planOpacity * 100))}
              onValueChange={(value) => action(`opacity-${value}` as DrawingStudioAction)}
            >
              <DropdownMenuRadioItem value="25">25%</DropdownMenuRadioItem>
              <DropdownMenuRadioItem value="50">50%</DropdownMenuRadioItem>
              <DropdownMenuRadioItem value="75">75%</DropdownMenuRadioItem>
              <DropdownMenuRadioItem value="100">100%</DropdownMenuRadioItem>
            </DropdownMenuRadioGroup>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              disabled={!props.hasDrawing}
              variant="destructive"
              onSelect={() => action("clear-design")}
            >
              <RotateCcw />
              Clear fixtures and wiring
            </DropdownMenuItem>
            <DropdownMenuItem
              disabled={!props.hasPlanSymbols}
              variant="destructive"
              onSelect={() => action("clear-symbols")}
            >
              <Trash2 />
              Clear plan annotations
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>

        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <MenuButton label="Add" />
          </DropdownMenuTrigger>
          <DropdownMenuContent
            align="start"
            className="max-h-[min(70vh,28rem)] w-64 overflow-y-auto"
          >
            {!props.hasAerial ? <DropdownMenuLabel>{noAerialReason}</DropdownMenuLabel> : null}
            <DropdownMenuLabel>Fixture types</DropdownMenuLabel>
            {props.fixtureTools?.map(({ id, label, icon: Icon, active, onSelect }) => (
              <DropdownMenuItem
                key={id}
                disabled={!props.hasAerial}
                onSelect={onSelect}
                className={cn(active && "font-semibold")}
              >
                <Icon className="size-4" aria-hidden />
                {label}
                {active ? <Check className="ms-auto size-4" aria-hidden /> : null}
              </DropdownMenuItem>
            ))}
            <DropdownMenuSeparator />
            <DropdownMenuItem disabled={!props.hasAerial} onSelect={() => action("add-photo")}>
              <ImageIcon />
              Supplemental detail photo
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>

      <div className="flex flex-wrap items-center gap-1 px-2 py-1.5 sm:px-3">
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <MenuButton label="Wiring" icon={Cable} active={props.activeAction === "wire"} />
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start" className="w-60">
            {!props.canWire ? (
              <DropdownMenuLabel>
                No wire product is configured in the price book.
              </DropdownMenuLabel>
            ) : null}
            <DropdownMenuItem
              disabled={!props.hasAerial || !props.canWire}
              onSelect={() => action("wire")}
            >
              <Cable />
              Draw wire route
            </DropdownMenuItem>
            <DropdownMenuItem
              disabled={!props.hasDrawing}
              variant="destructive"
              onSelect={() => action("clear-wires")}
            >
              <Trash2 />
              Clear wire routes
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuLabel>Default source voltage</DropdownMenuLabel>
            <DropdownMenuRadioGroup
              value={String(props.sourceVoltage)}
              onValueChange={(value) => action(`source-voltage-${value}` as DrawingStudioAction)}
            >
              <DropdownMenuRadioItem value="12">12 V</DropdownMenuRadioItem>
              <DropdownMenuRadioItem value="13">13 V</DropdownMenuRadioItem>
              <DropdownMenuRadioItem value="15">15 V</DropdownMenuRadioItem>
            </DropdownMenuRadioGroup>
          </DropdownMenuContent>
        </DropdownMenu>

        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <MenuButton label="Legend" />
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start">
            <DropdownMenuCheckboxItem
              checked={props.legendVisible}
              onCheckedChange={() => action("legend-visible")}
            >
              Show legend
            </DropdownMenuCheckboxItem>
            <DropdownMenuItem onSelect={() => action("recount")}>
              <RotateCcw />
              Recount fixtures
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuLabel>Legend position</DropdownMenuLabel>
            <DropdownMenuItem onSelect={() => action("legend-left")}>Move left</DropdownMenuItem>
            <DropdownMenuItem onSelect={() => action("legend-right")}>Move right</DropdownMenuItem>
            <DropdownMenuItem onSelect={() => action("legend-up")}>Move up</DropdownMenuItem>
            <DropdownMenuItem onSelect={() => action("legend-down")}>Move down</DropdownMenuItem>
            <DropdownMenuLabel>Legend size</DropdownMenuLabel>
            <DropdownMenuItem
              disabled={props.legendScale <= 0.6}
              onSelect={() => action("legend-smaller")}
            >
              Smaller
            </DropdownMenuItem>
            <DropdownMenuItem
              disabled={props.legendScale >= 1.6}
              onSelect={() => action("legend-larger")}
            >
              Larger
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuCheckboxItem
              checked={props.halosVisible}
              onCheckedChange={() => action("halos-visible")}
            >
              Show light halos
            </DropdownMenuCheckboxItem>
          </DropdownMenuContent>
        </DropdownMenu>

        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <MenuButton label="File" />
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start" className="w-60">
            <DropdownMenuItem onSelect={() => action("import-project")}>
              <Upload />
              Open editable project
            </DropdownMenuItem>
            <DropdownMenuItem onSelect={() => action("export-project")}>
              <FileJson />
              Save editable project
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem onSelect={() => action("fullscreen")}>
              <Fullscreen />
              Full screen
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>

        <ToolbarButton icon={HelpCircle} onClick={() => action("help")}>
          Help
        </ToolbarButton>

        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <MenuButton label="Present" icon={Presentation} />
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start" className="w-64">
            <DropdownMenuItem onSelect={() => action("toggle-preview")}>
              <Eye />
              {props.duskPreview ? "Show original aerial" : "Show dusk plan"}
            </DropdownMenuItem>
            <DropdownMenuItem onSelect={() => action("present")}>
              <Presentation />
              Open proposal preview
            </DropdownMenuItem>
            <DropdownMenuItem disabled={!props.canRender} onSelect={() => action("render")}>
              <Sparkles />
              Create dusk render
            </DropdownMenuItem>
            {!props.canRender && props.renderDisabledReason ? (
              <DropdownMenuLabel>{props.renderDisabledReason}</DropdownMenuLabel>
            ) : null}
          </DropdownMenuContent>
        </DropdownMenu>

        <ToolbarButton
          icon={Download}
          className="border-[#c99b4d] bg-[#c99b4d] px-3 text-[#15130f] hover:border-[#ddb465] hover:bg-[#ddb465] hover:text-black"
          onClick={() => action("download-pdf")}
        >
          Download PDF
        </ToolbarButton>
      </div>
    </section>
  );
}
