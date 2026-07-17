/**
 * Editor state + history for the light designer.
 *
 * A trimmed port of the in-house light-estimator store: it owns only the
 * *design* slice (calibration, runs, items) plus the interaction state the
 * canvas needs (tool, selection, night mode) and a bounded undo/redo history.
 * Products, pricing, and customer/share state live in the host component
 * (`roofline-estimator.tsx`), which drives the server-authoritative estimate —
 * this reducer never touches money.
 *
 * The host runs it with `useReducer(editorReducer, undefined, initialEditorState)`
 * and passes `state`/`dispatch` to the canvas, palette, and estimate panel.
 */
import type {
  Calibration,
  Design,
  PlacedItem,
  Run,
  Selection,
  Tool,
} from "@/lib/estimator/types";

export const EMPTY_DESIGN: Design = { calibration: null, runs: [], items: [] };

const HISTORY_LIMIT = 60;

export interface EditorState {
  design: Design;
  tool: Tool;
  selection: Selection;
  nightMode: boolean;
  past: Design[];
  future: Design[];
}

export type EditorAction =
  | { type: "SET_TOOL"; tool: Tool }
  | { type: "SET_SELECTION"; selection: Selection }
  | { type: "SET_NIGHT"; on: boolean }
  | { type: "ADD_RUN"; run: Run }
  | {
      type: "UPDATE_RUN";
      id: string;
      patch: Partial<
        Pick<Run, "points" | "productId" | "spacingIn" | "colors" | "bulbScale">
      >;
      transient?: boolean;
    }
  | { type: "DELETE_RUN"; id: string }
  | { type: "APPLY_COLORS_ALL"; colors: string[] }
  | { type: "ADD_ITEM"; item: PlacedItem }
  | {
      type: "UPDATE_ITEM";
      id: string;
      patch: Partial<Pick<PlacedItem, "at" | "sizePx" | "productId">>;
      transient?: boolean;
    }
  | { type: "DELETE_ITEM"; id: string }
  | { type: "SET_CALIBRATION"; calibration: Calibration | null; transient?: boolean }
  | { type: "CLEAR_DESIGN" }
  | { type: "RESET"; design?: Design }
  | { type: "COMMIT_HISTORY"; before: Design }
  | { type: "UNDO" }
  | { type: "REDO" };

export function initialEditorState(): EditorState {
  return {
    design: EMPTY_DESIGN,
    tool: { type: "select" },
    selection: null,
    nightMode: true,
    past: [],
    future: [],
  };
}

function pushHistory(
  state: EditorState,
  before: Design,
): Pick<EditorState, "past" | "future"> {
  const past = [...state.past, before];
  if (past.length > HISTORY_LIMIT) past.shift();
  return { past, future: [] };
}

/** Set the design; non-transient changes push the previous design onto history. */
function withDesign(
  state: EditorState,
  design: Design,
  transient?: boolean,
): EditorState {
  if (transient) return { ...state, design };
  return { ...state, design, ...pushHistory(state, state.design) };
}

export function editorReducer(
  state: EditorState,
  action: EditorAction,
): EditorState {
  switch (action.type) {
    case "SET_TOOL":
      return { ...state, tool: action.tool, selection: null };
    case "SET_SELECTION":
      return { ...state, selection: action.selection };
    case "SET_NIGHT":
      return { ...state, nightMode: action.on };

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
          runs: state.design.runs.map((r) =>
            r.id === action.id ? { ...r, ...action.patch } : r,
          ),
        },
        action.transient,
      );
    case "DELETE_RUN":
      return {
        ...withDesign(state, {
          ...state.design,
          runs: state.design.runs.filter((r) => r.id !== action.id),
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
        }),
        selection: null,
      };

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
      // Clears runs + items but keeps the photo scale (calibration).
      return {
        ...withDesign(state, {
          calibration: state.design.calibration,
          runs: [],
          items: [],
        }),
        selection: null,
      };

    case "RESET":
      // New photo → drop the whole design and history.
      return {
        ...initialEditorState(),
        nightMode: state.nightMode,
        design: action.design ?? EMPTY_DESIGN,
      };

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
