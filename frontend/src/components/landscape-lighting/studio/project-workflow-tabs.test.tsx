import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ProjectWorkflowTabs } from "./project-workflow-tabs";

describe("ProjectWorkflowTabs", () => {
  it("renders the six plain text workflow steps and supports arrow, Home, and End keys", () => {
    const onChange = vi.fn();
    const { container } = render(<ProjectWorkflowTabs value="drawing" onChange={onChange} />);
    const tabs = screen.getAllByRole("tab");

    expect(tabs.map((tab) => tab.textContent)).toEqual([
      "Drawing Sheet",
      "Fixture Schedule",
      "BOM",
      "Electrical",
      "Proposal",
      "Pre-Con",
    ]);
    expect(container.querySelector("svg")).toBeNull();
    expect(tabs[0]).toHaveAttribute("aria-selected", "true");
    expect(tabs[0]).toHaveAttribute("tabindex", "0");
    expect(tabs.slice(1).every((tab) => tab.getAttribute("tabindex") === "-1")).toBe(true);

    tabs[0].focus();
    fireEvent.keyDown(tabs[0], { key: "ArrowRight" });
    expect(onChange).toHaveBeenLastCalledWith("schedule");
    expect(tabs[1]).toHaveFocus();

    fireEvent.keyDown(tabs[1], { key: "End" });
    expect(onChange).toHaveBeenLastCalledWith("precon");
    expect(tabs[5]).toHaveFocus();

    fireEvent.keyDown(tabs[5], { key: "Home" });
    expect(onChange).toHaveBeenLastCalledWith("drawing");
    expect(tabs[0]).toHaveFocus();
  });
});
