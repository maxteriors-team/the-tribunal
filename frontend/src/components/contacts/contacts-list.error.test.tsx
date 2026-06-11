import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ContactsList } from "@/components/contacts/contacts-list";

const { listMock, useWorkspaceIdMock } = vi.hoisted(() => ({
  listMock: vi.fn(),
  useWorkspaceIdMock: vi.fn(),
}));

vi.mock("@/lib/api/contacts", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api/contacts")>(
    "@/lib/api/contacts",
  );
  return {
    ...actual,
    contactsApi: { ...actual.contactsApi, list: listMock },
  };
});

vi.mock("@/hooks/useWorkspaceId", () => ({
  useWorkspaceId: () => useWorkspaceIdMock(),
}));

function renderWithClient(ui: React.ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

describe("ContactsList error state (RF-003)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useWorkspaceIdMock.mockReturnValue("ws_1");
  });

  it("renders the error+retry surface instead of the empty state when the query fails", async () => {
    listMock.mockRejectedValue(new Error("network blip"));

    renderWithClient(<ContactsList />);

    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: /try again/i }),
      ).toBeInTheDocument(),
    );

    // Critical: we must NOT tell the user their data is gone on a fetch failure.
    expect(screen.queryByText(/no contacts yet/i)).not.toBeInTheDocument();
  });
});
