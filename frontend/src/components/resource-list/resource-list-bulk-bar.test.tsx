import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ResourceListBulkBar } from "./resource-list-bulk-bar";

describe("ResourceListBulkBar", () => {
  const baseProps = {
    resourceName: "contact",
    allVisibleSelected: false,
    someVisibleSelected: false,
    onToggleAllVisible: vi.fn(),
    onClearSelection: vi.fn(),
  };

  it("prompts to select when nothing is selected and hides bulk actions", () => {
    render(
      <ResourceListBulkBar {...baseProps} selectedCount={0}>
        <button type="button">Delete</button>
      </ResourceListBulkBar>,
    );

    expect(screen.getByText("Select contacts")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Clear" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Delete" })).not.toBeInTheDocument();
  });

  it("shows the count, clear button and bulk actions when rows are selected", () => {
    render(
      <ResourceListBulkBar {...baseProps} selectedCount={3}>
        <button type="button">Delete</button>
      </ResourceListBulkBar>,
    );

    expect(screen.getByText("3 selected")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Clear" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Delete" })).toBeInTheDocument();
  });

  it("invokes clear and toggle-all callbacks", async () => {
    const onClearSelection = vi.fn();
    const onToggleAllVisible = vi.fn();
    const user = userEvent.setup();

    render(
      <ResourceListBulkBar
        {...baseProps}
        selectedCount={2}
        onClearSelection={onClearSelection}
        onToggleAllVisible={onToggleAllVisible}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Clear" }));
    expect(onClearSelection).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole("checkbox"));
    expect(onToggleAllVisible).toHaveBeenCalledTimes(1);
  });

  it("reflects the indeterminate header state", () => {
    render(
      <ResourceListBulkBar
        {...baseProps}
        selectedCount={1}
        someVisibleSelected
      />,
    );

    expect(screen.getByRole("checkbox")).toHaveAttribute("data-state", "indeterminate");
  });

  it("renders a banner slot beneath the bar", () => {
    render(
      <ResourceListBulkBar
        {...baseProps}
        selectedCount={5}
        allVisibleSelected
        banner={<div>Select all 200 matching</div>}
      />,
    );

    expect(screen.getByText("Select all 200 matching")).toBeInTheDocument();
    expect(screen.getByRole("checkbox")).toHaveAttribute("data-state", "checked");
  });
});
