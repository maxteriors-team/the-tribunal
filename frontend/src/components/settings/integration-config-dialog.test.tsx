import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { IntegrationConfigDialog } from "@/components/settings/integration-config-dialog";

const { testIntegrationMock } = vi.hoisted(() => ({
  testIntegrationMock: vi.fn(),
}));

vi.mock("@/hooks/useWorkspaceId", () => ({
  useWorkspaceId: () => "workspace-1",
}));

vi.mock("@/lib/api/integrations", () => ({
  integrationsApi: {
    create: vi.fn(),
    update: vi.fn(),
    test: testIntegrationMock,
  },
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

function renderDialog() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <IntegrationConfigDialog
        open
        onOpenChange={vi.fn()}
        integrationType="quo"
        existingIntegration={null}
      />
    </QueryClientProvider>,
  );
}

describe("IntegrationConfigDialog Quo configuration", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    testIntegrationMock.mockResolvedValue({
      success: true,
      message: "Successfully connected to Quo",
    });
  });

  it("collects the API key as a password and tests it only for the current workspace", async () => {
    const user = userEvent.setup();
    renderDialog();

    expect(screen.getByRole("heading", { name: "Connect Quo" })).toBeVisible();
    expect(screen.getByText("Create this in Quo Settings > Integrations > API keys")).toBeVisible();

    const keyInput = screen.getByLabelText("Quo API Key *");
    expect(keyInput).toHaveAttribute("type", "password");
    await user.type(keyInput, "quo_secret_key");
    await user.click(screen.getByRole("button", { name: "Test Connection" }));

    await waitFor(() =>
      expect(testIntegrationMock).toHaveBeenCalledExactlyOnceWith("workspace-1", "quo", {
        api_key: "quo_secret_key",
      }),
    );
    expect(await screen.findByText("Successfully connected to Quo")).toBeVisible();
  });
});
