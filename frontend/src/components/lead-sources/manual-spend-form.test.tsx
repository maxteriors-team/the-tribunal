import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ManualSpendForm } from "@/components/lead-sources/manual-spend-form";
import type { LeadSource } from "@/lib/api/lead-sources";

const { listMock, listCampaignsMock, createSpendMock } = vi.hoisted(() => ({
  listMock: vi.fn(),
  listCampaignsMock: vi.fn(),
  createSpendMock: vi.fn(),
}));

vi.mock("@/lib/api/lead-sources", () => ({
  leadSourcesApi: {
    list: listMock,
    listCampaigns: listCampaignsMock,
    createSpend: createSpendMock,
  },
}));

function source(overrides: Partial<LeadSource> = {}): LeadSource {
  return {
    id: "src-fb",
    workspace_id: "ws-1",
    name: "Facebook Ads",
    public_key: "pk_1",
    allowed_domains: [],
    enabled: true,
    source_type: "facebook_ads",
    action: "collect",
    action_config: {},
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    endpoint_url: "https://api.test/lead-sources/pk_1",
    ...overrides,
  };
}

function renderForm(onCreated = vi.fn()) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  render(
    <QueryClientProvider client={client}>
      <ManualSpendForm workspaceId="ws-1" onCreated={onCreated} />
    </QueryClientProvider>,
  );
  return { onCreated };
}

beforeEach(() => {
  vi.clearAllMocks();
  listMock.mockResolvedValue([source()]);
  listCampaignsMock.mockResolvedValue([]);
});

describe("ManualSpendForm", () => {
  it("keeps submit disabled until a source, amount, and dates are provided", async () => {
    renderForm();

    const submit = screen.getByRole("button", { name: "Record spend" });
    expect(submit).toBeDisabled();

    // Pick the source.
    await userEvent.click(
      await screen.findByRole("combobox", { name: "Lead source" }),
    );
    await userEvent.click(await screen.findByRole("option", { name: "Facebook Ads" }));

    // Amount only — still missing dates.
    await userEvent.type(screen.getByLabelText("Amount"), "500");
    expect(submit).toBeDisabled();

    fireEvent.change(screen.getByLabelText("Start date"), {
      target: { value: "2026-01-01" },
    });
    fireEvent.change(screen.getByLabelText("End date"), {
      target: { value: "2026-01-31" },
    });

    expect(submit).toBeEnabled();
  });

  it("blocks submission and warns when the end date precedes the start", async () => {
    renderForm();

    await userEvent.click(
      await screen.findByRole("combobox", { name: "Lead source" }),
    );
    await userEvent.click(await screen.findByRole("option", { name: "Facebook Ads" }));
    await userEvent.type(screen.getByLabelText("Amount"), "500");

    fireEvent.change(screen.getByLabelText("Start date"), {
      target: { value: "2026-02-10" },
    });
    fireEvent.change(screen.getByLabelText("End date"), {
      target: { value: "2026-02-01" },
    });

    expect(
      screen.getByText("End date must be on or after the start date."),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Record spend" })).toBeDisabled();
  });

  it("submits the spend entry with the expected API payload", async () => {
    createSpendMock.mockResolvedValue({ id: "spend-1" });
    const { onCreated } = renderForm();

    await userEvent.click(
      await screen.findByRole("combobox", { name: "Lead source" }),
    );
    await userEvent.click(await screen.findByRole("option", { name: "Facebook Ads" }));
    await userEvent.type(screen.getByLabelText("Amount"), "1200.50");
    fireEvent.change(screen.getByLabelText("Start date"), {
      target: { value: "2026-01-01" },
    });
    fireEvent.change(screen.getByLabelText("End date"), {
      target: { value: "2026-01-31" },
    });

    await userEvent.click(screen.getByRole("button", { name: "Record spend" }));

    await waitFor(() =>
      expect(createSpendMock).toHaveBeenCalledWith("ws-1", {
        lead_source_id: "src-fb",
        lead_source_campaign_id: null,
        spend_starts_on: "2026-01-01",
        spend_ends_on: "2026-01-31",
        amount: 1200.5,
        currency: "USD",
        notes: null,
      }),
    );
    await waitFor(() =>
      expect(onCreated).toHaveBeenCalledWith({ id: "spend-1" }),
    );
  });
});
