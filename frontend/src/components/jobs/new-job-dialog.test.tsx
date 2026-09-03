import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { NewJobDialog } from "@/components/jobs/new-job-dialog";
import { MAX_HANDOFF_IMAGE_BYTES } from "@/lib/api/handoff-images";

const { createJobMock, errorToastMock, successToastMock, uploadJobImageMock } = vi.hoisted(() => ({
  createJobMock: vi.fn(),
  errorToastMock: vi.fn(),
  successToastMock: vi.fn(),
  uploadJobImageMock: vi.fn(),
}));

vi.mock("@/hooks/useJobs", () => ({
  useCreateJob: () => ({ mutateAsync: createJobMock, isPending: false }),
  useWorkspaceTechnicians: () => ({ data: { items: [] } }),
}));

vi.mock("@/lib/api/handoff-images", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api/handoff-images")>(
    "@/lib/api/handoff-images",
  );
  return { ...actual, uploadJobHandoffImage: uploadJobImageMock };
});

vi.mock("sonner", () => ({
  toast: { error: errorToastMock, success: successToastMock },
}));

vi.mock("@/components/ui/contact-combobox", () => ({
  ContactPicker: ({ onChange }: { onChange: (contactId: string) => void }) => (
    <button type="button" onClick={() => onChange("42")}>
      Choose customer
    </button>
  ),
}));

vi.mock("@/components/jobs/technician-select", () => ({
  TechnicianSelect: () => <div>No technicians</div>,
}));

function renderDialog(onOpenChange = vi.fn()) {
  return {
    onOpenChange,
    ...render(
      <NewJobDialog
        workspaceId="workspace-1"
        open
        onOpenChange={onOpenChange}
      />,
    ),
  };
}

async function completeRequiredFields(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: "Choose customer" }));
  await user.type(screen.getByLabelText("Title"), "  Roofline install  ");
  await user.click(screen.getByLabelText("Schedule later"));
}

describe("NewJobDialog handoff images", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    createJobMock.mockResolvedValue({ id: "job-1" });
    uploadJobImageMock.mockResolvedValue({ id: "image-1" });
  });

  it("creates once, then uploads each staged image to that job", async () => {
    const user = userEvent.setup();
    const { onOpenChange } = renderDialog();
    await completeRequiredFields(user);
    await user.type(screen.getByLabelText("Job notes"), "Gate code 4417");
    const first = new File(["one"], "front.png", { type: "image/png" });
    const second = new File(["two"], "layout.webp", { type: "image/webp" });
    await user.upload(screen.getByLabelText("Field handoff images"), [first, second]);

    await user.click(screen.getByRole("button", { name: "Save job" }));

    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
    expect(createJobMock).toHaveBeenCalledTimes(1);
    expect(createJobMock).toHaveBeenCalledWith({
      contact_id: 42,
      title: "Roofline install",
      description: "Gate code 4417",
      scheduled_start: null,
      scheduled_end: null,
      technician_ids: [],
    });
    expect(uploadJobImageMock).toHaveBeenNthCalledWith(1, "workspace-1", "job-1", first);
    expect(uploadJobImageMock).toHaveBeenNthCalledWith(2, "workspace-1", "job-1", second);
    expect(successToastMock).toHaveBeenCalledWith("Job created with 2 handoff images");
  });

  it("reports partial upload failures without creating or retrying the job again", async () => {
    uploadJobImageMock
      .mockResolvedValueOnce({ id: "image-1" })
      .mockRejectedValueOnce(new Error("Connection lost"));
    const user = userEvent.setup();
    const { onOpenChange } = renderDialog();
    await completeRequiredFields(user);
    const first = new File(["one"], "front.png", { type: "image/png" });
    const second = new File(["two"], "rear.png", { type: "image/png" });
    await user.upload(screen.getByLabelText("Field handoff images"), [first, second]);

    await user.click(screen.getByRole("button", { name: "Save job" }));

    await waitFor(() => expect(errorToastMock).toHaveBeenCalled());
    expect(createJobMock).toHaveBeenCalledTimes(1);
    expect(uploadJobImageMock).toHaveBeenCalledTimes(2);
    expect(errorToastMock).toHaveBeenCalledWith(
      expect.stringContaining(
        "Job created, but 1 of 2 images failed — rear.png: Connection lost. Add them from job details.",
      ),
    );
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("rejects invalid staged files and lets dispatchers remove accepted ones", async () => {
    const user = userEvent.setup();
    const { container } = renderDialog();
    const input = screen.getByLabelText("Field handoff images") as HTMLInputElement;
    fireEvent.change(input, {
      target: { files: [new File(["bad"], "diagram.gif", { type: "image/gif" })] },
    });
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "diagram.gif must be a JPEG, PNG, or WebP image.",
    );

    const oversized = new File([new Uint8Array(MAX_HANDOFF_IMAGE_BYTES + 1)], "huge.png", {
      type: "image/png",
    });
    fireEvent.change(input, { target: { files: [oversized] } });
    expect(await screen.findByRole("alert")).toHaveTextContent("huge.png exceeds the 10 MB limit.");

    const accepted = new File(["image"], "front.png", { type: "image/png" });
    fireEvent.change(input, { target: { files: [accepted] } });
    expect(screen.getByText("front.png")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Remove front.png" }));
    expect(screen.queryByText("front.png")).not.toBeInTheDocument();
    expect(container.querySelectorAll('[aria-label="Selected handoff images"] li')).toHaveLength(0);
  });
});
