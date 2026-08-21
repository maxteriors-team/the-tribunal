import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SalesRepOnboardingGate } from "@/components/onboarding/sales-rep-onboarding-gate";
import { markSalesRepOnboardingCompleted } from "@/lib/sales-rep-onboarding-status";

const { replaceMock, authMock, workspaceMock } = vi.hoisted(() => ({
  replaceMock: vi.fn(),
  authMock: vi.fn(),
  workspaceMock: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: replaceMock }),
}));

vi.mock("@/hooks/useMounted", () => ({
  useIsMounted: () => true,
}));

vi.mock("@/providers/auth-provider", () => ({
  useAuth: () => authMock(),
}));

vi.mock("@/providers/workspace-provider", () => ({
  useWorkspace: () => workspaceMock(),
}));

function workspace(role: string, id: string) {
  return {
    currentWorkspace: { role, workspace: { id, name: "Maxteriors" } },
    currentWorkspaceId: id,
    isPending: false,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  authMock.mockReturnValue({ user: { id: 301 }, isLoading: false });
});

describe("SalesRepOnboardingGate", () => {
  it("sends a new sales rep into setup and leaves a return reminder", () => {
    workspaceMock.mockReturnValue(workspace("sales_rep", "workspace-new"));

    render(<SalesRepOnboardingGate />);

    expect(replaceMock).toHaveBeenCalledWith("/sales-onboarding");
    expect(screen.getByText("Finish your sales rep setup")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Continue setup" })).toHaveAttribute(
      "href",
      "/sales-onboarding",
    );
  });

  it("never shows sales setup to another workspace role", () => {
    workspaceMock.mockReturnValue(workspace("manager", "workspace-manager"));

    const { container } = render(<SalesRepOnboardingGate />);

    expect(replaceMock).not.toHaveBeenCalled();
    expect(container).toBeEmptyDOMElement();
  });

  it("stops prompting after this user finishes in this workspace", () => {
    workspaceMock.mockReturnValue(workspace("sales_rep", "workspace-complete"));
    markSalesRepOnboardingCompleted(301, "workspace-complete");

    const { container } = render(<SalesRepOnboardingGate />);

    expect(replaceMock).not.toHaveBeenCalled();
    expect(container).toBeEmptyDOMElement();
  });

  it("auto-redirects only once so skipping does not trap the rep", () => {
    workspaceMock.mockReturnValue(workspace("sales_rep", "workspace-skip"));

    const { unmount } = render(<SalesRepOnboardingGate />);
    unmount();
    render(<SalesRepOnboardingGate />);

    expect(replaceMock).toHaveBeenCalledTimes(1);
  });
});
