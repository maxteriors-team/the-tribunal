import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AssistantDock } from "./assistant-dock";

vi.mock("@/components/assistant/assistant-chat", () => ({
  AssistantChat: ({ compact }: { compact?: boolean }) => (
    <div data-testid="assistant-chat">{compact ? "compact" : "full"}</div>
  ),
}));

// `hidden: true` keeps the collapsed (aria-hidden) window queryable; an
// aria-hidden element has no accessible name, so match on role alone.
const panel = () => screen.getByRole("dialog", { hidden: true });

describe("AssistantDock", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("opens the chat window, keeps it mounted while closed, and follows a remount", async () => {
    const user = userEvent.setup();
    const { unmount } = render(<AssistantDock />);

    expect(screen.queryByTestId("assistant-chat")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Open CRM Assistant" }));

    expect(panel()).not.toHaveAttribute("aria-hidden", "true");
    // Dock mode drops the chat-list rail so the chat fits a narrow window.
    expect(screen.getByTestId("assistant-chat")).toHaveTextContent("compact");

    await user.click(screen.getByRole("button", { name: "Close CRM Assistant" }));

    // Hidden, not unmounted: an in-flight assistant run must survive a collapse.
    expect(panel()).toHaveAttribute("aria-hidden", "true");
    expect(panel()).toHaveClass("hidden");
    expect(screen.getByTestId("assistant-chat")).toBeInTheDocument();

    // The app shell remounts on every client navigation; an open window follows.
    await user.click(screen.getByRole("button", { name: "Open CRM Assistant" }));
    unmount();
    render(<AssistantDock />);

    expect(panel()).not.toHaveAttribute("aria-hidden", "true");
    expect(
      screen.queryByRole("button", { name: "Open CRM Assistant", hidden: true }),
    ).not.toBeInTheDocument();
  });

  it("closes on Escape from inside the window", async () => {
    const user = userEvent.setup();
    render(<AssistantDock />);

    await user.click(screen.getByRole("button", { name: "Open CRM Assistant" }));
    await user.keyboard("{Escape}");

    expect(panel()).toHaveAttribute("aria-hidden", "true");
  });
});
