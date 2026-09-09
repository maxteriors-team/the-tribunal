import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { MessageComposer } from "@/components/assistant/assistant-chat-views";
import { clearDiagnostics, recordApiFailure } from "@/lib/assistant/diagnostics";

const { captureScreenFrameMock } = vi.hoisted(() => ({ captureScreenFrameMock: vi.fn() }));

vi.mock("@/lib/ai/screen-capture", () => ({ captureScreenFrame: captureScreenFrameMock }));

function renderComposer(overrides: Partial<Parameters<typeof MessageComposer>[0]> = {}) {
  const onImageChange = vi.fn();
  const onInputChange = vi.fn();
  render(
    <MessageComposer
      input=""
      isStreaming={false}
      canSend
      imageDataUrl={null}
      isEnhancing={false}
      enhancementError={null}
      onInputChange={onInputChange}
      onImageChange={onImageChange}
      onEnhance={vi.fn()}
      onSubmit={vi.fn()}
      onKeyDown={vi.fn()}
      onStop={vi.fn()}
      {...overrides}
    />,
  );
  return { onImageChange, onInputChange };
}

const readScreen = () => screen.getByRole("button", { name: "Read my screen" });

describe("MessageComposer screen capture", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    clearDiagnostics();
  });

  it("attaches the captured frame and prefills a prompt carrying recent failures", async () => {
    const user = userEvent.setup();
    captureScreenFrameMock.mockResolvedValue({ dataUrl: "data:image/png;base64,AAAA" });
    recordApiFailure({ method: "get", url: "/api/v1/workspaces/w1/contacts", status: 500 });
    const { onImageChange, onInputChange } = renderComposer();

    await user.click(readScreen());

    expect(onImageChange).toHaveBeenCalledWith("data:image/png;base64,AAAA");
    const prompt = onInputChange.mock.calls[0][0] as string;
    expect(prompt).toContain("Troubleshoot what I'm looking at");
    expect(prompt).toContain("GET /api/v1/workspaces/w1/contacts → 500");
  });

  it("keeps a message the user already typed", async () => {
    const user = userEvent.setup();
    captureScreenFrameMock.mockResolvedValue({ dataUrl: "data:image/png;base64,AAAA" });
    const { onImageChange, onInputChange } = renderComposer({ input: "why is this blank?" });

    await user.click(readScreen());

    expect(onImageChange).toHaveBeenCalledWith("data:image/png;base64,AAAA");
    expect(onInputChange).not.toHaveBeenCalled();
  });

  it("stays silent when the user dismisses the share picker", async () => {
    const user = userEvent.setup();
    captureScreenFrameMock.mockResolvedValue({ cancelled: true });
    const { onImageChange, onInputChange } = renderComposer();

    await user.click(readScreen());

    expect(onImageChange).not.toHaveBeenCalled();
    expect(onInputChange).not.toHaveBeenCalled();
    expect(screen.queryByText(/could not capture/i)).not.toBeInTheDocument();
  });

  it("surfaces a capture failure instead of attaching nothing", async () => {
    const user = userEvent.setup();
    captureScreenFrameMock.mockResolvedValue({ error: "This browser can't share a screen." });
    const { onImageChange } = renderComposer();

    await user.click(readScreen());

    expect(onImageChange).not.toHaveBeenCalled();
    expect(screen.getByText("This browser can't share a screen.")).toBeInTheDocument();
  });

  it("cannot be fired twice while a capture is in flight", async () => {
    const user = userEvent.setup();
    let resolveCapture: (value: { dataUrl: string }) => void = () => {};
    captureScreenFrameMock.mockReturnValue(
      new Promise<{ dataUrl: string }>((resolve) => {
        resolveCapture = resolve;
      }),
    );
    renderComposer();

    await user.click(readScreen());
    expect(readScreen()).toBeDisabled();

    await act(async () => {
      resolveCapture({ dataUrl: "data:image/png;base64,AAAA" });
    });

    expect(readScreen()).toBeEnabled();
    expect(captureScreenFrameMock).toHaveBeenCalledTimes(1);
  });
});
