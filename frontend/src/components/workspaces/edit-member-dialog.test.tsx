import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { EditMemberDialog } from "./edit-member-dialog";

const { rosterMock, setInLeagueMock } = vi.hoisted(() => ({
  rosterMock: vi.fn(),
  setInLeagueMock: vi.fn(),
}));

vi.mock("@/hooks/useWorkspaceId", () => ({
  useWorkspaceId: () => "ws-1",
}));

vi.mock("@/hooks/useJobs", () => ({
  useWorkspaceRoster: () => rosterMock(),
  useSetMemberOnRoster: () => ({ mutate: vi.fn(), isPending: false }),
  useSetMemberInLeague: () => ({ mutate: setInLeagueMock, isPending: false }),
  useWorkspaceBookableStaff: () => ({ data: { items: [] }, isLoading: false }),
  useSetMemberBookable: () => ({ mutate: vi.fn(), isPending: false }),
}));

vi.mock("@/lib/api/workspaces", () => ({
  workspacesApi: {
    updateMemberRole: vi.fn(),
    removeMember: vi.fn(),
  },
}));

function Wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={new QueryClient()}>{children}</QueryClientProvider>;
}

function renderDialog() {
  render(
    <EditMemberDialog
      open
      onOpenChange={vi.fn()}
      member={{
        id: 42,
        email: "sam@example.com",
        full_name: "Sam Stringlight",
        role: "technician",
      }}
      currentUserRole="owner"
    />,
    { wrapper: Wrapper },
  );
}

describe("EditMemberDialog Lighting League selection", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    rosterMock.mockReturnValue({
      data: {
        items: [
          {
            id: "tech-1",
            user_id: 42,
            is_active: true,
            scoreboard_enabled: true,
          },
        ],
      },
      isLoading: false,
    });
  });

  it("lets a manager remove a rostered member from Lighting League", async () => {
    const user = userEvent.setup();
    renderDialog();

    const leagueSwitch = screen.getByRole("switch", { name: "Lighting League" });
    expect(leagueSwitch).toBeChecked();
    await user.click(leagueSwitch);

    expect(setInLeagueMock).toHaveBeenCalledWith(
      { technicianId: "tech-1", enabled: false },
      expect.objectContaining({ onSuccess: expect.any(Function), onError: expect.any(Function) }),
    );
  });

  it("requires a member to be on the job roster first", () => {
    rosterMock.mockReturnValue({ data: { items: [] }, isLoading: false });
    renderDialog();

    expect(screen.getByRole("switch", { name: "Lighting League" })).toBeDisabled();
  });
});
