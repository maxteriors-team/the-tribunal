import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SoftphoneBar } from "@/components/calls/softphone-bar";

const actions = {
  onAnswer: vi.fn(async () => undefined),
  onToggleMute: vi.fn(async () => undefined),
  onHangup: vi.fn(async () => undefined),
  onDismiss: vi.fn(),
};

describe("SoftphoneBar", () => {
  beforeEach(() => vi.clearAllMocks());

  it("asks the operator to answer before the customer is dialed", async () => {
    render(
      <SoftphoneBar
        {...actions}
        phase="ringing"
        contactName="Dana Reeves"
        isMuted={false}
        startedAt={null}
        error={null}
      />,
    );

    expect(screen.getByText("Dana Reeves")).toBeInTheDocument();
    expect(screen.getByText("Headset ready")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Answer" }));
    expect(actions.onAnswer).toHaveBeenCalledOnce();
  });

  it("exposes labelled mute and hangup controls during an active call", async () => {
    render(
      <SoftphoneBar
        {...actions}
        phase="active"
        contactName="Dana Reeves"
        isMuted={false}
        startedAt={Date.now()}
        error={null}
      />,
    );

    await userEvent.click(screen.getByRole("button", { name: "Mute microphone" }));
    await userEvent.click(screen.getByRole("button", { name: "End browser call" }));
    expect(actions.onToggleMute).toHaveBeenCalledOnce();
    expect(actions.onHangup).toHaveBeenCalledOnce();
  });

  it("announces a recoverable error and lets the operator dismiss it", async () => {
    render(
      <SoftphoneBar
        {...actions}
        phase="error"
        contactName="Dana Reeves"
        isMuted={false}
        startedAt={null}
        error="Microphone access failed."
      />,
    );

    expect(screen.getByRole("region", { name: "Browser call" })).toHaveTextContent(
      "Microphone access failed.",
    );
    await userEvent.click(screen.getByRole("button", { name: "Dismiss browser call" }));
    expect(actions.onDismiss).toHaveBeenCalledOnce();
  });
});
