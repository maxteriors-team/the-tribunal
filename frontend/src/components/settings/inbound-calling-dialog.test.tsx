import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { InboundCallingDialog } from "@/components/settings/inbound-calling-dialog";
import type { PhoneNumber } from "@/types";

const { configureInboundMock, listAgentsMock, readinessMock } = vi.hoisted(() => ({
  configureInboundMock: vi.fn(),
  listAgentsMock: vi.fn(),
  readinessMock: vi.fn(),
}));

vi.mock("@/lib/api/agents", () => ({
  agentsApi: { list: listAgentsMock },
}));

vi.mock("@/lib/api/phone-numbers", () => ({
  phoneNumbersApi: {
    configureInbound: configureInboundMock,
    inboundReadiness: readinessMock,
  },
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

const number: PhoneNumber = {
  id: "phone-1",
  workspace_id: "workspace-1",
  phone_number: "+12025550100",
  friendly_name: "Main",
  provider: "telnyx",
  sms_enabled: true,
  voice_enabled: true,
  mms_enabled: true,
  imessage_enabled: false,
  lead_source_id: null,
  lead_source_campaign_id: null,
  tracking_label: null,
  lead_source: null,
  lead_source_campaign: null,
  is_active: true,
  inbound_ai_enabled: false,
};

const checks = [
  { code: "workspace", ready: true, message: "Workspace matches." },
  { code: "pilot", ready: true, message: "Workspace is enabled for the pilot." },
  { code: "provider_credentials", ready: true, message: "Telnyx is configured." },
  { code: "openai_credentials", ready: true, message: "OpenAI is configured." },
  { code: "agent", ready: false, message: "Choose an agent." },
  { code: "agent_provider", ready: false, message: "Choose an OpenAI agent." },
  { code: "fallback_number", ready: false, message: "Configure fallback." },
  { code: "transfer_destination", ready: false, message: "Configure transfer." },
];

function renderDialog() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <InboundCallingDialog
        workspaceId="workspace-1"
        number={number}
        trigger={<button type="button">AI calls</button>}
      />
    </QueryClientProvider>,
  );
}

describe("InboundCallingDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    readinessMock.mockResolvedValue({
      phone_number_id: "phone-1",
      ready: false,
      enabled: false,
      assigned_agent_id: null,
      fallback_configured: false,
      transfer_destination_configured: false,
      checks,
    });
    listAgentsMock.mockResolvedValue({
      items: [
        {
          id: "agent-1",
          name: "Receptionist",
          is_active: true,
          channel_mode: "voice",
          voice_provider: "openai",
          voice_id: "alloy",
        },
      ],
      total: 1,
      page: 1,
      page_size: 100,
      pages: 1,
    });
    configureInboundMock.mockResolvedValue({
      phone_number_id: "phone-1",
      ready: true,
      enabled: true,
      assigned_agent_id: "agent-1",
      fallback_configured: true,
      transfer_destination_configured: true,
      checks: checks.map((check) => ({ ...check, ready: true })),
    });
  });

  it("requires explicit disclosure acknowledgement and complete readiness", async () => {
    const user = userEvent.setup();
    renderDialog();
    await user.click(screen.getByRole("button", { name: "AI calls" }));

    expect(await screen.findByRole("heading", { name: "AI inbound answering" })).toBeVisible();
    expect(screen.getByText(/Before caller audio reaches OpenAI/)).toBeVisible();
    expect(screen.getByText(/Pilot calls are not raw-recorded/)).toBeVisible();
    const enable = screen.getByRole("button", { name: "Enable AI answering" });
    expect(enable).toBeDisabled();

    await user.click(screen.getByRole("combobox", { name: "Voice agent" }));
    await user.click(screen.getByRole("option", { name: "Receptionist" }));
    await user.type(screen.getByLabelText("Emergency fallback"), "+12025550123");
    await user.type(screen.getByLabelText("Human transfer"), "+12025550124");
    await user.click(screen.getByRole("checkbox"));

    expect(enable).toBeEnabled();
    await user.click(enable);

    await waitFor(() =>
      expect(configureInboundMock).toHaveBeenCalledExactlyOnceWith("workspace-1", "phone-1", {
        enabled: true,
        assigned_agent_id: "agent-1",
        fallback_number: "+12025550123",
        transfer_destination_number: "+12025550124",
      }),
    );
  });

  it("does not return or render stored fallback destinations", async () => {
    readinessMock.mockResolvedValue({
      phone_number_id: "phone-1",
      ready: true,
      enabled: false,
      assigned_agent_id: "agent-1",
      fallback_configured: true,
      transfer_destination_configured: true,
      checks: checks.map((check) => ({ ...check, ready: true })),
    });
    const user = userEvent.setup();
    renderDialog();
    await user.click(screen.getByRole("button", { name: "AI calls" }));

    const destinationInputs = await screen.findAllByPlaceholderText(
      "Configured; leave blank to keep",
    );
    expect(destinationInputs).toHaveLength(2);
    for (const input of destinationInputs) expect(input).toHaveValue("");
  });

  it("blocks activation when a replacement destination is invalid", async () => {
    readinessMock.mockResolvedValue({
      phone_number_id: "phone-1",
      ready: true,
      enabled: false,
      assigned_agent_id: "agent-1",
      fallback_configured: true,
      transfer_destination_configured: true,
      checks: checks.map((check) => ({ ...check, ready: true })),
    });
    const user = userEvent.setup();
    renderDialog();
    await user.click(screen.getByRole("button", { name: "AI calls" }));

    await user.type(await screen.findByLabelText("Emergency fallback"), "2025550123");
    await user.click(screen.getByRole("checkbox"));

    expect(screen.getByRole("button", { name: "Enable AI answering" })).toBeDisabled();
    expect(screen.getByText("Use E.164 format, such as +12025550123.")).toBeVisible();
  });
});
