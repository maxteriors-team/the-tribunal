import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { DrawingToolbar } from "./drawing-toolbar";

const renderToolbar = () => {
  const onAction = vi.fn();
  const onPaperSizeChange = vi.fn();
  render(
    <DrawingToolbar
      paperSize="tabloid"
      canUndo
      canRedo={false}
      fixtureNumbersVisible
      measurementsVisible
      legendVisible
      halosVisible
      onPaperSizeChange={onPaperSizeChange}
      onAction={onAction}
    />,
  );
  return { onAction, onPaperSizeChange };
};

const clickMenuItem = async (menu: string, item: string) => {
  const user = userEvent.setup();
  const triggers = screen.getAllByRole("button", { name: menu });
  await user.click(triggers.find((trigger) => trigger.hasAttribute("aria-haspopup")) ?? triggers.at(-1)!);
  await user.click(
    await screen.findByRole(item === "Show measurements" || item === "Show legend" || item === "Show light halos" ? "menuitemcheckbox" : item.endsWith("V source") ? "menuitemradio" : "menuitem", { name: item }),
  );
};

describe("DrawingToolbar", () => {
  it("exercises every always-visible action and paper size", () => {
    const { onAction, onPaperSizeChange } = renderToolbar();
    fireEvent.change(screen.getByLabelText(/paper/i), { target: { value: "arch-d" } });
    expect(onPaperSizeChange).toHaveBeenCalledWith("arch-d");
    for (const label of ["Select", "Undo", "Wiring", "Highlight", "Numbers"]) {
      fireEvent.click(screen.getAllByRole("button", { name: label })[0]);
    }
    expect(onAction.mock.calls.flat()).toEqual([
      "select",
      "undo",
      "wire",
      "highlight",
      "fixture-numbers",
    ]);
    expect(screen.getByRole("button", { name: "Redo" })).toBeDisabled();
  });

  it("exercises every plan menu action", async () => {
    const { onAction } = renderToolbar();
    const actions = [
      ["Set scale", "set-scale"],
      ["Measure distance", "measure"],
      ["Show measurements", "measurements-visible"],
      ["Contain plan", "fit-contain"],
      ["Cover plan", "fit-cover"],
      ["Plan opacity", "plan-fade"],
      ["Preview automatic design", "automatic-design"],
      ["Clear fixture design", "clear-design"],
      ["Clear plan symbols", "clear-symbols"],
      ["Clear plan", "clear-plan"],
    ] as const;
    for (const [label, expected] of actions) {
      await clickMenuItem("Plan", label);
      expect(onAction).toHaveBeenLastCalledWith(expected);
    }
  });

  it("exercises every add, wiring, legend, file, and help action", async () => {
    const { onAction } = renderToolbar();
    const groups: Array<[string, Array<[string, string]>]> = [
      ["Add", [["Note", "add-note"], ["Line", "add-line"], ["Tree symbol", "add-tree"], ["Photo inset", "add-photo"], ["Revision row", "add-revision"]]],
      ["Wiring", [["Draw named run", "draw-wire"], ["End run", "end-run"], ["Undo wire point", "undo-point"], ["Clear wire runs", "clear-wires"], ["Draw arrow", "draw-arrow"], ["Clear arrows", "clear-arrows"], ["Assign transformer zone", "assign-zone"], ["12 V source", "source-voltage"]]],
      ["Legend", [["Show legend", "legend-visible"], ["Reposition legend", "legend-move"], ["Smaller key", "legend-smaller"], ["Larger key", "legend-larger"], ["Recount fixtures", "recount"], ["Show light halos", "halos-visible"]]],
      ["File", [["Open editable project", "import-project"], ["Save editable project", "export-project"], ["Download all sheets", "download-sheets"], ["Print active sheet", "print"], ["Full screen", "fullscreen"]]],
    ];
    for (const [menu, items] of groups) {
      for (const [item, expected] of items) {
        await clickMenuItem(menu, item);
        expect(onAction).toHaveBeenLastCalledWith(expected);
      }
    }
    for (const [label, expected] of [["Present", "present"], ["PDF", "download-pdf"], ["Help", "help"]] as const) {
      fireEvent.click(screen.getByRole("button", { name: label }));
      expect(onAction).toHaveBeenLastCalledWith(expected);
    }
    expect(onAction).toHaveBeenCalledTimes(groups.reduce((total, [, items]) => total + items.length, 0) + 3);
  });
});
