import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { hydrateRoot, type Root } from "react-dom/client";
import { renderToString } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { OpenAIChatGPTCard } from "@/components/settings/openai-chatgpt-card";
import type { OpenAIOAuthStatus } from "@/lib/api/integrations";
import { queryKeys } from "@/lib/query-keys";

const { workspaceState, getStatusMock, startOAuthMock, pollDeviceCodeMock, disconnectOAuthMock } =
  vi.hoisted(() => ({
    workspaceState: { currentWorkspaceId: null as string | null },
    getStatusMock: vi.fn(),
    startOAuthMock: vi.fn(),
    pollDeviceCodeMock: vi.fn(),
    disconnectOAuthMock: vi.fn(),
  }));

vi.mock("@/providers/workspace-provider", () => ({
  useWorkspace: () => ({ currentWorkspaceId: workspaceState.currentWorkspaceId }),
}));

vi.mock("@/lib/api/integrations", () => ({
  integrationsApi: {
    getOpenAIOAuthStatus: getStatusMock,
    startOpenAIOAuth: startOAuthMock,
    pollOpenAIOAuthDeviceCode: pollDeviceCodeMock,
    disconnectOpenAIOAuth: disconnectOAuthMock,
  },
}));

vi.mock("sonner", () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
    info: vi.fn(),
  },
}));

const disconnectedStatus: OpenAIOAuthStatus = {
  connected: false,
  api_key_configured: false,
  realtime_model: "gpt-realtime-2",
};

function createQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, staleTime: Infinity },
      mutations: { retry: false },
    },
  });
}

function TestProviders({ client, children }: { client: QueryClient; children: ReactNode }) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  vi.clearAllMocks();
  workspaceState.currentWorkspaceId = null;
  getStatusMock.mockResolvedValue(disconnectedStatus);
  startOAuthMock.mockResolvedValue({
    method: "browser",
    expires_at: 1_800_000_000_000,
    authorization_url: "https://auth.openai.test/authorize",
    redirect_uri: "https://app.test/callback",
    poll_interval_seconds: 5,
  });
});

describe("OpenAIChatGPTCard hydration", () => {
  it("keeps readiness deterministic through hydration, then enables and starts sign-in", async () => {
    const serverClient = createQueryClient();
    const serverHtml = renderToString(
      <TestProviders client={serverClient}>
        <OpenAIChatGPTCard />
      </TestProviders>,
    );
    const container = document.createElement("div");
    container.innerHTML = serverHtml;
    document.body.appendChild(container);

    const serverButton = within(container).getByRole("button", { name: "Connect OpenAI" });
    expect(serverButton).toBeDisabled();
    expect(
      within(container).getByText("Checking this workspace’s OpenAI connection before sign-in…"),
    ).toBeInTheDocument();

    // Reproduce the production mismatch: the browser already knows its workspace
    // and has cached status while the server rendered without either one.
    workspaceState.currentWorkspaceId = "workspace-1";
    const client = createQueryClient();
    client.setQueryData(queryKeys.integrations.openAIOAuth("workspace-1"), disconnectedStatus);

    const popup = {
      document: { write: vi.fn() },
      location: { href: "about:blank" },
      close: vi.fn(),
    } as unknown as Window;
    const openSpy = vi.spyOn(window, "open").mockReturnValue(popup);
    const consoleErrorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    let root: Root | undefined;

    try {
      await act(async () => {
        root = hydrateRoot(
          container,
          <TestProviders client={client}>
            <OpenAIChatGPTCard />
          </TestProviders>,
        );
      });

      const connectButton = within(container).getByRole("button", { name: "Connect OpenAI" });
      await waitFor(() => expect(connectButton).toBeEnabled());
      expect(
        within(container).getByText(/Click connect, sign in with OpenAI\/ChatGPT/),
      ).toBeVisible();

      const hydrationErrors = consoleErrorSpy.mock.calls.filter(([message]) =>
        /hydration|server rendered HTML|did(?: not|n['’]t) match|patched/i.test(String(message)),
      );
      expect(hydrationErrors).toEqual([]);

      await userEvent.click(connectButton);

      await waitFor(() => expect(startOAuthMock).toHaveBeenCalledExactlyOnceWith("workspace-1"));
      expect(openSpy).toHaveBeenCalledWith("about:blank", "openai-codex-oauth");
      await waitFor(() => expect(popup.location.href).toBe("https://auth.openai.test/authorize"));
    } finally {
      await act(async () => root?.unmount());
      consoleErrorSpy.mockRestore();
      openSpy.mockRestore();
      container.remove();
    }
  });
});
