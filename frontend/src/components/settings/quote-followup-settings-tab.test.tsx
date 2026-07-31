import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { QuoteFollowupSettingsTab } from "@/components/settings/quote-followup-settings-tab";
import type { QuoteFollowupSettings } from "@/lib/api/settings";

/**
 * Post-estimate cadence settings.
 *
 * The tab guards the cadence the backend refuses to accept: automated steps need
 * saved copy, the ladder needs at least one real conversation in it, and day 15+
 * belongs to the separate 30/60/90 revival sequence. Every one of these is a
 * server-side 422, so failing fast here is the difference between a clear
 * message and a rejected save.
 */

const { getMock, updateMock, templatesMock, useWorkspaceIdMock, toastErrorMock } = vi.hoisted(
  () => ({
    getMock: vi.fn(),
    updateMock: vi.fn(),
    templatesMock: vi.fn(),
    useWorkspaceIdMock: vi.fn(),
    toastErrorMock: vi.fn(),
  }),
);

vi.mock("@/lib/api/settings", () => ({
  settingsApi: {
    getQuoteFollowup: getMock,
    updateQuoteFollowup: updateMock,
  },
}));

vi.mock("@/lib/api/message-templates", () => ({
  messageTemplatesApi: { list: templatesMock },
}));

vi.mock("@/hooks/useWorkspaceId", () => ({
  useWorkspaceId: () => useWorkspaceIdMock(),
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: toastErrorMock },
}));

const TEMPLATE_ID = "11111111-1111-4111-8111-111111111111";

function settings(overrides: Partial<QuoteFollowupSettings> = {}): QuoteFollowupSettings {
  return {
    enabled: true,
    high_value_threshold: 10000,
    quiet_hours_start: "20:00:00",
    quiet_hours_end: "08:00:00",
    timezone: null,
    touches: [
      { offset_days: 1, channel: "sms", template_id: TEMPLATE_ID },
      { offset_days: 3, channel: "call", template_id: null },
      { offset_days: 7, channel: "email", template_id: TEMPLATE_ID },
    ],
    ...overrides,
  };
}

function renderTab() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  render(
    <QueryClientProvider client={client}>
      <QuoteFollowupSettingsTab />
    </QueryClientProvider>,
  );
}

describe("QuoteFollowupSettingsTab", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useWorkspaceIdMock.mockReturnValue("ws-1");
    templatesMock.mockResolvedValue({
      items: [{ id: TEMPLATE_ID, name: "Day 1 check-in", message_template: "Hi {first_name}" }],
      total: 1,
      page: 1,
      page_size: 100,
    });
    updateMock.mockImplementation(async () => settings());
  });

  it("seeds the saved cadence", async () => {
    getMock.mockResolvedValue(settings());
    renderTab();

    expect(await screen.findByLabelText("High-value quote threshold")).toHaveValue(10000);
    expect(screen.getByLabelText("Start")).toHaveValue("20:00");
    expect(screen.getByLabelText("End")).toHaveValue("08:00");
  });

  it("explains that high-value quotes get a call instead of a text", async () => {
    getMock.mockResolvedValue(settings());
    renderTab();

    expect(
      await screen.findByText(/SMS steps at or above this value become human call tasks/),
    ).toBeInTheDocument();
  });

  it("tells the operator to save templates before enabling automation", async () => {
    getMock.mockResolvedValue(settings());
    templatesMock.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 100 });
    renderTab();

    expect(
      await screen.findByText(/Save at least one message template/),
    ).toBeInTheDocument();
  });

  it("saves a valid cadence", async () => {
    const user = userEvent.setup();
    getMock.mockResolvedValue(settings());
    renderTab();

    await user.click(await screen.findByRole("button", { name: /Save cadence/ }));

    await waitFor(() =>
      expect(updateMock).toHaveBeenCalledWith(
        "ws-1",
        expect.objectContaining({ enabled: true, high_value_threshold: 10000 }),
      ),
    );
  });

  it("refuses to save an all-automated ladder", async () => {
    const user = userEvent.setup();
    getMock.mockResolvedValue(
      settings({
        touches: [
          { offset_days: 1, channel: "sms", template_id: TEMPLATE_ID },
          { offset_days: 3, channel: "sms", template_id: TEMPLATE_ID },
          { offset_days: 7, channel: "email", template_id: TEMPLATE_ID },
        ],
      }),
    );
    renderTab();

    await user.click(await screen.findByRole("button", { name: /Save cadence/ }));

    expect(toastErrorMock).toHaveBeenCalledWith("Add at least one human call task");
    expect(updateMock).not.toHaveBeenCalled();
  });

  it("refuses to save an enabled cadence whose SMS step has no copy", async () => {
    const user = userEvent.setup();
    getMock.mockResolvedValue(
      settings({
        touches: [
          { offset_days: 1, channel: "sms", template_id: null },
          { offset_days: 3, channel: "call", template_id: null },
          { offset_days: 7, channel: "email", template_id: TEMPLATE_ID },
        ],
      }),
    );
    renderTab();

    await user.click(await screen.findByRole("button", { name: /Save cadence/ }));

    expect(toastErrorMock).toHaveBeenCalledWith(
      "Choose a saved template for every SMS and email touch",
    );
    expect(updateMock).not.toHaveBeenCalled();
  });

  it("refuses a half-configured quiet-hours window", async () => {
    const user = userEvent.setup();
    getMock.mockResolvedValue(settings({ quiet_hours_end: null }));
    renderTab();

    await user.click(await screen.findByRole("button", { name: /Save cadence/ }));

    expect(toastErrorMock).toHaveBeenCalledWith("Set both quiet-hour times or clear both");
    expect(updateMock).not.toHaveBeenCalled();
  });

  it("caps the cadence at day 14 so it cannot collide with quote revival", async () => {
    getMock.mockResolvedValue(settings());
    renderTab();

    const days = await screen.findAllByLabelText("Day");
    expect(days).toHaveLength(3);
    for (const day of days) {
      expect(day).toHaveAttribute("max", "14");
    }
    expect(
      screen.getByText(/Day 15 and later are excluded/),
    ).toBeInTheDocument();
  });
});
