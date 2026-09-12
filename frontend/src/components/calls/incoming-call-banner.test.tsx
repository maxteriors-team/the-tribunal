import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { IncomingCallBanner } from "@/components/calls/incoming-call-banner";

const actions = {
  onAccept: vi.fn(),
  onDecline: vi.fn(),
};

describe("IncomingCallBanner", () => {
  beforeEach(() => vi.clearAllMocks());

  it("shows who is calling and offers both answers", async () => {
    render(<IncomingCallBanner {...actions} callerNumber="+15551234567" isConnecting={false} />);

    expect(screen.getByText("+1 (555) 123-4567")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /accept/i }));
    expect(actions.onAccept).toHaveBeenCalledOnce();
    expect(actions.onDecline).not.toHaveBeenCalled();
  });

  it("lets the operator decline without accepting", async () => {
    render(<IncomingCallBanner {...actions} callerNumber="+15551234567" isConnecting={false} />);

    await userEvent.click(screen.getByRole("button", { name: /decline/i }));
    expect(actions.onDecline).toHaveBeenCalledOnce();
    expect(actions.onAccept).not.toHaveBeenCalled();
  });

  it("announces the call to a screen reader", async () => {
    render(<IncomingCallBanner {...actions} callerNumber="+15551234567" isConnecting={false} />);

    expect(
      await screen.findByText(/incoming call from \+1 \(555\) 123-4567/i),
    ).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Incoming call" })).toBeInTheDocument();
  });

  it("keeps a way out while the microphone handshake is in flight", () => {
    render(<IncomingCallBanner {...actions} callerNumber="+15551234567" isConnecting />);

    // Accepting twice would answer a call that is already being answered, but a
    // stalled mic prompt must never trap the operator with no way to refuse.
    expect(screen.getByRole("button", { name: /accept/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /decline/i })).toBeEnabled();
  });

  it("still identifies the call when the number is withheld", () => {
    render(<IncomingCallBanner {...actions} callerNumber="" isConnecting={false} />);

    expect(screen.getByText("Unknown caller")).toBeInTheDocument();
  });
});
