import { describe, expect, it } from "vitest";

import { getLatestQuoLink, getValidatedQuoLink } from "@/lib/api/quo-links";
import type { TimelineItem } from "@/types";

const quoItem = (overrides: Partial<TimelineItem> = {}): TimelineItem => ({
  id: "message-1",
  type: "sms",
  timestamp: "2026-08-26T12:00:00Z",
  content: "Hello",
  is_ai: false,
  original_id: "message-1",
  original_type: "sms_message",
  source_provider: "quo",
  external_url: "https://my.quo.com/inbox/conversations/abc",
  ...overrides,
});

describe("Quo timeline links", () => {
  it("accepts only exact HTTPS Quo links from Quo-sourced items", () => {
    expect(getValidatedQuoLink(quoItem())).toBe("https://my.quo.com/inbox/conversations/abc");
    expect(getValidatedQuoLink(quoItem({ source_provider: "telnyx" }))).toBeNull();
    expect(
      getValidatedQuoLink(quoItem({ external_url: "https://quo.example/inbox/conversations/abc" })),
    ).toBeNull();
    expect(
      getValidatedQuoLink(quoItem({ external_url: "http://my.quo.com/inbox/conversations/abc" })),
    ).toBeNull();
    expect(
      getValidatedQuoLink(
        quoItem({ external_url: "https://other.example@my.quo.com/inbox/conversations/abc" }),
      ),
    ).toBeNull();
  });

  it("uses the newest valid synced link and skips malformed newer values", () => {
    expect(
      getLatestQuoLink([
        quoItem({ id: "first", external_url: "https://my.quo.com/inbox/conversations/first" }),
        quoItem({ id: "second", external_url: "javascript:alert(1)" }),
      ]),
    ).toBe("https://my.quo.com/inbox/conversations/first");
  });
});
