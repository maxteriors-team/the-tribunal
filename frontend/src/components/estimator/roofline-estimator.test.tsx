import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { RooflineEstimator } from "@/components/estimator/roofline-estimator";

// The estimator never calls the pricing API until feet > 0, but mock it so a
// stray call can't hit the network during the upload interaction under test.
vi.mock("@/lib/api/estimator", () => ({
  estimatorApi: {
    estimate: vi.fn().mockResolvedValue(null),
    share: vi.fn().mockResolvedValue({ url: "" }),
  },
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
});
