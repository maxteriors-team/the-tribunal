import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Cable, Circle } from "lucide-react";
import { describe, expect, it, vi } from "vitest";

import { DrawingToolbar } from "./drawing-toolbar";

const MENU_WALK_TIMEOUT_MS = 30_000;

const renderToolbar = () => {
  const onAction = vi.fn();
  const onPaperSizeChange = vi.fn();
  const onMarkerColorChange = vi.fn();
  const onFixtureSelect = vi.fn();
  const onBistroSelect = vi.fn();
  render(
    <DrawingToolbar
      workspaceName="Northstar Outdoor Lighting"
      paperSize="tabloid"
      hasAerial
      hasDrawing
      hasPlanSymbols
      canUndo
      canWire
      canRender
      duskPreview={false}
      markerColor="#eb5757"
      planFit="contain"
      planOpacity={1}
      legendScale={1}
      sourceVoltage={13}
      fixtureNumbersVisible
      measurementsVisible
      legendVisible
      halosVisible
      onPaperSizeChange={onPaperSizeChange}
      onMarkerColorChange={onMarkerColorChange}
      onAction={onAction}
      fixtureTools={[
        {
          id: "uplight",
          label: "Uplight",
          icon: Circle,
          onSelect: onFixtureSelect,
        },
        {
          id: "bistro-temporary",
          label: "Temporary Bistro Lights",
          icon: Cable,
          group: "bistro",
          onSelect: onBistroSelect,
        },
      ]}
    />,
  );
  return {
    onAction,
    onBistroSelect,
    onFixtureSelect,
    onMarkerColorChange,
    onPaperSizeChange,
  };
};

const clickMenuItem = async (menu: string, item: string) => {
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: menu }));
  const candidate =
    screen.queryByRole("menuitem", { name: item }) ??
    screen.queryByRole("menuitemcheckbox", { name: item }) ??
    screen.queryByRole("menuitemradio", { name: item });
  expect(candidate).not.toBeNull();
  await user.click(candidate!);
};

describe("DrawingToolbar", () => {
  it("uses the active workspace brand with the drawing controls", () => {
    renderToolbar();

    expect(screen.getByText("Northstar Outdoor Lighting")).toBeInTheDocument();
    expect(screen.queryByText(/maxteriors/i)).not.toBeInTheDocument();
  });

  it("keeps the compact primary actions, physical sheet sizes, and sixteen named marker colors", () => {
    const { onAction, onMarkerColorChange, onPaperSizeChange } = renderToolbar();

    fireEvent.change(screen.getByRole("combobox", { name: /sheet/i }), {
      target: { value: "arch-d" },
    });
    expect(onPaperSizeChange).toHaveBeenCalledWith("arch-d");

    const markerRadios = screen.getAllByRole("radio");
    expect(markerRadios).toHaveLength(16);
    expect(screen.getByRole("radio", { name: "Red" })).toBeChecked();
    fireEvent.click(screen.getByRole("radio", { name: "Blue" }));
    expect(onMarkerColorChange).toHaveBeenCalledWith("#2f80ed");

    for (const [label, expected] of [
      ["Replace aerial", "place-aerial"],
      ["Select", "select"],
      ["Pan", "pan"],
      ["Undo", "undo"],
      ["Wiring: Off", "wire"],
      ["Highlight", "highlight"],
      ["Fixture #: On", "fixture-numbers"],
      ["Help", "help"],
      ["Download PDF", "download-pdf"],
    ] as const) {
      fireEvent.click(screen.getByRole("button", { name: label }));
      expect(onAction).toHaveBeenLastCalledWith(expected);
    }
  });

  it(
    "moves fixture placement into Add and exposes only retained drawing commands",
    async () => {
      const { onAction, onBistroSelect, onFixtureSelect } = renderToolbar();

      await clickMenuItem("Add", "Uplight");
      expect(onFixtureSelect).toHaveBeenCalledOnce();
      await clickMenuItem("Add", "Temporary Bistro Lights");
      expect(onBistroSelect).toHaveBeenCalledOnce();
      await clickMenuItem("Add", "Supplemental detail photo");
      expect(onAction).toHaveBeenLastCalledWith("add-photo");

      const planActions = [
        ["Set scale", "set-scale"],
        ["Show saved measurements", "measurements-visible"],
        ["Cover drawing area", "fit-cover"],
        ["50%", "opacity-50"],
        ["Clear fixtures, bistro runs, and wiring", "clear-design"],
        ["Clear plan annotations", "clear-symbols"],
      ] as const;
      for (const [label, expected] of planActions) {
        await clickMenuItem("Plan", label);
        expect(onAction).toHaveBeenLastCalledWith(expected);
      }
    },
    MENU_WALK_TIMEOUT_MS,
  );

  it("returns menu focus for keyboards without leaving a pointer focus ring", async () => {
    const user = userEvent.setup();
    renderToolbar();
    const add = screen.getByRole("button", { name: "Add" });

    await user.click(add);
    await user.click(screen.getByRole("menuitem", { name: "Temporary Bistro Lights" }));
    expect(add).not.toHaveFocus();

    add.focus();
    await user.keyboard("{Enter}");
    expect(screen.getByRole("menuitem", { name: "Temporary Bistro Lights" })).toBeVisible();
    await user.keyboard("{Escape}");
    expect(add).toHaveFocus();
  });

  it(
    "wires every contextual menu to a visible state change or document action",
    async () => {
      const { onAction } = renderToolbar();
      const actions = [
        ["Wiring", "Draw wire route", "wire"],
        ["Wiring", "Clear wire routes", "clear-wires"],
        ["Wiring", "15 V", "source-voltage-15"],
        ["Legend", "Show legend", "legend-visible"],
        ["Legend", "Move right", "legend-right"],
        ["Legend", "Larger", "legend-larger"],
        ["Legend", "Recount fixtures", "recount"],
        ["Legend", "Show light halos", "halos-visible"],
        ["File", "Open editable project", "import-project"],
        ["File", "Save editable project", "export-project"],
        ["File", "Full screen", "fullscreen"],
        ["Present", "Show dusk plan", "toggle-preview"],
        ["Present", "Open proposal preview", "present"],
        ["Present", "Create dusk render", "render"],
      ] as const;

      for (const [menu, item, expected] of actions) {
        await clickMenuItem(menu, item);
        expect(onAction).toHaveBeenLastCalledWith(expected);
      }
    },
    MENU_WALK_TIMEOUT_MS,
  );
});
