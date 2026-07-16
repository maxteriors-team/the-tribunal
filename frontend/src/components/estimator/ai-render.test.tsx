import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactElement } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AIRenderModal } from "@/components/estimator/ai-render";
import { estimatorApi } from "@/lib/api/estimator";
import { exportDesignJpeg } from "@/lib/estimator/export";
import type { Design, PhotoInfo } from "@/lib/estimator/types";

vi.mock("@/lib/api/estimator", () => ({
  estimatorApi: { render: vi.fn() },
}));

// The compositing pipeline needs a real canvas; jsdom has none. Mock it to a
// fixed data URL so the test proves the wiring (export -> render -> display),
// not the pixel engine (covered in render.test.ts).
vi.mock("@/lib/estimator/export", () => ({
  exportDesignJpeg: vi.fn().mockResolvedValue("data:image/jpeg;base64,DESIGN"),
}));

const PHOTO: PhotoInfo = {
  dataUrl: "data:image/png;base64,PHOTO",
  width: 1200,
  height: 800,
};
const DESIGN: Design = { calibration: null, runs: [], items: [] };

function wrap(node: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>);
}

afterEach(() => vi.clearAllMocks());

describe("AIRenderModal", () => {
  it("composites the design, calls the server render, and shows the result", async () => {
    vi.mocked(estimatorApi.render).mockResolvedValue({
      image: "data:image/jpeg;base64,RENDER",
    });

    wrap(
      <AIRenderModal
        workspaceId="ws-1"
        photo={PHOTO}
        design={DESIGN}
        productById={new Map()}
        onClose={() => {}}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /generate realistic photo/i }));

    await waitFor(() =>
      expect(screen.getByAltText("AI night render")).toBeInTheDocument(),
    );
    // The drawn design is flattened, then only that image is sent to the server.
    expect(exportDesignJpeg).toHaveBeenCalledOnce();
    expect(estimatorApi.render).toHaveBeenCalledWith("ws-1", {
      image: "data:image/jpeg;base64,DESIGN",
      mode: "seasonal",
      prompt: null,
    });
    expect(screen.getByAltText("AI night render")).toHaveAttribute(
      "src",
      "data:image/jpeg;base64,RENDER",
    );
  });

  it("shows the server error message when the render fails", async () => {
    vi.mocked(estimatorApi.render).mockRejectedValue({
      response: { data: { message: "AI render isn't available for this workspace." } },
    });

    wrap(
      <AIRenderModal
        workspaceId="ws-1"
        photo={PHOTO}
        design={DESIGN}
        productById={new Map()}
        onClose={() => {}}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /generate realistic photo/i }));

    await waitFor(() =>
      expect(
        screen.getByText("AI render isn't available for this workspace."),
      ).toBeInTheDocument(),
    );
    expect(screen.queryByAltText("AI night render")).not.toBeInTheDocument();
  });
});
