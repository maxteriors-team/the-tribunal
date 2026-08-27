import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ComponentProps } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { PhoneNumber } from "@/types/phone";

import { MessageComposer } from "./message-composer";

const prepareOutboundMmsImage = vi.hoisted(() => vi.fn());

vi.mock("@/lib/messaging/image-upload", () => ({
  MMS_IMAGE_ACCEPT: "image/jpeg,image/png,image/gif,image/webp",
  prepareOutboundMmsImage,
}));

const phone: PhoneNumber = {
  id: "phone-1",
  workspace_id: "workspace-1",
  phone_number: "+12125550101",
  provider: "telnyx",
  sms_enabled: true,
  voice_enabled: true,
  mms_enabled: true,
  lead_source_id: null,
  lead_source_campaign_id: null,
  tracking_label: null,
  lead_source: null,
  lead_source_campaign: null,
  is_active: true,
};

function renderComposer(overrides: Partial<ComponentProps<typeof MessageComposer>> = {}) {
  const onSend = vi.fn().mockResolvedValue(undefined);
  render(
    <MessageComposer
      message=""
      onMessageChange={vi.fn()}
      onSend={onSend}
      isSending={false}
      phoneNumbers={[phone]}
      selectedFromNumber={phone.phone_number}
      onFromNumberChange={vi.fn()}
      {...overrides}
    />,
  );
  return { onSend };
}

describe("MessageComposer outbound images", () => {
  beforeEach(() => {
    prepareOutboundMmsImage.mockReset();
    prepareOutboundMmsImage.mockResolvedValue({
      dataUrl: "data:image/jpeg;base64,/9j/",
      name: "driveway.jpg",
      sizeBytes: 120_000,
    });
  });

  it("previews and sends an image without requiring a caption", async () => {
    const { onSend } = renderComposer();
    const file = new File(["photo"], "driveway.jpg", { type: "image/jpeg" });

    fireEvent.change(screen.getByLabelText("Choose image attachment"), {
      target: { files: [file] },
    });

    expect(await screen.findByRole("img", { name: "Image attachment preview" })).toBeInTheDocument();
    expect(screen.getByText("driveway.jpg")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Send message" }));

    await waitFor(() =>
      expect(onSend).toHaveBeenCalledWith("data:image/jpeg;base64,/9j/"),
    );
    await waitFor(() =>
      expect(screen.queryByRole("img", { name: "Image attachment preview" })).not.toBeInTheDocument(),
    );
  });

  it("disables image selection for a number without MMS", () => {
    renderComposer({ phoneNumbers: [{ ...phone, mms_enabled: false }] });

    expect(screen.getByRole("button", { name: "Attach image" })).toBeDisabled();
  });

  it("keeps Quo replies fixed-sender and text-only", async () => {
    const { onSend } = renderComposer({
      message: "Quo reply",
      textOnly: true,
      phoneNumbers: [phone, { ...phone, id: "phone-2", phone_number: "+12125550102" }],
    });

    expect(screen.queryByText("Send from:")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Attach image" })).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Choose image attachment")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Voice message" })).not.toBeInTheDocument();

    fireEvent.keyDown(screen.getByPlaceholderText("Type a message..."), { key: "Enter" });
    await waitFor(() => expect(onSend).toHaveBeenCalledWith(undefined));
  });

  it("keeps the selected image when sending fails", async () => {
    const onSend = vi.fn().mockRejectedValue(new Error("provider failed"));
    renderComposer({ onSend });
    const file = new File(["photo"], "driveway.jpg", { type: "image/jpeg" });

    fireEvent.change(screen.getByLabelText("Choose image attachment"), {
      target: { files: [file] },
    });
    await screen.findByRole("img", { name: "Image attachment preview" });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));

    await waitFor(() => expect(onSend).toHaveBeenCalledOnce());
    expect(screen.getByRole("img", { name: "Image attachment preview" })).toBeInTheDocument();
  });
});
