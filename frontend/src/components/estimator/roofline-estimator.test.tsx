import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { RooflineEstimator } from "@/components/estimator/roofline-estimator";
import { estimatorApi } from "@/lib/api/estimator";
import type { LinearFeetEstimateResult } from "@/types/estimate";

// The estimator never calls the pricing API until feet > 0, but mock it so a
// stray call can't hit the network during the interactions under test.
vi.mock("@/lib/api/estimator", () => ({
  estimatorApi: {
    estimate: vi.fn().mockResolvedValue(null),
    share: vi.fn().mockResolvedValue({ url: "" }),
    deliver: vi.fn().mockResolvedValue({ ok: true, to: "" }),
  },
}));

// Isolate the component from canvas geometry: jsdom can't produce real traced
// points (getBoundingClientRect returns zeros), so force a positive measured
// footage. The measurement math itself is unit-tested in measure.test.ts.
// `pxPerFoot` stays 0 so `calibrated` is false — keeping the "set the scale"
// hint the upload tests assert on.
vi.mock("@/lib/estimator/measure", () => ({
  REFERENCE_PRESETS: [{ key: "front_door", label: "Front door (single)", feet: 6.67 }],
  rooflineFeet: () => 100,
  pxPerFoot: () => 0,
  polylineLength: () => 0,
}));

// jsdom ships no canvas 2D context; a minimal stub lets draw() run its path.
function stubCanvas() {
  const ctx = {
    clearRect: vi.fn(),
    drawImage: vi.fn(),
    save: vi.fn(),
    restore: vi.fn(),
    beginPath: vi.fn(),
    moveTo: vi.fn(),
    lineTo: vi.fn(),
    stroke: vi.fn(),
    arc: vi.fn(),
    fill: vi.fn(),
    strokeStyle: "",
    fillStyle: "",
    lineWidth: 0,
    lineJoin: "",
  } as unknown as CanvasRenderingContext2D;
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(ctx);
}

// FileReader + Image are async browser APIs jsdom doesn't drive; stub both so
// the upload chain (readAsDataURL -> Image.onload -> setHasImage) resolves
// synchronously inside the change event.
function stubImagePipeline() {
  class MockFileReader {
    onload: (() => void) | null = null;
    result: string | null = null;
    readAsDataURL() {
      this.result = "data:image/png;base64,AAAA";
      this.onload?.();
    }
  }
  class MockImage {
    onload: (() => void) | null = null;
    width = 1200;
    height = 800;
    set src(_value: string) {
      this.onload?.();
    }
  }
  vi.stubGlobal("FileReader", MockFileReader);
  vi.stubGlobal("Image", MockImage);
}

function renderEstimator() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <RooflineEstimator workspaceId="ws_1" />
    </QueryClientProvider>,
  );
}

describe("RooflineEstimator photo upload", () => {
  beforeEach(() => {
    stubCanvas();
    stubImagePipeline();
    // restoreAllMocks (below) resets the module mock fns, so re-establish safe
    // async defaults each test. feet is forced positive by the measure mock, so
    // the pricing query is always enabled and must resolve (not undefined). The
    // component only reads `estimate?.…`, so a null estimate is a valid resolve.
    vi.mocked(estimatorApi.estimate).mockResolvedValue(
      null as unknown as LinearFeetEstimateResult,
    );
    vi.mocked(estimatorApi.share).mockResolvedValue({
      url: "",
      token: "",
      contact_id: null,
      saved_to_customer: false,
    });
    vi.mocked(estimatorApi.deliver).mockResolvedValue({ ok: true, to: "" });
  });
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("mounts the measuring canvas after the first photo upload", async () => {
    const { container } = renderEstimator();

    // Before upload: empty prompt, no canvas, no draw tools.
    expect(container.querySelector("canvas")).toBeNull();
    expect(screen.getByText(/Upload a straight-on photo/i)).toBeInTheDocument();

    const input = container.querySelector<HTMLInputElement>(
      'input[type="file"]',
    );
    expect(input).not.toBeNull();

    const file = new File(["x"], "house.png", { type: "image/png" });
    fireEvent.change(input!, { target: { files: [file] } });

    // After upload the canvas + drawing controls appear — proving `hasImage`
    // flipped true. This is exactly what the pre-fix code failed to do, because
    // the canvas mounts on `hasImage` yet `hasImage` was only set inside a
    // callback that bailed when the canvas wasn't mounted yet.
    await waitFor(() =>
      expect(container.querySelector("canvas")).not.toBeNull(),
    );
    expect(
      screen.getByRole("button", { name: /2\. Roofline/i }),
    ).toBeInTheDocument();
    expect(screen.getByText(/set the scale/i)).toBeInTheDocument();
  });

  it("exposes the Save-to-customer fields once a photo is loaded", async () => {
    const { container } = renderEstimator();

    // No customer capture before a photo exists.
    expect(screen.queryByLabelText(/Customer name/i)).toBeNull();

    const input = container.querySelector<HTMLInputElement>(
      'input[type="file"]',
    );
    const file = new File(["x"], "house.png", { type: "image/png" });
    fireEvent.change(input!, { target: { files: [file] } });

    // After upload the rep can attach the estimate to a customer.
    await waitFor(() =>
      expect(screen.getByLabelText(/Customer name/i)).toBeInTheDocument(),
    );
    expect(screen.getByLabelText(/Customer email/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Customer phone/i)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Save & share/i }),
    ).toBeInTheDocument();
  });

  it("emails the saved estimate to the entered customer", async () => {
    vi.mocked(estimatorApi.share).mockResolvedValue({
      url: "https://app.test/p/compare/tok_123",
      token: "tok_123",
      contact_id: 42,
      saved_to_customer: true,
    });
    vi.mocked(estimatorApi.deliver).mockResolvedValue({
      ok: true,
      to: "buyer@example.com",
    });

    const { container } = renderEstimator();

    const input = container.querySelector<HTMLInputElement>(
      'input[type="file"]',
    );
    fireEvent.change(input!, {
      target: { files: [new File(["x"], "house.png", { type: "image/png" })] },
    });
    await waitFor(() =>
      expect(screen.getByLabelText(/Customer email/i)).toBeInTheDocument(),
    );

    // Enter the customer's email, then save/share the estimate.
    fireEvent.change(screen.getByLabelText(/Customer email/i), {
      target: { value: "buyer@example.com" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Save & share/i }));

    // The email action only appears after a save; it targets the entered email.
    const emailBtn = await screen.findByRole("button", {
      name: /Email estimate to buyer@example\.com/i,
    });
    expect(emailBtn).toBeEnabled();

    fireEvent.click(emailBtn);

    // Sends to the saved comparison token + entered email, then confirms.
    await waitFor(() =>
      expect(estimatorApi.deliver).toHaveBeenCalledWith(
        "ws_1",
        "tok_123",
        "buyer@example.com",
      ),
    );
    expect(
      await screen.findByText(/Sent to buyer@example\.com/i),
    ).toBeInTheDocument();
  });
});
