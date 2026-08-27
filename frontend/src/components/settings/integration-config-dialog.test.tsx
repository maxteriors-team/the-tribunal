import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ComponentProps } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { IntegrationConfigDialog } from "@/components/settings/integration-config-dialog";
import { queryKeys } from "@/lib/query-keys";

const { createIntegrationMock, testIntegrationMock, updateIntegrationMock } = vi.hoisted(() => ({
  createIntegrationMock: vi.fn(),
  testIntegrationMock: vi.fn(),
  updateIntegrationMock: vi.fn(),
}));

vi.mock("@/hooks/useWorkspaceId", () => ({
  useWorkspaceId: () => "workspace-1",
}));

vi.mock("@/lib/api/integrations", () => ({
  integrationsApi: {
    create: createIntegrationMock,
    update: updateIntegrationMock,
    test: testIntegrationMock,
  },
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

function renderDialog(
  existingIntegration: ComponentProps<typeof IntegrationConfigDialog>["existingIntegration"] = null,
) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const view = render(
    <QueryClientProvider client={client}>
      <IntegrationConfigDialog
        open
        onOpenChange={vi.fn()}
        integrationType="quo"
        existingIntegration={existingIntegration}
      />
    </QueryClientProvider>,
  );
  return { ...view, client };
}

describe("IntegrationConfigDialog Quo configuration", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    createIntegrationMock.mockResolvedValue(undefined);
    updateIntegrationMock.mockResolvedValue(undefined);
    testIntegrationMock.mockResolvedValue({
      success: true,
      message: "Successfully connected to Quo",
      phone_numbers: [
        { id: "PN_one", phone_number: "+14155552671", provider_label: "Main" },
        { id: "PN_two", phone_number: "+14155552672", provider_label: "Sales" },
        { id: "PN_three", phone_number: "+14155552673", provider_label: null },
      ],
    });
  });

  it("requires one tested Quo number before connecting", async () => {
    const user = userEvent.setup();
    renderDialog();

    expect(screen.getByRole("heading", { name: "Connect Quo" })).toBeVisible();
    expect(screen.getByText("Create this in Quo Settings > Integrations > API keys")).toBeVisible();

    const keyInput = screen.getByLabelText("Quo API Key *");
    expect(keyInput).toHaveAttribute("type", "password");
    await user.type(keyInput, "quo_secret_key");
    await user.click(screen.getByRole("button", { name: "Connect" }));
    expect(await screen.findByText("Select one Quo phone number")).toBeVisible();
    expect(createIntegrationMock).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Test Connection" }));
    await waitFor(() =>
      expect(testIntegrationMock).toHaveBeenCalledExactlyOnceWith("workspace-1", "quo", {
        api_key: "quo_secret_key",
      }),
    );
    await user.click(screen.getByRole("combobox", { name: "Quo phone number" }));
    await user.click(screen.getByRole("option", { name: /Sales.*\(415\) 555-2672/ }));
    await user.click(screen.getByRole("button", { name: "Connect" }));

    await waitFor(() =>
      expect(createIntegrationMock).toHaveBeenCalledWith("workspace-1", {
        integration_type: "quo",
        credentials: { api_key: "quo_secret_key", phone_number_id: "PN_two" },
      }),
    );
  });

  it("switches the selected number without returning the stored API key", async () => {
    const user = userEvent.setup();
    const { client } = renderDialog({
      id: "integration-1",
      workspace_id: "workspace-1",
      integration_type: "quo",
      is_active: true,
      created_at: "2026-08-26T00:00:00Z",
      updated_at: "2026-08-26T00:00:00Z",
      masked_credentials: {
        api_key: "••••1234",
        phone_number_id: "PN_one",
        phone_number: "+14155552671",
      },
    });
    const removeQueries = vi.spyOn(client, "removeQueries");

    expect(screen.getByText(/Active number:/)).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Test Connection" }));
    await waitFor(() =>
      expect(testIntegrationMock).toHaveBeenCalledExactlyOnceWith("workspace-1", "quo", undefined),
    );
    await user.click(screen.getByRole("combobox", { name: "Quo phone number" }));
    await user.click(screen.getByRole("option", { name: /Sales.*\(415\) 555-2672/ }));
    await user.click(screen.getByRole("button", { name: "Update" }));

    await waitFor(() =>
      expect(updateIntegrationMock).toHaveBeenCalledWith("workspace-1", "quo", {
        credentials: { phone_number_id: "PN_two" },
      }),
    );
    expect(removeQueries).toHaveBeenCalledWith({
      queryKey: queryKeys.contacts.all("workspace-1"),
    });
  });
});
