import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ProfileSettingsTab } from "@/components/settings/profile-settings-tab";

const { getProfileMock, setThemeMock, updateProfileMock } = vi.hoisted(() => ({
  getProfileMock: vi.fn(),
  setThemeMock: vi.fn(),
  updateProfileMock: vi.fn(),
}));

vi.mock("next-themes", () => ({
  useTheme: () => ({ resolvedTheme: "light", setTheme: setThemeMock }),
}));

vi.mock("@/lib/api/settings", () => ({
  settingsApi: {
    getProfile: getProfileMock,
    updateProfile: updateProfileMock,
  },
}));

function renderTab() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  render(
    <QueryClientProvider client={queryClient}>
      <ProfileSettingsTab />
    </QueryClientProvider>,
  );
}

describe("ProfileSettingsTab appearance preferences", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getProfileMock.mockResolvedValue({
      email: "operator@example.com",
      full_name: "Test Operator",
      phone_number: null,
      timezone: "America/New_York",
    });
  });

  it("removes Compact Mode rather than showing an inert switch", async () => {
    const user = userEvent.setup();
    renderTab();

    await screen.findByLabelText("Full Name");

    expect(screen.queryByRole("switch", { name: "Compact Mode" })).not.toBeInTheDocument();
    expect(screen.queryByText("Compact Mode")).not.toBeInTheDocument();

    await user.click(screen.getByRole("switch", { name: "Dark Mode" }));
    expect(setThemeMock).toHaveBeenCalledWith("dark");
  });
});
