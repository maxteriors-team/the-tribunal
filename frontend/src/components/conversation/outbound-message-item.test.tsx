import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { TimelineItem } from "@/types";

import { OutboundMessageItem } from "./outbound-message-item";

function item(overrides: Partial<TimelineItem> = {}): TimelineItem {
  return {
    id: "message-1",
    type: "sms",
    timestamp: "2026-08-12T12:00:00Z",
    direction: "outbound",
    is_ai: true,
    agent_id: "agent-1",
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
