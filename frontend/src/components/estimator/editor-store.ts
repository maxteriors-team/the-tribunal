/**
 * Editor state + history for the light designer.
 *
 * A trimmed port of the in-house light-estimator store: it owns only the
 * *design* slice (calibration, runs, items) plus the interaction state the
 * canvas needs (tool, selection, dusk) and a bounded undo/redo history.
 * Products, pricing, and customer/share state live in the host component
 * (`roofline-estimator.tsx`), which drives the server-authoritative estimate —
 * this reducer never touches money.
 *
 * The host runs it with `useReducer(editorReducer, undefined, initialEditorState)`
 * and passes `state`/`dispatch` to the canvas, palette, and estimate panel.
 */
import { DEFAULT_DUSK, MAX_DUSK } from "@/lib/estimator/render";
import type {
  Calibration,
  Design,
  PlacedItem,
  PlanImage,
  Run,
  LandscapeAnnotation,
  LandscapeMeasurementLine,
  LandscapeHighlightStroke,
  LandscapeArrow,
  Selection,
  Tool,
} from "@/lib/estimator/types";

export const EMPTY_DESIGN: Design = {
  calibration: null,
  runs: [],
  items: [],
  planImages: [],
  annotations: [],
  measurements: [],
  highlights: [],
  arrows: [],
};

const HISTORY_LIMIT = 60;

export interface EditorState {
  design: Design;
  tool: Tool;
  selection: Selection;
  /**
   * How far past sunset the photo reads, 0 (daylight) to `MAX_DUSK`. Continuous
   * rather than a night on/off switch: the rep drags the sun down in front of
   * the customer, which is the moment the design sells itself.
   */
  dusk: number;
  past: Design[];
  future: Design[];
}

export type EditorAction =
  | { type: "SET_TOOL"; tool: Tool }
  | { type: "SET_SELECTION"; selection: Selection }
  | { type: "SET_DUSK"; dusk: number }
  | { type: "ADD_RUN"; run: Run }
  | {
      type: "UPDATE_RUN";
      id: string;
      patch: Partial<
        Pick<
          Run,
          | "points"
          | "productId"
          | "spacingIn"
          | "colors"
          | "bulbScale"
          | "permanentComplexity"
          | "circuitLabel"
          | "transformerId"
          | "wireGauge"
          | "sourceVoltage"
        >
      >;
      transient?: boolean;
    }
  | { type: "DELETE_RUN"; id: string }
  | { type: "APPLY_COLORS_ALL"; colors: string[] }
  | { type: "ADD_ITEM"; item: PlacedItem }
  | {
      type: "UPDATE_ITEM";
      id: string;
      patch: Partial<
        Pick<
          PlacedItem,
          | "at"
          | "sizePx"
          | "iconScale"
          | "productId"
          | "beamAngleDeg"
          | "beamRotationDeg"
          | "circuitId"
          | "markerColor"
          | "catalogItemId"
          | "catalogSku"
          | "lampCatalogItemId"
          | "accessoryCatalogItemIds"
        >
      >;
      transient?: boolean;
    }
  | { type: "DELETE_ITEM"; id: string }
  | { type: "ADD_PLAN_IMAGE"; image: PlanImage }
  | {
      type: "UPDATE_PLAN_IMAGE";
      id: string;
      patch: Partial<Pick<PlanImage, "at" | "widthPx" | "heightPx" | "name">>;
      transient?: boolean;
    }
  | { type: "DELETE_PLAN_IMAGE"; id: string }
  | { type: "ADD_ANNOTATION"; annotation: LandscapeAnnotation }
  | { type: "DELETE_ANNOTATION"; id: string }
  | { type: "ADD_MEASUREMENT"; measurement: LandscapeMeasurementLine }
  | { type: "DELETE_MEASUREMENT"; id: string }
  | { type: "ADD_HIGHLIGHT"; highlight: LandscapeHighlightStroke }
  | { type: "DELETE_HIGHLIGHT"; id: string }
  | { type: "ADD_ARROW"; arrow: LandscapeArrow }
  | { type: "DELETE_ARROW"; id: string }
  | { type: "CLEAR_SYMBOLS" }
  | { type: "SET_CALIBRATION"; calibration: Calibration | null; transient?: boolean }
  | { type: "CLEAR_DESIGN" }
  | { type: "RESET"; design?: Design }
  /**
   * Roll back an in-progress transient drag without touching history — used
   * when a gesture supersedes a drag (a second finger lands mid-drag on a
   * tablet), so the abandoned move leaves nothing behind and costs no undo.
   */
  | { type: "REVERT_TRANSIENT"; design: Design }
  | { type: "COMMIT_HISTORY"; before: Design }
  | { type: "UNDO" }
  | { type: "REDO" };

export function initialEditorState(): EditorState {
  return {
    design: EMPTY_DESIGN,
    tool: { type: "select" },
    selection: null,
    dusk: DEFAULT_DUSK,
    past: [],
    future: [],
  };
}

function pushHistory(state: EditorState, before: Design): Pick<EditorState, "past" | "future"> {
  const past = [...state.past, before];
  if (past.length > HISTORY_LIMIT) past.shift();
  return { past, future: [] };
}

/** Set the design; non-transient changes push the previous design onto history. */
function withDesign(state: EditorState, design: Design, transient?: boolean): EditorState {
  if (transient) return { ...state, design };
  return { ...state, design, ...pushHistory(state, state.design) };
}

export function editorReducer(state: EditorState, action: EditorAction): EditorState {
  switch (action.type) {
    case "SET_TOOL":
      return { ...state, tool: action.tool, selection: null };
    case "SET_SELECTION":
      return { ...state, selection: action.selection };
    case "SET_DUSK":
      return { ...state, dusk: Math.min(Math.max(action.dusk, 0), MAX_DUSK) };

    case "ADD_RUN":
      return {
        ...withDesign(state, {
          ...state.design,
          runs: [...state.design.runs, action.run],
        }),
        selection: { kind: "run", id: action.run.id },
      };
    case "UPDATE_RUN":
      return withDesign(
        state,
        {
          ...state.design,
          runs: state.design.runs.map((r) => (r.id === action.id ? { ...r, ...action.patch } : r)),
        },
        action.transient,
      );
    case "DELETE_RUN":
      return {
        ...withDesign(state, {
          ...state.design,
          runs: state.design.runs.filter((r) => r.id !== action.id),
          items: state.design.items.map((item) =>
            item.circuitId === action.id ? { ...item, circuitId: undefined } : item,
          ),
        }),
        selection: null,
      };

    case "ADD_ITEM":
      return {
        ...withDesign(state, {
          ...state.design,
          items: [...state.design.items, action.item],
        }),
        selection: { kind: "item", id: action.item.id },
      };
    case "UPDATE_ITEM":
      return withDesign(
        state,
        {
          ...state.design,
          items: state.design.items.map((i) =>
            i.id === action.id ? { ...i, ...action.patch } : i,
          ),
        },
        action.transient,
      );
    case "DELETE_ITEM":
      return {
        ...withDesign(state, {
          ...state.design,
          items: state.design.items.filter((i) => i.id !== action.id),
          runs: state.design.runs.map((run) =>
            run.transformerId === action.id ? { ...run, transformerId: undefined } : run,
          ),
        }),
        selection: null,
      };

    case "ADD_PLAN_IMAGE":
      return {
        ...withDesign(state, {
          ...state.design,
          planImages: [...(state.design.planImages ?? []), action.image],
        }),
        tool: { type: "select" },
        selection: { kind: "planImage", id: action.image.id },
      };
    case "UPDATE_PLAN_IMAGE":
      return withDesign(
        state,
        {
          ...state.design,
          planImages: (state.design.planImages ?? []).map((image) =>
            image.id === action.id ? { ...image, ...action.patch } : image,
          ),
        },
        action.transient,
      );
    case "DELETE_PLAN_IMAGE":
      return {
        ...withDesign(state, {
          ...state.design,
          planImages: (state.design.planImages ?? []).filter((image) => image.id !== action.id),
        }),
        selection: null,
      };
    case "ADD_ANNOTATION":
      return withDesign(state, {
        ...state.design,
        annotations: [...(state.design.annotations ?? []), action.annotation],
      });
    case "DELETE_ANNOTATION":
      return withDesign(state, {
        ...state.design,
        annotations: (state.design.annotations ?? []).filter((entry) => entry.id !== action.id),
      });
    case "ADD_MEASUREMENT":
      return withDesign(state, {
        ...state.design,
        measurements: [...(state.design.measurements ?? []), action.measurement],
      });
    case "DELETE_MEASUREMENT":
      return withDesign(state, {
        ...state.design,
        measurements: (state.design.measurements ?? []).filter((entry) => entry.id !== action.id),
      });
    case "ADD_HIGHLIGHT":
      return withDesign(state, {
        ...state.design,
        highlights: [...(state.design.highlights ?? []), action.highlight],
      });
    case "DELETE_HIGHLIGHT":
      return withDesign(state, {
        ...state.design,
        highlights: (state.design.highlights ?? []).filter((entry) => entry.id !== action.id),
      });
    case "ADD_ARROW":
      return withDesign(state, {
        ...state.design,
        arrows: [...(state.design.arrows ?? []), action.arrow],
      });
    case "DELETE_ARROW":
      return withDesign(state, {
        ...state.design,
        arrows: (state.design.arrows ?? []).filter((entry) => entry.id !== action.id),
      });
    case "CLEAR_SYMBOLS":
      return withDesign(state, {
        ...state.design,
        annotations: [],
        measurements: [],
        highlights: [],
        arrows: [],
      });

    case "APPLY_COLORS_ALL": {
      if (state.design.runs.length === 0) return state;
      return withDesign(state, {
        ...state.design,
        runs: state.design.runs.map((r) => ({ ...r, colors: action.colors })),
      });
    }

    case "SET_CALIBRATION":
      return withDesign(
        state,
        { ...state.design, calibration: action.calibration },
        action.transient,
      );

    case "CLEAR_DESIGN":
      // Clears priced lighting geometry but keeps plan references and scale.
      return {
        ...withDesign(state, {
          calibration: state.design.calibration,
          runs: [],
          items: [],
          planImages: state.design.planImages ?? [],
          annotations: state.design.annotations ?? [],
          measurements: state.design.measurements ?? [],
          highlights: state.design.highlights ?? [],
          arrows: state.design.arrows ?? [],
        }),
        selection: null,
      };

    case "RESET":
      // Switching photos → drop the history and load that shot's drawing (empty
      // for a photo just added). Undo is per-photo on purpose: undoing into
      // another photo's strokes would edit something that isn't on screen.
      return {
        ...initialEditorState(),
        dusk: state.dusk,
        design: action.design ?? EMPTY_DESIGN,
      };

    case "REVERT_TRANSIENT":
      return { ...state, design: action.design };

    case "COMMIT_HISTORY": {
      if (JSON.stringify(action.before) === JSON.stringify(state.design)) {
        return state;
      }
      return { ...state, ...pushHistory(state, action.before) };
    }

    case "UNDO": {
      const prev = state.past[state.past.length - 1];
      if (!prev) return state;
      return {
        ...state,
        design: prev,
        past: state.past.slice(0, -1),
        future: [state.design, ...state.future],
        selection: null,
      };
    }
    case "REDO": {
      const next = state.future[0];
      if (!next) return state;
      return {
        ...state,
        design: next,
        past: [...state.past, state.design],
        future: state.future.slice(1),
        selection: null,
      };
    }

    default:
      return state;
  }
}

let idCounter = 0;
/** Monotonic id for runs/items; stable within a session. */
export function nextId(prefix: string): string {
  idCounter += 1;
  return `${prefix}-${Date.now().toString(36)}-${idCounter}`;
}
