import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useWorkspace } from "@/providers/workspace-provider";

import NewEmailCampaignPage from "./page";

const { pushMock } = vi.hoisted(() => ({ pushMock: vi.fn() }));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
}));

vi.mock("@/components/layout/app-sidebar", () => ({
  AppSidebar: ({ children }: { children: ReactNode }) => <>{children}</>,
}));

vi.mock("@/components/campaigns/virtual-contact-selector", () => ({
  VirtualContactSelector: () => <div>Recipient selector</div>,
}));

vi.mock("@/lib/api/email-campaigns", () => ({
  emailCampaignsApi: {
    create: vi.fn(),
    addContacts: vi.fn(),
    start: vi.fn(),
  },
}));

vi.mock("@/providers/workspace-provider", () => ({
  useWorkspace: vi.fn(),
}));

const useWorkspaceMock = vi.mocked(useWorkspace);

describe("new email campaign tenant branding", () => {
  beforeEach(() => {
    pushMock.mockReset();
    useWorkspaceMock.mockReturnValue({
      workspaces: [],
      isPending: false,
      setCurrentWorkspace: vi.fn(),
      currentWorkspaceId: "ws_2",
      currentWorkspace: {
        role: "owner",
        is_default: false,
        workspace: {
          id: "ws_2",
          name: "Northstar Workspace",
          slug: "northstar-workspace",
          description: null,
          settings: {
            proposal_template: {
              business_name: "Northstar Outdoor Lighting",
              logo_url: "https://northstar.example/logo.svg",
            },
          },
          is_active: true,
          onboarding_completed_at: "2026-08-19T00:00:00Z",
          created_at: "2026-08-19T00:00:00Z",
          updated_at: "2026-08-19T00:00:00Z",
        },
      },
    });
  });

  it("uses a second workspace proposal brand instead of another tenant's name", () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });

    render(
      <QueryClientProvider client={queryClient}>
        <NewEmailCampaignPage />
      </QueryClientProvider>,
    );

    expect(screen.getByText("Northstar Outdoor Lighting")).toBeInTheDocument();
    expect(
      screen.getByPlaceholderText("Hi {first_name}, an update from Northstar Outdoor Lighting"),
    ).toBeInTheDocument();
    expect(screen.queryByText(/maxteriors/i)).not.toBeInTheDocument();
  });
});
