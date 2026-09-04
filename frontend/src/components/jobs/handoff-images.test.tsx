import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { HandoffImages } from "@/components/jobs/handoff-images";
import type { HandoffImage, HandoffImageList } from "@/lib/api/handoff-images";

const {
  deleteJobImageMock,
  deleteQuoteImageMock,
  listJobImagesMock,
  listQuoteImagesMock,
  uploadJobImageMock,
  uploadQuoteImageMock,
} = vi.hoisted(() => ({
  deleteJobImageMock: vi.fn(),
  deleteQuoteImageMock: vi.fn(),
  listJobImagesMock: vi.fn(),
  listQuoteImagesMock: vi.fn(),
  uploadJobImageMock: vi.fn(),
  uploadQuoteImageMock: vi.fn(),
}));

vi.mock("@/lib/api/handoff-images", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api/handoff-images")>(
    "@/lib/api/handoff-images",
  );
  return {
    ...actual,
    deleteJobHandoffImage: deleteJobImageMock,
    deleteQuoteHandoffImage: deleteQuoteImageMock,
    listJobHandoffImages: listJobImagesMock,
    listQuoteHandoffImages: listQuoteImagesMock,
    uploadJobHandoffImage: uploadJobImageMock,
    uploadQuoteHandoffImage: uploadQuoteImageMock,
  };
});

const image: HandoffImage = {
  id: "image-1",
  source: "quote",
  filename: "roof-before.png",
  content_type: "image/png",
  size_bytes: 128,
  created_at: "2026-08-28T12:00:00Z",
};

const jobImage: HandoffImage = {
  ...image,
  id: "job-image-1",
  source: "job",
  filename: "gate-code.png",
};

const emptyList: HandoffImageList = {
  images: [],
  max_images: 3,
  max_image_bytes: 10,
};

function renderQuotePanel() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <HandoffImages mode="quote-edit" workspaceId="workspace-1" quoteId="quote-1" />
    </QueryClientProvider>,
  );
}

function renderJobPanel() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <HandoffImages mode="technician-read" workspaceId="workspace-1" jobId="job-1" />
    </QueryClientProvider>,
  );
}

function fileInput(container: HTMLElement): HTMLInputElement {
  const input = container.querySelector<HTMLInputElement>('input[type="file"]');
  if (!input) throw new Error("Expected an image file input");
  return input;
}

describe("HandoffImages", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    listQuoteImagesMock.mockResolvedValue(emptyList);
    listJobImagesMock.mockResolvedValue(emptyList);
    uploadQuoteImageMock.mockResolvedValue(image);
    uploadJobImageMock.mockResolvedValue(jobImage);
    deleteQuoteImageMock.mockResolvedValue(undefined);
    deleteJobImageMock.mockResolvedValue(undefined);
  });

  it("shows the editable empty area and server limits", async () => {
    renderQuotePanel();

    expect(await screen.findByText("No handoff images added yet.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add images" })).toBeEnabled();
    expect(screen.getByText("Limit: 3 images, 10 B each. JPEG, PNG, or WebP.")).toBeInTheDocument();
  });

  it("rejects unsupported, oversized, and over-capacity selections before upload", async () => {
    const { container } = renderQuotePanel();
    await screen.findByText("No handoff images added yet.");
    const input = fileInput(container);

    fireEvent.change(input, {
      target: { files: [new File(["gif"], "site.gif", { type: "image/gif" })] },
    });
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "site.gif must be a JPEG, PNG, or WebP image.",
    );

    fireEvent.change(input, {
      target: { files: [new File(["12345678901"], "large.png", { type: "image/png" })] },
    });
    expect(await screen.findByRole("alert")).toHaveTextContent("large.png exceeds the 10 B limit.");

    const files = [0, 1, 2, 3].map(
      (index) => new File(["x"], `photo-${index}.png`, { type: "image/png" }),
    );
    fireEvent.change(input, { target: { files } });
    expect(await screen.findByRole("alert")).toHaveTextContent("Only 3 image spots remaining.");
    expect(uploadQuoteImageMock).not.toHaveBeenCalled();
  });

  it("uploads sequentially and deletes listed images", async () => {
    listQuoteImagesMock.mockResolvedValue({ ...emptyList, images: [image] });
    const { container } = renderQuotePanel();
    const user = userEvent.setup();
    await screen.findByRole("img", { name: "roof-before.png" });

    const first = new File(["one"], "one.png", { type: "image/png" });
    const second = new File(["two"], "two.webp", { type: "image/webp" });
    fireEvent.change(fileInput(container), { target: { files: [first, second] } });

    expect(await screen.findByRole("status")).toHaveTextContent("2 images uploaded.");
    expect(uploadQuoteImageMock).toHaveBeenNthCalledWith(1, "workspace-1", "quote-1", first);
    expect(uploadQuoteImageMock).toHaveBeenNthCalledWith(2, "workspace-1", "quote-1", second);

    await user.click(screen.getByRole("button", { name: "Remove roof-before.png" }));
    await waitFor(() => {
      expect(deleteQuoteImageMock).toHaveBeenCalledWith("workspace-1", "quote-1", "image-1");
    });
  });

  it("keeps accepted uploads visible and reports a partial failure", async () => {
    listQuoteImagesMock
      .mockResolvedValueOnce(emptyList)
      .mockResolvedValue({ ...emptyList, images: [image] });
    uploadQuoteImageMock
      .mockResolvedValueOnce(image)
      .mockRejectedValueOnce(new Error("Upload connection lost"));
    const { container } = renderQuotePanel();
    await screen.findByText("No handoff images added yet.");

    fireEvent.change(fileInput(container), {
      target: {
        files: [
          new File(["one"], "one.png", { type: "image/png" }),
          new File(["two"], "two.png", { type: "image/png" }),
        ],
      },
    });

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("1 uploaded. 1 failed");
    expect(alert).toHaveTextContent("two.png: Upload connection lost");
    expect(await screen.findByRole("img", { name: "roof-before.png" })).toBeInTheDocument();
    expect(listQuoteImagesMock).toHaveBeenCalledTimes(2);
  });

  it("renders technician job images without mutation controls", async () => {
    listJobImagesMock.mockResolvedValue({ ...emptyList, images: [jobImage] });
    renderJobPanel();

    expect(await screen.findByRole("img", { name: "gate-code.png" })).toHaveAttribute(
      "loading",
      "lazy",
    );
    expect(screen.getByRole("link", { name: "gate-code.png" })).toHaveAttribute(
      "href",
      "/api/v1/workspaces/workspace-1/jobs/job-1/handoff-images/job-image-1/download",
    );
    expect(screen.queryByRole("button", { name: "Add images" })).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Remove gate-code.png" }),
    ).not.toBeInTheDocument();
    expect(deleteQuoteImageMock).not.toHaveBeenCalled();
  });
  it("shows a direct-job empty state and uploads through the job route", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const user = userEvent.setup();
    const { container } = render(
      <QueryClientProvider client={client}>
        <HandoffImages mode="job-edit" workspaceId="workspace-1" jobId="direct-job" />
      </QueryClientProvider>,
    );

    expect(await screen.findByText("No handoff images added yet.")).toBeInTheDocument();
    expect(listJobImagesMock).toHaveBeenCalledWith("workspace-1", "direct-job");
    await user.click(screen.getByRole("button", { name: "Add images" }));
    const upload = new File(["image"], "direct.png", { type: "image/png" });
    await user.upload(fileInput(container), upload);

    await waitFor(() =>
      expect(uploadJobImageMock).toHaveBeenCalledWith("workspace-1", "direct-job", upload),
    );
    expect(uploadQuoteImageMock).not.toHaveBeenCalled();
  });

  it("only offers job-owned image deletion while editing a job", async () => {
    listJobImagesMock.mockResolvedValue({ ...emptyList, images: [image, jobImage] });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const user = userEvent.setup();
    render(
      <QueryClientProvider client={client}>
        <HandoffImages mode="job-edit" workspaceId="workspace-1" jobId="job-1" />
      </QueryClientProvider>,
    );

    expect(await screen.findByText("roof-before.png")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Remove roof-before.png" }),
    ).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Remove gate-code.png" }));

    await waitFor(() =>
      expect(deleteJobImageMock).toHaveBeenCalledWith("workspace-1", "job-1", "job-image-1"),
    );
    expect(deleteQuoteImageMock).not.toHaveBeenCalled();
  });

});
