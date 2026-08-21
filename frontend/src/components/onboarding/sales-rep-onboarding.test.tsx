import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SalesRepOnboarding } from "@/components/onboarding/sales-rep-onboarding";
import { hasCompletedSalesRepOnboarding } from "@/lib/sales-rep-onboarding-status";

const { replaceMock, searchParamsMock, toastSuccessMock } = vi.hoisted(() => ({
  replaceMock: vi.fn(),
  searchParamsMock: vi.fn(),
  toastSuccessMock: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: replaceMock }),
  useSearchParams: () => searchParamsMock(),
}));

vi.mock("sonner", () => ({
  toast: { success: toastSuccessMock },
}));

vi.mock("@/hooks/useMounted", () => ({
  useIsMounted: () => true,
}));

vi.mock("@/providers/auth-provider", () => ({
  useAuth: () => ({
    user: { id: 401, email: "rep@example.com", full_name: "Jordan Rivera" },
    isLoading: false,
  }),
}));

vi.mock("@/providers/workspace-provider", () => ({
  useWorkspace: () => ({
    currentWorkspace: {
      role: "sales_rep",
      workspace: { id: "workspace-flow", name: "Maxteriors" },
    },
    currentWorkspaceId: "workspace-flow",
    isPending: false,
  }),
}));

vi.mock("@/components/settings/google-calendar-card", () => ({
  GoogleCalendarCard: () => <div>Google Calendar connection</div>,
}));

vi.mock("@/components/wizard/wizard-container", () => ({
  WizardContainer: ({
    children,
    isFirstStep,
    isLastStep,
    onPrevious,
    onNext,
    onSubmit,
  }: {
    children: React.ReactNode;
    isFirstStep: boolean;
    isLastStep: boolean;
    onPrevious: () => void;
    onNext: () => void;
    onSubmit: () => void;
  }) => (
    <div>
      {children}
      {!isFirstStep && <button onClick={onPrevious}>Previous</button>}
      {!isLastStep ? (
        <button onClick={onNext}>Next</button>
      ) : (
        <button onClick={onSubmit}>Finish setup</button>
      )}
    </div>
  ),
}));

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  searchParamsMock.mockReturnValue(new URLSearchParams());
});

describe("SalesRepOnboarding", () => {
  it("walks a new rep through every setup section and records completion", async () => {
    const user = userEvent.setup();
    render(<SalesRepOnboarding />);

    expect(
      screen.getByRole("heading", { name: "Welcome to Maxteriors, Jordan" }),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Next" }));
    expect(
      screen.getByRole("heading", { name: "Make your activity recognizable" }),
    ).toBeInTheDocument();
    expect(replaceMock).toHaveBeenCalledWith("/sales-onboarding?step=profile", {
      scroll: false,
    });

    await user.click(screen.getByRole("button", { name: "Next" }));
    expect(
      screen.getByRole("heading", { name: "Connect the calendar that owns your appointments" }),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.getByRole("heading", { name: "Run the first-lead path" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Next" }));
    expect(
      screen.getByRole("heading", { name: "Ready for your first assigned lead" }),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Finish setup" }));

    expect(hasCompletedSalesRepOnboarding(401, "workspace-flow")).toBe(true);
    expect(toastSuccessMock).toHaveBeenCalledWith("Sales rep setup complete");
    expect(replaceMock).toHaveBeenCalledWith("/today");
  });

  it("restores the selected section after refresh or Google OAuth", async () => {
    searchParamsMock.mockReturnValue(
      new URLSearchParams("step=calendar&google_calendar=connected"),
    );

    render(<SalesRepOnboarding />);

    expect(
      await screen.findByRole("heading", {
        name: "Connect the calendar that owns your appointments",
      }),
    ).toBeInTheDocument();
  });
});
