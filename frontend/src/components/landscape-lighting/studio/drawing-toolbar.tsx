"use client";

import {
  ArrowRight,
  Cable,
  ChevronDown,
  CircleDot,
  Download,
  Eye,
  EyeOff,
  FileJson,
  Fullscreen,
  HelpCircle,
  Highlighter,
  ImageIcon,
  Layers3,
  LineChart,
  Maximize2,
  MousePointer2,
  Move,
  Palette,
  Presentation,
  Printer,
  Redo2,
  RotateCcw,
  Ruler,
  Sparkles,
  SquareStack,
  StickyNote,
  Trash2,
  TreePine,
  Undo2,
  Upload,
  Zap,
} from "lucide-react";
import { forwardRef, type ComponentProps, type ComponentType } from "react";

import { Button } from "@/components/ui/button";
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
import type { LandscapePaperSize } from "@/lib/estimator/types";
import { cn } from "@/lib/utils";

export type DrawingStudioAction =
  | "select"
  | "undo"
  | "redo"
  | "wire"
  | "highlight"
  | "fixture-numbers"
  | "set-scale"
  | "measure"
  | "measurements-visible"
  | "clear-plan"
  | "fit-contain"
  | "fit-cover"
  | "plan-fade"
  | "automatic-design"
  | "clear-design"
  | "clear-symbols"
  | "add-note"
  | "add-line"
  | "add-tree"
  | "add-photo"
  | "add-revision"
  | "draw-wire"
  | "end-run"
  | "undo-point"
  | "clear-wires"
  | "draw-arrow"
  | "clear-arrows"
  | "assign-zone"
  | "source-voltage"
  | "legend-visible"
  | "legend-move"
  | "legend-smaller"
  | "legend-larger"
  | "recount"
  | "halos-visible"
  | "import-project"
  | "export-project"
  | "download-sheets"
  | "print"
  | "fullscreen"
  | "present"
  | "download-pdf"
  | "help";

interface DrawingToolbarProps {
  paperSize: LandscapePaperSize;
  activeAction?: DrawingStudioAction;
  canUndo: boolean;
  canRedo: boolean;
  fixtureNumbersVisible: boolean;
  measurementsVisible: boolean;
  legendVisible: boolean;
  halosVisible: boolean;
  onPaperSizeChange: (size: LandscapePaperSize) => void;
  onAction: (action: DrawingStudioAction) => void;
  fixtureTools?: Array<{
    id: string;
    label: string;
    icon: ComponentType<{ className?: string; "aria-hidden"?: boolean }>;
    active?: boolean;
    onSelect: () => void;
  }>;
}

const ToolButton = ({
  label,
  icon: Icon,
  action,
  active,
  disabled,
  onAction,
}: {
  label: string;
  icon: ComponentType<{ className?: string; "aria-hidden"?: boolean }>;
  action: DrawingStudioAction;
  active?: boolean;
  disabled?: boolean;
  onAction: (action: DrawingStudioAction) => void;
}) => (
  <button
    type="button"
    disabled={disabled}
    aria-pressed={active}
    onClick={() => onAction(action)}
    className={cn(
      "flex h-11 min-w-14 flex-col items-center justify-center gap-0.5 border-r border-white/10 px-2 text-[10px] font-semibold uppercase tracking-wide text-neutral-300 transition-[color,background-color] duration-150 hover:bg-white/10 hover:text-white focus-visible:z-10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-amber-400 disabled:opacity-40 motion-reduce:transition-none",
      active && "bg-amber-400 text-black hover:bg-amber-300 hover:text-black",
    )}
  >
    <Icon className="size-4" aria-hidden />
    {label}
  </button>
);

const MenuButton = forwardRef<
  HTMLButtonElement,
  ComponentProps<typeof Button> & { label: string }
>(({ label, ...props }, ref) => (
  <Button
    ref={ref}
    type="button"
    variant="ghost"
    className="h-11 rounded-none border-r border-white/10 px-3 text-xs font-semibold uppercase tracking-wide text-neutral-200 hover:bg-white/10 hover:text-white data-[state=open]:bg-white/10"
    {...props}
  >
    {label}
    <ChevronDown className="size-3.5" aria-hidden="true" />
  </Button>
));
MenuButton.displayName = "MenuButton";

export function DrawingToolbar(props: DrawingToolbarProps) {
  const action = props.onAction;
  return (
    <section className="overflow-x-auto bg-neutral-900 [scrollbar-color:#a98336_#171717]" aria-label="Drawing toolbar">
      <div className="flex min-w-max items-stretch border-b border-black">
        <label className="flex h-11 items-center gap-2 border-r border-white/10 px-3 text-xs font-semibold uppercase tracking-wide text-neutral-300">
          Paper
          <select
            value={props.paperSize}
            onChange={(event) => props.onPaperSizeChange(event.target.value as LandscapePaperSize)}
            className="h-8 rounded border border-white/20 bg-black ps-2 pe-8 text-xs text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400"
          >
            <option value="tabloid">Tabloid</option>
            <option value="super-b">Super B</option>
            <option value="letter">Letter</option>
            <option value="arch-c">ARCH C</option>
            <option value="arch-d">ARCH D</option>
            <option value="ansi-d">ANSI D</option>
          </select>
        </label>
        <ToolButton label="Select" icon={MousePointer2} action="select" active={props.activeAction === "select"} onAction={action} />
        <ToolButton label="Undo" icon={Undo2} action="undo" disabled={!props.canUndo} onAction={action} />
        <ToolButton label="Redo" icon={Redo2} action="redo" disabled={!props.canRedo} onAction={action} />
        <ToolButton label="Wiring" icon={Cable} action="wire" active={props.activeAction === "wire"} onAction={action} />
        <ToolButton label="Highlight" icon={Highlighter} action="highlight" active={props.activeAction === "highlight"} onAction={action} />
        <ToolButton label="Numbers" icon={CircleDot} action="fixture-numbers" active={props.fixtureNumbersVisible} onAction={action} />
        {props.fixtureTools?.map(({ id, label, icon: Icon, active, onSelect }) => (
          <button
            key={id}
            type="button"
            aria-pressed={active}
            title={`Place ${label}`}
            onClick={onSelect}
            className={cn(
              "flex h-11 min-w-16 flex-col items-center justify-center gap-0.5 border-r border-white/10 px-2 text-[10px] font-semibold uppercase tracking-wide text-neutral-300 transition-[color,background-color] duration-150 hover:bg-white/10 hover:text-white focus-visible:z-10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-amber-400 motion-reduce:transition-none",
              active && "bg-amber-400 text-black hover:bg-amber-300 hover:text-black",
            )}
          >
            <Icon className="size-4" aria-hidden />
            {label}
          </button>
        ))}

        <DropdownMenu>
          <DropdownMenuTrigger asChild><MenuButton label="Plan" /></DropdownMenuTrigger>
          <DropdownMenuContent align="start" className="w-64">
            <DropdownMenuItem onSelect={() => action("set-scale")}><Ruler />Set scale</DropdownMenuItem>
            <DropdownMenuItem onSelect={() => action("measure")}><LineChart />Measure distance</DropdownMenuItem>
            <DropdownMenuCheckboxItem checked={props.measurementsVisible} onCheckedChange={() => action("measurements-visible")}>Show measurements</DropdownMenuCheckboxItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem onSelect={() => action("fit-contain")}><MinimizePlanIcon />Contain plan</DropdownMenuItem>
            <DropdownMenuItem onSelect={() => action("fit-cover")}><Maximize2 />Cover plan</DropdownMenuItem>
            <DropdownMenuItem onSelect={() => action("plan-fade")}><Palette />Plan opacity</DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem onSelect={() => action("automatic-design")}><Sparkles />Preview automatic design</DropdownMenuItem>
            <DropdownMenuItem onSelect={() => action("clear-design")}><RotateCcw />Clear fixture design</DropdownMenuItem>
            <DropdownMenuItem onSelect={() => action("clear-symbols")}><Trash2 />Clear plan symbols</DropdownMenuItem>
            <DropdownMenuItem variant="destructive" onSelect={() => action("clear-plan")}><Trash2 />Clear plan</DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>

        <DropdownMenu>
          <DropdownMenuTrigger asChild><MenuButton label="Add" /></DropdownMenuTrigger>
          <DropdownMenuContent align="start">
            <DropdownMenuItem onSelect={() => action("add-note")}><StickyNote />Note</DropdownMenuItem>
            <DropdownMenuItem onSelect={() => action("add-line")}><LineChart />Line</DropdownMenuItem>
            <DropdownMenuItem onSelect={() => action("add-tree")}><TreePine />Tree symbol</DropdownMenuItem>
            <DropdownMenuItem onSelect={() => action("add-photo")}><ImageIcon />Photo inset</DropdownMenuItem>
            <DropdownMenuItem onSelect={() => action("add-revision")}><SquareStack />Revision row</DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>

        <DropdownMenu>
          <DropdownMenuTrigger asChild><MenuButton label="Wiring" /></DropdownMenuTrigger>
          <DropdownMenuContent align="start" className="w-60">
            <DropdownMenuItem onSelect={() => action("draw-wire")}><Cable />Draw named run</DropdownMenuItem>
            <DropdownMenuItem onSelect={() => action("end-run")}><CircleDot />End run</DropdownMenuItem>
            <DropdownMenuItem onSelect={() => action("undo-point")}><Undo2 />Undo wire point</DropdownMenuItem>
            <DropdownMenuItem onSelect={() => action("clear-wires")}><Trash2 />Clear wire runs</DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem onSelect={() => action("draw-arrow")}><ArrowRight />Draw arrow</DropdownMenuItem>
            <DropdownMenuItem onSelect={() => action("clear-arrows")}><Trash2 />Clear arrows</DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem onSelect={() => action("assign-zone")}><Zap />Assign transformer zone</DropdownMenuItem>
            <DropdownMenuLabel>Branches use separate named runs</DropdownMenuLabel>
            <DropdownMenuRadioGroup value="13" onValueChange={() => action("source-voltage")}>
              <DropdownMenuRadioItem value="12">12 V source</DropdownMenuRadioItem>
              <DropdownMenuRadioItem value="13">13 V source</DropdownMenuRadioItem>
              <DropdownMenuRadioItem value="14">14 V source</DropdownMenuRadioItem>
              <DropdownMenuRadioItem value="15">15 V source</DropdownMenuRadioItem>
            </DropdownMenuRadioGroup>
          </DropdownMenuContent>
        </DropdownMenu>

        <DropdownMenu>
          <DropdownMenuTrigger asChild><MenuButton label="Legend" /></DropdownMenuTrigger>
          <DropdownMenuContent align="start">
            <DropdownMenuCheckboxItem checked={props.legendVisible} onCheckedChange={() => action("legend-visible")}>Show legend</DropdownMenuCheckboxItem>
            <DropdownMenuItem onSelect={() => action("legend-move")}><Move />Reposition legend</DropdownMenuItem>
            <DropdownMenuItem onSelect={() => action("legend-smaller")}><EyeOff />Smaller key</DropdownMenuItem>
            <DropdownMenuItem onSelect={() => action("legend-larger")}><Eye />Larger key</DropdownMenuItem>
            <DropdownMenuItem onSelect={() => action("recount")}><RotateCcw />Recount fixtures</DropdownMenuItem>
            <DropdownMenuCheckboxItem checked={props.halosVisible} onCheckedChange={() => action("halos-visible")}>Show light halos</DropdownMenuCheckboxItem>
          </DropdownMenuContent>
        </DropdownMenu>

        <DropdownMenu>
          <DropdownMenuTrigger asChild><MenuButton label="File" /></DropdownMenuTrigger>
          <DropdownMenuContent align="start" className="w-60">
            <DropdownMenuItem onSelect={() => action("import-project")}><Upload />Open editable project</DropdownMenuItem>
            <DropdownMenuItem onSelect={() => action("export-project")}><FileJson />Save editable project</DropdownMenuItem>
            <DropdownMenuItem onSelect={() => action("download-sheets")}><Download />Download all sheets</DropdownMenuItem>
            <DropdownMenuItem onSelect={() => action("print")}><Printer />Print active sheet</DropdownMenuItem>
            <DropdownMenuItem onSelect={() => action("fullscreen")}><Fullscreen />Full screen</DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>

        <ToolButton label="Present" icon={Presentation} action="present" onAction={action} />
        <ToolButton label="PDF" icon={Download} action="download-pdf" onAction={action} />
        <ToolButton label="Help" icon={HelpCircle} action="help" onAction={action} />
      </div>
    </section>
  );
}

function MinimizePlanIcon({ className }: { className?: string }) {
  return <Layers3 className={className} />;
}
