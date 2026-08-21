import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Component, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AdLibraryClient } from "@/app/find-leads/ad-library/ad-library-client";
import { adLibraryApi } from "@/lib/api/ad-library";

vi.mock("@/hooks/useWorkspaceId", () => ({
  useWorkspaceId: () => "workspace-1",
}));

vi.mock("@/hooks/useCapabilities", () => ({
  useCapabilities: () => ({ can: () => true }),
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

class TestErrorBoundary extends Component<{ children: ReactNode }, { hasError: boolean }> {
  state = { hasError: false };

  static getDerivedStateFromError() {
    return { hasError: true };
  }

  render() {
    return this.state.hasError ? <p>Route crashed</p> : this.props.children;
  }
}

function renderClient() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: {
        retry: false,
        // Match the app-level policy that originally promoted every 5xx to the
        // route boundary. The search mutation must override this handled case.
        throwOnError: () => true,
      },
    },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <TestErrorBoundary>
        <AdLibraryClient />
      </TestErrorBoundary>
    </QueryClientProvider>,
  );
}

describe("AdLibraryClient", () => {
  beforeEach(() => {
    vi.spyOn(adLibraryApi, "listAdvertisers").mockResolvedValue({
      items: [],
      page: 1,
      page_size: 50,
      pages: 0,
      total: 0,
    });
    vi.spyOn(adLibraryApi, "listMonitors").mockResolvedValue([]);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("keeps the module usable when the provider is not configured", async () => {
    vi.spyOn(adLibraryApi, "search").mockRejectedValue(
      Object.assign(new Error("Ad Library provider is not configured"), {
        status: 503,
        response: {
          status: 503,
          data: {
            code: "ad_library_provider_unavailable",
            message: "Ad Library provider is not configured",
          },
        },
      }),
    );
    const user = userEvent.setup();
    renderClient();

    await user.type(screen.getByPlaceholderText("e.g. roofing contractors"), "roofing");
    await user.click(screen.getByRole("button", { name: "Search ad library" }));

    expect(await screen.findByText("Ad Library needs a provider token")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Set up ad-library access" })).toHaveAttribute(
      "href",
      "/settings?tab=integrations",
    );
    expect(screen.getByRole("heading", { name: "Ad Library" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Saved monitors" })).toBeInTheDocument();
    expect(screen.queryByText("Route crashed")).not.toBeInTheDocument();
  });
});
