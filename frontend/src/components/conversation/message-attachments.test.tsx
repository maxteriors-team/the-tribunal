import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { TimelineAttachment, TimelineItem } from "@/types/conversation";

import { MessageAttachments } from "./message-attachments";
import { SmsMessageItem } from "./sms-message-item";

const baseAttachment: TimelineAttachment = {
  id: "attachment-1",
  filename: "mms-1.jpg",
  content_type: "image/jpeg",
  size_bytes: 321,
  status: "ready",
  content_url:
    "/api/v1/workspaces/workspace/contacts/42/timeline/attachments/attachment-1/content",
};

function timelineItem(
  overrides: Partial<TimelineItem> = {},
): TimelineItem {
  return {
    id: "message-1",
    type: "sms",
    timestamp: "2026-08-11T12:00:00Z",
    direction: "inbound",
    is_ai: false,
    content: "",
    attachments: [baseAttachment],
    original_id: "message-1",
    original_type: "sms_message",
    ...overrides,
  };
}

describe("MessageAttachments", () => {
  it("renders a ready photo through the authenticated content route", () => {
    render(<MessageAttachments attachments={[baseAttachment]} />);

    const image = screen.getByRole("img", { name: "mms-1.jpg" });
    expect(image).toHaveAttribute("src", baseAttachment.content_url);
    expect(
      screen.getByRole("link", { name: "Open mms-1.jpg" }),
    ).toHaveAttribute("href", baseAttachment.content_url);
  });

  it("renders ready video with native playback controls", () => {
    render(
      <MessageAttachments
        attachments={[
          {
            ...baseAttachment,
            filename: "mms-1.mp4",
            content_type: "video/mp4",
          },
        ]}
      />,
    );

    const video = screen.getByLabelText("mms-1.mp4");
    expect(video.tagName).toBe("VIDEO");
    expect(video).toHaveAttribute("controls");
    expect(video).toHaveAttribute("src", baseAttachment.content_url);
  });

  it("shows processing and failed attachment states", () => {
    const { rerender } = render(
      <MessageAttachments
        attachments={[{ ...baseAttachment, status: "processing" }]}
      />,
    );
    expect(screen.getByText("Receiving photo…")).toBeInTheDocument();

    rerender(
      <MessageAttachments
        attachments={[{ ...baseAttachment, status: "failed" }]}
      />,
    );
    expect(screen.getByText("Attachment unavailable")).toBeInTheDocument();
  });

  it("renders a media-only SMS without an empty text paragraph", () => {
    const { container } = render(<SmsMessageItem item={timelineItem()} />);

    expect(screen.getByRole("img", { name: "mms-1.jpg" })).toBeInTheDocument();
    expect(container.querySelector("p")).toBeNull();
  });
});
