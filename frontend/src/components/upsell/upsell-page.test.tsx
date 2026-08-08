import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { UpsellPage } from "@/components/upsell/upsell-page";
import { can as roleCan, roleTier, type Capability } from "@/lib/permissions";

/**
 * Who may open the on-site selling screen.
 *
 * Product rule: quoting is a Lead Technician responsibility. A regular
 * technician who spots an upgrade hands the job to their lead rather than
 * pricing it themselves, so the screen has to say that plainly — the nav
 * already hides it, but a bookmark or a shared link still lands here, and a
 * wall of 403 toasts would read as the app being broken.
 */

const { capabilitiesMock, workspaceIdMock, listJobsMock, myStatsMock } = vi.hoisted(() => ({
  capabilitiesMock: vi.fn(),
  workspaceIdMock: vi.fn(),
  listJobsMock: vi.fn(),
  myStatsMock: vi.fn(),
}));

vi.mock("@/lib/api/upsell", () => ({
  upsellApi: {
    listJobs: listJobsMock,
    myStats: myStatsMock,
    jobCustomer: vi.fn(),
    listCatalog: vi.fn(),
    listCarePlans: vi.fn(),
    createQuote: vi.fn(),
    deliverQuote: vi.fn(),
  },
}));

vi.mock("@/hooks/useCapabilities", () => ({
  useCapabilities: () => capabilitiesMock(),
}));

vi.mock("@/hooks/useWorkspaceId", () => ({
  useWorkspaceId: () => workspaceIdMock(),
}));

function signedInAs(role: string) {
  capabilitiesMock.mockReturnValue({
    tier: roleTier(role),
    can: (capability: Capability) => roleCan(role, capability),
  });
}

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <UpsellPage />
    </QueryClientProvider>
  );
}

describe("UpsellPage — selling is a lead technician responsibility", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    workspaceIdMock.mockReturnValue("ws_1");
    listJobsMock.mockResolvedValue({ items: [], total: 0 });
    myStatsMock.mockResolvedValue(null);
  });

  it("tells a regular technician to hand the upsell to their lead", async () => {
    signedInAs("technician");
    renderPage();

    expect(await screen.findByText("Only lead techs can sell add-ons")).toBeInTheDocument();
  });

  it("does not fire scoped requests the server would refuse", async () => {
    signedInAs("technician");
    renderPage();

    await screen.findByText("Only lead techs can sell add-ons");
    expect(listJobsMock).not.toHaveBeenCalled();
  });

  it("lets a lead technician through to the job picker", async () => {
    signedInAs("lead_technician");
    renderPage();

    expect(screen.queryByText("Only lead techs can sell add-ons")).not.toBeInTheDocument();
  });

  it("lets an office tier through as well", async () => {
    signedInAs("admin");
    renderPage();

    expect(screen.queryByText("Only lead techs can sell add-ons")).not.toBeInTheDocument();
  });
});
