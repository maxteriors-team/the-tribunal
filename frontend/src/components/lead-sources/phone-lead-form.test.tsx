import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PhoneLeadForm } from "@/components/lead-sources/phone-lead-form";
import type { LeadSource } from "@/lib/api/lead-sources";

const { listMock, listCampaignsMock, createContactMock } = vi.hoisted(() => ({
  listMock: vi.fn(),
  listCampaignsMock: vi.fn(),
  createContactMock: vi.fn(),
}));

vi.mock("@/lib/api/lead-sources", () => ({
  leadSourcesApi: {
    list: listMock,
    listCampaigns: listCampaignsMock,
  },
}));

vi.mock("@/lib/api/contacts", () => ({
  contactsApi: { create: createContactMock },
}));

function source(overrides: Partial<LeadSource> = {}): LeadSource {
  return {
    id: "src-radio",
    workspace_id: "ws-1",
    name: "WXYZ 102.5 Spot",
    public_key: "pk_1",
    allowed_domains: [],
    enabled: true,
    source_type: "phone_radio",
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
      <PhoneLeadForm workspaceId="ws-1" onCreated={onCreated} />
    </QueryClientProvider>,
  );
  return { onCreated };
}

beforeEach(() => {
  vi.clearAllMocks();
  listMock.mockResolvedValue([
    source(),
    // A non-phone source that must NOT appear in the Phone/Radio picker.
    source({ id: "src-fb", name: "Facebook Ads", source_type: "facebook_ads" }),
  ]);
  listCampaignsMock.mockResolvedValue([]);
});

describe("PhoneLeadForm", () => {
  it("only offers Phone/Radio sources and requires name, phone, and a source", async () => {
    renderForm();

    const submit = screen.getByRole("button", { name: "Add phone lead" });
    expect(submit).toBeDisabled();

    await userEvent.type(screen.getByLabelText("First name"), "Dana");
    await userEvent.type(screen.getByLabelText("Phone number"), "(555) 867-5309");
    expect(submit).toBeDisabled(); // still no source

    await userEvent.click(
      await screen.findByRole("combobox", { name: "Lead source" }),
    );
    expect(
      await screen.findByRole("option", { name: "WXYZ 102.5 Spot" }),
    ).toBeInTheDocument();
    // Facebook source is filtered out of the phone_radio picker.
    expect(
      screen.queryByRole("option", { name: "Facebook Ads" }),
    ).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("option", { name: "WXYZ 102.5 Spot" }));
    expect(submit).toBeEnabled();
  });

  it("creates a contact stamped with the phone/radio source attribution", async () => {
    createContactMock.mockResolvedValue({ id: 42, first_name: "Dana" });
    const { onCreated } = renderForm();

    await userEvent.type(screen.getByLabelText("First name"), "Dana");
    await userEvent.type(screen.getByLabelText("Phone number"), "(555) 867-5309");
    await userEvent.click(
      await screen.findByRole("combobox", { name: "Lead source" }),
    );
    await userEvent.click(
      await screen.findByRole("option", { name: "WXYZ 102.5 Spot" }),
    );

    await userEvent.click(screen.getByRole("button", { name: "Add phone lead" }));

    await waitFor(() =>
      expect(createContactMock).toHaveBeenCalledWith(
        "ws-1",
        expect.objectContaining({
          first_name: "Dana",
          phone_number: "(555) 867-5309",
          source: "phone",
          first_touch_lead_source_id: "src-radio",
          latest_touch_lead_source_id: "src-radio",
          attribution_confidence: 1,
        }),
      ),
    );
    await waitFor(() =>
      expect(onCreated).toHaveBeenCalledWith({ id: 42, first_name: "Dana" }),
    );
  });
});
