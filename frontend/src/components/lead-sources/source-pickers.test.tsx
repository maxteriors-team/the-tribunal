import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi, beforeEach } from "vitest";

import {
  CampaignPicker,
  LeadSourcePicker,
  SourceTypePicker,
  sourceTypeLabel,
} from "@/components/lead-sources/source-pickers";
import type {
  LeadSource,
  LeadSourceCampaign,
} from "@/lib/api/lead-sources";

const { listMock, listCampaignsMock } = vi.hoisted(() => ({
  listMock: vi.fn(),
  listCampaignsMock: vi.fn(),
}));

vi.mock("@/lib/api/lead-sources", () => ({
  leadSourcesApi: {
    list: listMock,
    listCampaigns: listCampaignsMock,
  },
}));

function source(overrides: Partial<LeadSource> = {}): LeadSource {
  return {
    id: "src-1",
    workspace_id: "ws-1",
    name: "Spring FB Promo",
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

function campaign(overrides: Partial<LeadSourceCampaign> = {}): LeadSourceCampaign {
  return {
    id: "camp-1",
    workspace_id: "ws-1",
    lead_source_id: "src-1",
    name: "Retargeting",
    platform_campaign_id: null,
    platform_campaign_name: null,
    utm_campaign: null,
    description: null,
    enabled: true,
    campaign_metadata: {},
    started_on: null,
    ended_on: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

function renderWithClient(ui: React.ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("sourceTypeLabel", () => {
  it("maps channel codes to human labels", () => {
    expect(sourceTypeLabel("facebook_ads")).toBe("Facebook Ads");
    expect(sourceTypeLabel("google_ads")).toBe("Google Ads");
    expect(sourceTypeLabel("organic")).toBe("Organic");
    expect(sourceTypeLabel("phone_radio")).toBe("Phone / Radio");
    expect(sourceTypeLabel("other")).toBe("Other");
  });
});

describe("SourceTypePicker", () => {
  it("emits the selected channel code", async () => {
    const onChange = vi.fn();
    render(<SourceTypePicker value={undefined} onChange={onChange} />);

    await userEvent.click(screen.getByRole("combobox", { name: "Channel" }));
    await userEvent.click(
      await screen.findByRole("option", { name: "Facebook Ads" }),
    );

    expect(onChange).toHaveBeenCalledWith("facebook_ads");
  });

  it("can hide the catch-all Other option", async () => {
    render(
      <SourceTypePicker value={undefined} onChange={vi.fn()} includeOther={false} />,
    );

    await userEvent.click(screen.getByRole("combobox", { name: "Channel" }));

    expect(
      await screen.findByRole("option", { name: "Phone / Radio" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "Other" })).not.toBeInTheDocument();
  });
});

describe("LeadSourcePicker", () => {
  it("filters listed sources by channel and returns the picked source", async () => {
    listMock.mockResolvedValue([
      source({ id: "fb", name: "FB Promo", source_type: "facebook_ads" }),
      source({ id: "g", name: "Google Search", source_type: "google_ads" }),
      source({ id: "fb2", name: "FB Retarget", source_type: "facebook_ads" }),
    ]);
    const onChange = vi.fn();

    renderWithClient(
      <LeadSourcePicker
        workspaceId="ws-1"
        value={undefined}
        onChange={onChange}
        sourceType="facebook_ads"
      />,
    );

    await waitFor(() => expect(listMock).toHaveBeenCalledWith("ws-1"));
    await userEvent.click(
      await screen.findByRole("combobox", { name: "Lead source" }),
    );

    expect(await screen.findByRole("option", { name: "FB Promo" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "FB Retarget" })).toBeInTheDocument();
    // Google source is filtered out by the facebook_ads channel filter.
    expect(
      screen.queryByRole("option", { name: "Google Search" }),
    ).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("option", { name: "FB Retarget" }));
    expect(onChange).toHaveBeenCalledWith(
      "fb2",
      expect.objectContaining({ id: "fb2", name: "FB Retarget" }),
    );
  });

  it("disables the trigger when no sources match", async () => {
    listMock.mockResolvedValue([
      source({ id: "g", name: "Google Search", source_type: "google_ads" }),
    ]);

    renderWithClient(
      <LeadSourcePicker
        workspaceId="ws-1"
        value={undefined}
        onChange={vi.fn()}
        sourceType="phone_radio"
      />,
    );

    await waitFor(() => expect(listMock).toHaveBeenCalled());
    await waitFor(() =>
      expect(screen.getByRole("combobox", { name: "Lead source" })).toBeDisabled(),
    );
    expect(screen.getByText("No matching sources")).toBeInTheDocument();
  });
});

describe("CampaignPicker", () => {
  it("is disabled until a lead source is chosen", () => {
    renderWithClient(
      <CampaignPicker
        workspaceId="ws-1"
        leadSourceId={undefined}
        value={undefined}
        onChange={vi.fn()}
      />,
    );

    expect(screen.getByRole("combobox", { name: "Campaign" })).toBeDisabled();
    expect(screen.getByText("Pick a source first")).toBeInTheDocument();
    expect(listCampaignsMock).not.toHaveBeenCalled();
  });

  it("loads campaigns for the chosen source and emits the selection", async () => {
    listCampaignsMock.mockResolvedValue([
      campaign({ id: "c1", name: "Retargeting" }),
      campaign({ id: "c2", name: "Lookalike" }),
    ]);
    const onChange = vi.fn();

    renderWithClient(
      <CampaignPicker
        workspaceId="ws-1"
        leadSourceId="src-1"
        value={undefined}
        onChange={onChange}
      />,
    );

    await waitFor(() =>
      expect(listCampaignsMock).toHaveBeenCalledWith("ws-1", "src-1"),
    );
    await userEvent.click(
      await screen.findByRole("combobox", { name: "Campaign" }),
    );
    await userEvent.click(await screen.findByRole("option", { name: "Lookalike" }));

    expect(onChange).toHaveBeenCalledWith("c2");
  });
});
