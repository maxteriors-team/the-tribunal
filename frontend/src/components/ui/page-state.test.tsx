import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Sparkles } from "lucide-react";
import { describe, expect, it, vi } from "vitest";

import { Button } from "@/components/ui/button";
import {
  PageEmptyState,
  PageErrorState,
  PageLoadingState,
} from "@/components/ui/page-state";

describe("PageLoadingState", () => {
  it("renders an optional message", () => {
    render(<PageLoadingState message="Loading contacts…" />);
    expect(screen.getByText("Loading contacts…")).toBeInTheDocument();
  });

  it("omits the message paragraph when none is given", () => {
    const { container } = render(<PageLoadingState />);
    expect(container.querySelector("p")).toBeNull();
  });

  it("forwards className onto the page-state wrapper", () => {
    const { container } = render(<PageLoadingState className="h-96" />);
    const wrapper = container.querySelector('[data-slot="page-state"]');
    expect(wrapper).toHaveClass("h-96");
  });
});

describe("PageErrorState", () => {
  it("shows a default message and no retry button without onRetry", () => {
    render(<PageErrorState />);
    expect(screen.getByText("Something went wrong.")).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("renders a custom title and message", () => {
    render(<PageErrorState title="Access denied" message="Failed to load calls" />);
    expect(screen.getByRole("heading", { name: "Access denied" })).toBeInTheDocument();
    expect(screen.getByText("Failed to load calls")).toBeInTheDocument();
  });

  it("invokes onRetry when the retry button is clicked", async () => {
    const onRetry = vi.fn();
    const user = userEvent.setup();

    render(<PageErrorState onRetry={onRetry} retryLabel="Retry" />);

    await user.click(screen.getByRole("button", { name: "Retry" }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });
});

describe("PageEmptyState", () => {
  it("renders the title, description, custom icon, and action", () => {
    render(
      <PageEmptyState
        title="No contacts yet"
        description="Import a CSV to get started."
        icon={<Sparkles data-testid="empty-icon" className="size-8" />}
        action={<Button>Add contact</Button>}
      />,
    );

    expect(screen.getByText("No contacts yet")).toBeInTheDocument();
    expect(screen.getByText("Import a CSV to get started.")).toBeInTheDocument();
    expect(screen.getByTestId("empty-icon")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Add contact" }),
    ).toBeInTheDocument();
  });

  it("renders only the title when description and action are omitted", () => {
    render(<PageEmptyState title="No results" />);
    expect(screen.getByText("No results")).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});
