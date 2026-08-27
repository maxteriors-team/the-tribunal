import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { TimelineItem } from "@/types";

import { OutboundMessageItem } from "./outbound-message-item";

type SenderAttributedTimelineItem = Omit<TimelineItem, "sender_display_name"> & {
  sender_display_name: string | null;
};

function item(
  overrides: Partial<SenderAttributedTimelineItem> = {},
): SenderAttributedTimelineItem {
  return {
    id: "message-1",
    type: "sms",
    timestamp: "2026-08-12T12:00:00Z",
    direction: "outbound",
    is_ai: true,
    agent_id: "agent-1",
    sender_display_name: null,
    content: "AI reply",
    original_id: "message-1",
    original_type: "sms_message",
    ...overrides,
  };
}

describe("OutboundMessageItem Teach AI action", () => {
  it("shows a keyboard button for agent-assigned AI SMS replies", () => {
    const onTeachAI = vi.fn();
    const message = item();
    render(<OutboundMessageItem item={message} onTeachAI={onTeachAI} />);

    fireEvent.click(screen.getByRole("button", { name: "Teach AI from this reply" }));
    expect(onTeachAI).toHaveBeenCalledWith(message);
  });

  it("disables teaching when the source reply has no assigned agent", () => {
    render(<OutboundMessageItem item={item({ agent_id: null })} />);

    expect(screen.getByRole("button", { name: "Teach AI from this reply" })).toBeDisabled();
  });

  it("does not show Teach AI on human messages", () => {
    render(<OutboundMessageItem item={item({ is_ai: false })} />);

    expect(screen.queryByRole("button", { name: "Teach AI from this reply" })).toBeNull();
  });
});

const SENDER_CASES = [
  ["human", false, "Jordan Rivera", "J"],
  ["AI", true, "AI Agent", "A"],
  ["automation", false, "Automation", "A"],
  ["historical", false, "Unknown sender (historical)", "U"],
] as const;

describe("OutboundMessageItem sender attribution", () => {
  it.each(SENDER_CASES)(
    "displays the exact %s sender name on the outbound bubble",
    (_kind, isAI, senderName) => {
      render(
        <OutboundMessageItem
          item={item({
            is_ai: isAI,
            sender_display_name: _kind === "historical" ? null : senderName,
          })}
        />,
      );

      expect(screen.getByText(senderName)).toBeInTheDocument();
    },
  );

  it.each(SENDER_CASES)(
    "derives the %s sender avatar initial and accessible name",
    (_kind, isAI, senderName, initial) => {
      const { container } = render(
        <OutboundMessageItem
          item={item({
            is_ai: isAI,
            sender_display_name: _kind === "historical" ? null : senderName,
          })}
        />,
      );

      const avatar = container.querySelector('[data-slot="avatar"]');
      expect(avatar).toHaveTextContent(new RegExp(`^${initial}$`));
      expect(avatar).toHaveAccessibleName(senderName);
    },
  );

  it("uses the honest historical fallback instead of claiming the viewer sent the message", () => {
    render(<OutboundMessageItem item={item({ is_ai: false, sender_display_name: null })} />);

    expect(screen.getByText("Unknown sender (historical)")).toBeInTheDocument();
    expect(screen.queryByText(/^You$/)).not.toBeInTheDocument();
  });
});