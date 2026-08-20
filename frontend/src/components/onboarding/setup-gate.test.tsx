import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SetupGate } from "@/components/onboarding/setup-gate";

const { replaceMock, setupStatusMock, capabilitiesMock } = vi.hoisted(() => ({
  replaceMock: vi.fn(),
  setupStatusMock: vi.fn(),
  capabilitiesMock: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: replaceMock, push: vi.fn(), prefetch: vi.fn() }),
  usePathname: () => "/contacts",
}));

vi.mock("@/hooks/useSetupStatus", () => ({
  useSetupStatus: () => setupStatusMock(),
}));

vi.mock("@/hooks/useCapabilities", () => ({
  useCapabilities: () => capabilitiesMock(),
}));

/** An unconfigured workspace whose probe has settled — the gate's active state. */
const NEEDS_SETUP = { isLoading: false, needsSetup: true, workspaceId: "ws-1" };

/** Owner/admin: may configure the workspace. */
const OWNER = { tier: "admin" as const, can: () => true };
/** Field technician: operational-only, no workspace:manage. */
const TECHNICIAN = { tier: "field" as const, can: () => false };

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
});

describe("SetupGate", () => {
  it("nudges an owner of an unconfigured workspace into the wizard", () => {
    setupStatusMock.mockReturnValue(NEEDS_SETUP);
    capabilitiesMock.mockReturnValue(OWNER);

    render(<SetupGate />);

    expect(replaceMock).toHaveBeenCalledWith("/onboarding");
    expect(screen.getByText("Finish setting up your workspace")).toBeInTheDocument();
  });

  it("never redirects or shows setup UI to a member who cannot manage the workspace", () => {
    // Regression: a field technician was force-redirected into the owner setup
    // wizard on first login and shown the setup banner on every page.
    setupStatusMock.mockReturnValue(NEEDS_SETUP);
    capabilitiesMock.mockReturnValue(TECHNICIAN);

    const { container } = render(<SetupGate />);

    expect(replaceMock).not.toHaveBeenCalled();
    expect(container).toBeEmptyDOMElement();
  });

  it("waits for the role to resolve before redirecting an owner", () => {
    // The tier fails closed to "field" while the workspace/membership loads, so
    // the gate must act only once the probe settles — and must still redirect
    // the owner afterwards rather than skipping the nudge.
    setupStatusMock.mockReturnValue({ isLoading: true, needsSetup: false, workspaceId: null });
    capabilitiesMock.mockReturnValue(TECHNICIAN);

    const { rerender } = render(<SetupGate />);
    expect(replaceMock).not.toHaveBeenCalled();

    setupStatusMock.mockReturnValue(NEEDS_SETUP);
    capabilitiesMock.mockReturnValue(OWNER);
    rerender(<SetupGate />);

    expect(replaceMock).toHaveBeenCalledWith("/onboarding");
  });

  it("force-redirects at most once per workspace so a skipper is not trapped", () => {
    setupStatusMock.mockReturnValue(NEEDS_SETUP);
    capabilitiesMock.mockReturnValue(OWNER);

    const { unmount } = render(<SetupGate />);
    unmount();
    render(<SetupGate />);

    expect(replaceMock).toHaveBeenCalledTimes(1);
  });
});
