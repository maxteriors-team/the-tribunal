import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  UnsoldQuotesSettingsTab,
  activeTouches,
  describeSequence,
  toDraft,
  toPayload,
  validateDraft,
  type SequenceDraft,
} from "@/components/settings/unsold-quotes-settings-tab";
import type { UnsoldQuoteSettings } from "@/lib/api/unsold-quotes";

const { getMock, updateMock, listTemplatesMock, useWorkspaceIdMock, toastError } = vi.hoisted(
  () => ({
    getMock: vi.fn(),
    updateMock: vi.fn(),
    listTemplatesMock: vi.fn(),
    useWorkspaceIdMock: vi.fn(),
    toastError: vi.fn(),
  }),
);

vi.mock("@/lib/api/unsold-quotes", () => ({
  unsoldQuotesApi: { get: getMock, update: updateMock },
}));

vi.mock("@/lib/api/message-templates", () => ({
  messageTemplatesApi: { list: listTemplatesMock },
}));

vi.mock("@/hooks/useWorkspaceId", () => ({
  useWorkspaceId: () => useWorkspaceIdMock(),
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: toastError },
}));

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function settings(overrides: Partial<UnsoldQuoteSettings> = {}): UnsoldQuoteSettings {
  return {
    enabled: true,
    touches: [
      { day_offset: 30, hook: "price_validity", template_name: null, high_value_template_name: null },
      { day_offset: 60, hook: "seasonal", template_name: null, high_value_template_name: null },
      { day_offset: 90, hook: "financing", template_name: null, high_value_template_name: null },
    ],
    max_touches: 3,
    value_threshold: 5000,
    quiet_hours_start: "21:00",
    quiet_hours_end: "08:00",
    timezone: "America/Detroit",
    ...overrides,
  };
}

function draft(overrides: Partial<SequenceDraft> = {}): SequenceDraft {
  return { ...toDraft(settings()), ...overrides };
}

function renderTab() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <UnsoldQuotesSettingsTab />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  useWorkspaceIdMock.mockReturnValue("ws-1");
  getMock.mockResolvedValue(settings());
  updateMock.mockImplementation(async () => settings());
  listTemplatesMock.mockResolvedValue({
    items: [
      { id: "t1", name: "Price hold", message_template: "Hi {first_name}" },
      { id: "t2", name: "Big job financing", message_template: "Hi {first_name}" },
    ],
    total: 2,
  });
});

// ---------------------------------------------------------------------------
// Pure draft logic
// ---------------------------------------------------------------------------

describe("validateDraft", () => {
  it("accepts the shipped 30/60/90 cadence", () => {
    expect(validateDraft(draft()).touches).toEqual({});
  });

  it("refuses two touches on the same day instead of silently dropping one", () => {
    // The backend de-duplicates on write, so an unwarned operator would save
    // four touches and get three back with no idea which one went.
    const clashing = draft();
    clashing.touches[1].dayOffset = "30";

    const errors = validateDraft(clashing);
    expect(errors.touches[clashing.touches[1].key]).toMatch(/already uses this day/i);
  });

  it("rejects impossible days, stop-after values and thresholds", () => {
    const zeroDay = draft();
    zeroDay.touches[0].dayOffset = "0";
    expect(validateDraft(zeroDay).touches[zeroDay.touches[0].key]).toBeDefined();

    expect(validateDraft(draft({ maxTouches: "9" })).maxTouches).toBeDefined();
    expect(validateDraft(draft({ valueThreshold: "-1" })).valueThreshold).toBeDefined();
    expect(validateDraft(draft({ valueThreshold: "" })).valueThreshold).toBeDefined();
  });

  it("requires both ends of a quiet-hours window", () => {
    expect(validateDraft(draft({ quietStart: "21:00", quietEnd: "" })).quietHours).toBeDefined();
    expect(validateDraft(draft({ quietStart: "", quietEnd: "" })).quietHours).toBeUndefined();
  });
});

describe("activeTouches", () => {
  it("orders by day and stops at the stop-after limit", () => {
    const shortened = draft({ maxTouches: "2" });
    expect(activeTouches(shortened).map((touch) => touch.dayOffset)).toEqual(["30", "60"]);
  });

  it("sends nothing at zero without deleting the cadence", () => {
    const paused = draft({ maxTouches: "0" });
    expect(activeTouches(paused)).toEqual([]);
    expect(paused.touches).toHaveLength(3);
  });
});

describe("describeSequence", () => {
  it("states how many texts go out, on which days, and when they are held", () => {
    expect(describeSequence(draft())).toBe(
      "Each unsold quote gets 3 messages: day 30, day 60, day 90 after it was issued. " +
        "Nothing sends between 21:00 and 08:00 (America/Detroit).",
    );
  });

  it("says plainly that nothing sends while it is off", () => {
    expect(describeSequence(draft({ enabled: false }))).toMatch(/no messages are sent/i);
  });

  it("warns when quiet hours are off rather than staying silent", () => {
    expect(describeSequence(draft({ quietStart: "", quietEnd: "" }))).toMatch(
      /can send at any hour/i,
    );
  });

  it("calls out a cadence that would send nothing", () => {
    expect(describeSequence(draft({ maxTouches: "0" }))).toMatch(/no touches will send/i);
  });
});

describe("toPayload", () => {
  it("sends nulls for cleared optional fields", () => {
    const payload = toPayload(draft({ quietStart: "", quietEnd: "", timezone: "  " }));

    expect(payload.quiet_hours_start).toBeNull();
    expect(payload.quiet_hours_end).toBeNull();
    expect(payload.timezone).toBeNull();
    expect(payload.touches?.[0]).toEqual({
      day_offset: 30,
      hook: "price_validity",
      template_name: null,
      high_value_template_name: null,
    });
  });
});

// ---------------------------------------------------------------------------
// Rendered tab
// ---------------------------------------------------------------------------

describe("UnsoldQuotesSettingsTab", () => {
  it("reads the saved cadence back as a sentence", async () => {
    renderTab();

    expect(
      await screen.findByText(
        /Each unsold quote gets 3 messages: day 30, day 60, day 90 after it was issued\./,
      ),
    ).toBeInTheDocument();
    expect(screen.getByText(/Nothing sends between 21:00 and 08:00/)).toBeInTheDocument();
  });

  it("labels the two message slots with the job size that picks them", async () => {
    renderTab();

    const rows = await screen.findAllByRole("listitem");
    // Every touch carries both messages, so the threshold is legible on the row
    // rather than only in the card below it.
    expect(within(rows[0]).getByLabelText("Under $5,000")).toBeInTheDocument();
    expect(within(rows[0]).getByLabelText("$5,000 and up")).toBeInTheDocument();
    expect(screen.getAllByLabelText("Under $5,000")).toHaveLength(rows.length);
  });

  it("marks touches beyond the stop-after limit as not sent", async () => {
    getMock.mockResolvedValue(settings({ max_touches: 2 }));
    renderTab();

    const rows = await screen.findAllByRole("listitem");
    expect(rows).toHaveLength(3);
    expect(within(rows[2]).getByText("Not sent")).toBeInTheDocument();
    expect(within(rows[0]).queryByText("Not sent")).not.toBeInTheDocument();
  });

  it("blocks the save while the cadence is invalid", async () => {
    const user = userEvent.setup();
    renderTab();

    const save = await screen.findByRole("button", { name: /save follow-up/i });
    expect(save).toBeEnabled();

    const firstDay = screen.getByLabelText("Days after issue", {
      selector: "#unsold-touch-0-day",
    });
    await user.clear(firstDay);
    await user.type(firstDay, "60");

    await waitFor(() => expect(save).toBeDisabled());
    expect(screen.getByText("Another touch already uses this day.")).toBeInTheDocument();
    expect(updateMock).not.toHaveBeenCalled();
  });

  it("saves the edited cadence, threshold and quiet hours", async () => {
    const user = userEvent.setup();
    renderTab();

    const threshold = await screen.findByLabelText("Large job starts at ($)");
    await user.clear(threshold);
    await user.type(threshold, "12000");

    await user.click(screen.getByRole("button", { name: /save follow-up/i }));

    await waitFor(() => expect(updateMock).toHaveBeenCalledTimes(1));
    const [workspaceId, payload] = updateMock.mock.calls[0];
    expect(workspaceId).toBe("ws-1");
    expect(payload.value_threshold).toBe(12000);
    expect(payload.enabled).toBe(true);
    expect(payload.touches).toHaveLength(3);
    expect(payload.quiet_hours_start).toBe("21:00");
  });

  it("keeps a deleted template selected instead of silently swapping the copy", async () => {
    getMock.mockResolvedValue(
      settings({
        touches: [
          {
            day_offset: 30,
            hook: "price_validity",
            template_name: "Deleted last week",
            high_value_template_name: null,
          },
        ],
      }),
    );
    renderTab();

    expect(
      await screen.findByText("This template is no longer in your library."),
    ).toBeInTheDocument();
  });

  it("adds a touch a month after the last one", async () => {
    const user = userEvent.setup();
    renderTab();

    await user.click(await screen.findByRole("button", { name: /add a touch/i }));

    expect(
      screen.getByLabelText("Days after issue", { selector: "#unsold-touch-3-day" }),
    ).toHaveValue(120);
  });
});
