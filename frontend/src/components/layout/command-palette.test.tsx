import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CommandPalette } from "@/components/layout/command-palette";

const { contactsListMock, campaignsListMock, pushMock, useWorkspaceIdMock } = vi.hoisted(() => ({
  contactsListMock: vi.fn(),
  campaignsListMock: vi.fn(),
  pushMock: vi.fn(),
  useWorkspaceIdMock: vi.fn(),
}));

vi.mock("@/lib/api/contacts", () => ({
  contactsApi: { list: contactsListMock },
}));

vi.mock("@/lib/api/campaigns", () => ({
  campaignsApi: { list: campaignsListMock },
}));

vi.mock("@/hooks/useWorkspaceId", () => ({
  useWorkspaceId: () => useWorkspaceIdMock(),
}));

// Grant every capability so all command-palette nav items are visible.
vi.mock("@/hooks/useCapabilities", () => ({
  useCapabilities: () => ({ tier: "admin", can: () => true }),
}));

// Collapse the search debounce so the API-backed branches settle synchronously.
vi.mock("@/hooks/useDebounce", () => ({
  useDebounce: (value: string) => value,
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
}));

const EMPTY_PAGE = { items: [], total: 0, page: 1, page_size: 5, pages: 0 };
const PLACEHOLDER = "Search pages, contacts, campaigns...";

function renderPalette() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  render(
    <QueryClientProvider client={client}>
      <CommandPalette open onOpenChange={() => {}} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  useWorkspaceIdMock.mockReturnValue("ws-1");
  contactsListMock.mockResolvedValue(EMPTY_PAGE);
  campaignsListMock.mockResolvedValue(EMPTY_PAGE);
});

describe("CommandPalette", () => {
  it("lists navigation items grouped by section while the input is empty", () => {
    renderPalette();

    // Section headings + a sample of items from different sections.
    expect(screen.getByText("Workspace")).toBeInTheDocument();
    expect(screen.getByText("Dashboard")).toBeInTheDocument();
    expect(screen.getByText("Quotes")).toBeInTheDocument();
    expect(screen.getByText("Contacts")).toBeInTheDocument();
  });

  it("surfaces matching pages under a Pages group when the user types (regression)", async () => {
    renderPalette();

    await userEvent.type(screen.getByPlaceholderText(PLACEHOLDER), "quotes");

    // The typed query now yields a "Pages" group with the matching page — the
    // exact behavior the placeholder promises and that was previously broken.
    expect(await screen.findByText("Pages")).toBeInTheDocument();
    expect(screen.getByText("Quotes")).toBeInTheDocument();

    // Non-matching nav items and the section headings drop out under a query.
    expect(screen.queryByText("Dashboard")).not.toBeInTheDocument();
    expect(screen.queryByText("Workspace")).not.toBeInTheDocument();
    expect(screen.queryByText("No results found.")).not.toBeInTheDocument();
  });

  it("matches pages by url when the title does not contain the query", async () => {
    renderPalette();

    // The Price Book page lives at /catalog; typing the route should find it.
    await userEvent.type(screen.getByPlaceholderText(PLACEHOLDER), "catalog");

    expect(await screen.findByText("Pages")).toBeInTheDocument();
    expect(screen.getByText("Price Book")).toBeInTheDocument();
  });

  it("navigates to the matched page when it is selected", async () => {
    renderPalette();

    await userEvent.type(screen.getByPlaceholderText(PLACEHOLDER), "quotes");
    await userEvent.click(await screen.findByText("Quotes"));

    expect(pushMock).toHaveBeenCalledWith("/quotes");
  });

  it("shows the empty state when nothing matches pages, contacts, or campaigns", async () => {
    renderPalette();

    await userEvent.type(screen.getByPlaceholderText(PLACEHOLDER), "zzzzz");

    await waitFor(() => expect(screen.getByText("No results found.")).toBeInTheDocument());
    expect(screen.queryByText("Pages")).not.toBeInTheDocument();
  });
});
