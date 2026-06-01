import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { OpportunitiesList } from "@/components/opportunities/opportunities-list";
import type { OpportunitiesListResponse } from "@/lib/api/opportunities";
import type { Opportunity } from "@/types";

const { listMock } = vi.hoisted(() => ({ listMock: vi.fn() }));

vi.mock("@/lib/api/opportunities", () => ({
  opportunitiesApi: { list: listMock },
}));

function makeOpportunity(overrides: Partial<Opportunity> = {}): Opportunity {
  return {
    id: "opp_1",
    workspace_id: "ws_1",
    pipeline_id: "pipe_1",
    name: "Acme expansion",
    currency: "USD",
    probability: 50,
    status: "open",
    is_active: true,
    created_at: "2026-01-01T00:00:00.000Z",
    updated_at: "2026-01-01T00:00:00.000Z",
    ...overrides,
  };
}

function makeResponse(
  items: Opportunity[],
  overrides: Partial<OpportunitiesListResponse> = {},
): OpportunitiesListResponse {
  return {
    items,
    total: items.length,
    page: 1,
    page_size: 50,
    pages: 1,
    ...overrides,
  };
}

function renderList() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <OpportunitiesList workspaceId="ws_1" />
    </QueryClientProvider>,
  );
}

describe("OpportunitiesList", () => {
  beforeEach(() => {
    listMock.mockReset();
  });

  it("renders opportunities returned by the API", async () => {
    listMock.mockResolvedValue(
      makeResponse([
        makeOpportunity({ id: "opp_1", name: "Acme expansion" }),
        makeOpportunity({ id: "opp_2", name: "Globex renewal" }),
      ]),
    );

    renderList();

    expect(await screen.findByText("Acme expansion")).toBeInTheDocument();
    expect(screen.getByText("Globex renewal")).toBeInTheDocument();
  });

  it("debounces the search input into the API params", async () => {
    listMock.mockResolvedValue(makeResponse([makeOpportunity()]));
    const user = userEvent.setup();

    renderList();
    await screen.findByText("Acme expansion");

    const input = screen.getByPlaceholderText("Search opportunities...");
    await user.type(input, "globex");

    await waitFor(() => {
      expect(listMock).toHaveBeenCalledWith(
        "ws_1",
        expect.objectContaining({ search: "globex", page: 1 }),
      );
    });
  });

  it("shows the empty state when there are no opportunities", async () => {
    listMock.mockResolvedValue(makeResponse([]));

    renderList();

    expect(await screen.findByText("No opportunities found")).toBeInTheDocument();
  });

  it("paginates and requests the next page", async () => {
    listMock.mockResolvedValue(
      makeResponse([makeOpportunity()], { total: 120, pages: 3 }),
    );
    const user = userEvent.setup();

    renderList();
    await screen.findByText("Acme expansion");

    // Pagination summary from ResourceListPagination.
    expect(screen.getByText(/Showing 1 of 120 opportunities/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Next/i }));

    await waitFor(() => {
      expect(listMock).toHaveBeenCalledWith(
        "ws_1",
        expect.objectContaining({ page: 2 }),
      );
    });
  });

  it("disables next/prev on a single page of results", async () => {
    listMock.mockResolvedValue(makeResponse([makeOpportunity()]));

    renderList();
    await screen.findByText("Acme expansion");

    expect(screen.getByRole("button", { name: /Next/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /Previous/i })).toBeDisabled();
  });

  it("hides the pagination bar entirely when there are no results", async () => {
    listMock.mockResolvedValue(makeResponse([]));

    renderList();
    await screen.findByText("No opportunities found");

    expect(screen.queryByRole("button", { name: /Next/i })).not.toBeInTheDocument();
  });

  it("renders a row's status and probability badges", async () => {
    listMock.mockResolvedValue(
      makeResponse([
        makeOpportunity({ name: "Acme expansion", status: "won", probability: 100 }),
      ]),
    );

    renderList();

    const row = (await screen.findByText("Acme expansion")).closest("tr");
    expect(row).not.toBeNull();
    expect(within(row as HTMLElement).getByText("won")).toBeInTheDocument();
    expect(within(row as HTMLElement).getByText("100%")).toBeInTheDocument();
  });
});
