import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AssistantLauncher } from "@/components/assistant/assistant-launcher";

const { useWorkspaceMock } = vi.hoisted(() => ({ useWorkspaceMock: vi.fn() }));

vi.mock("@/providers/workspace-provider", () => ({
  useWorkspace: useWorkspaceMock,
}));

// The chat itself is covered by assistant-chat.test.tsx. Stubbed here so these
// tests are about the widget: when it opens, what minimising preserves, and what
// closing tears down. The input models a half-typed question.
vi.mock("@/components/assistant/assistant-chat", () => ({
  AssistantChat: () => <input data-testid="assistant-chat" aria-label="draft" />,
}));

const bubble = () => screen.getByRole("button", { name: /ask the crm assistant/i });
const widget = () => screen.queryByTestId("assistant-widget");

beforeEach(() => {
  vi.clearAllMocks();
  useWorkspaceMock.mockReturnValue({ currentWorkspace: { id: "ws-1", name: "Maxteriors" } });
});

describe("AssistantLauncher", () => {
  it("shows only a bubble until asked, so no page boots the chat runtime", () => {
    render(<AssistantLauncher />);

    expect(bubble()).toBeInTheDocument();
    expect(widget()).not.toBeInTheDocument();
  });

  it("opens the chat widget over the page when the bubble is pressed", async () => {
    const user = userEvent.setup();
    render(<AssistantLauncher />);

    await user.click(bubble());

    expect(widget()).toBeVisible();
    expect(screen.getByText("CRM Assistant")).toBeInTheDocument();
  });

  it("expands and shrinks", async () => {
    const user = userEvent.setup();
    render(<AssistantLauncher />);
    await user.click(bubble());

    await user.click(screen.getByRole("button", { name: /expand assistant/i }));
    expect(widget()).toHaveClass("w-[52rem]");

    await user.click(screen.getByRole("button", { name: /shrink assistant/i }));
    expect(widget()).toHaveClass("w-[26rem]");
  });

  it("keeps a half-typed question when minimised and reopened", async () => {
    const user = userEvent.setup();
    render(<AssistantLauncher />);
    await user.click(bubble());
    await user.type(screen.getByLabelText("draft"), "how many quotes are open");

    await user.click(screen.getByRole("button", { name: /minimize assistant/i }));
    // Minimised means hidden, never discarded — that is the whole difference
    // between minimise and close.
    expect(widget()).not.toBeVisible();

    await user.click(bubble());

    expect(screen.getByLabelText("draft")).toHaveValue("how many quotes are open");
  });

  it("tears the chat down on close, so nothing keeps polling", async () => {
    const user = userEvent.setup();
    render(<AssistantLauncher />);
    await user.click(bubble());

    await user.click(screen.getByRole("button", { name: /close assistant/i }));

    await waitFor(() => expect(widget()).not.toBeInTheDocument());
    expect(bubble()).toBeInTheDocument();
  });

  it("starts a closed widget back at normal size", async () => {
    const user = userEvent.setup();
    render(<AssistantLauncher />);
    await user.click(bubble());
    await user.click(screen.getByRole("button", { name: /expand assistant/i }));

    await user.click(screen.getByRole("button", { name: /close assistant/i }));
    await user.click(bubble());

    expect(widget()).toHaveClass("w-[26rem]");
  });

  it("minimises on Escape rather than discarding the draft", async () => {
    const user = userEvent.setup();
    render(<AssistantLauncher />);
    await user.click(bubble());
    await user.type(screen.getByLabelText("draft"), "draft text");

    await user.keyboard("{Escape}");

    expect(widget()).not.toBeVisible();
    await user.click(bubble());
    expect(screen.getByLabelText("draft")).toHaveValue("draft text");
  });

  it("toggles on the keyboard shortcut", async () => {
    const user = userEvent.setup();
    render(<AssistantLauncher />);

    await user.keyboard("{Meta>}/{/Meta}");
    expect(widget()).toBeVisible();

    await user.keyboard("{Meta>}/{/Meta}");
    expect(widget()).not.toBeVisible();
  });

  it("shows nothing before a workspace is chosen", () => {
    // The assistant acts inside a workspace; without one the bubble would open a
    // widget that cannot answer anything.
    useWorkspaceMock.mockReturnValue({ currentWorkspace: null });

    render(<AssistantLauncher />);

    expect(screen.queryByRole("button", { name: /ask the crm assistant/i })).not.toBeInTheDocument();
  });
});
