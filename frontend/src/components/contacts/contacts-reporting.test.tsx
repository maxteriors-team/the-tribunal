import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ContactsPage } from "@/components/contacts/contacts-page";
import { ContactsStatsCards } from "@/components/contacts/contacts-stats-cards";
import {
  contactsApi,
  type ContactStatsResponse,
  type ContactsListParams,
} from "@/lib/api/contacts";
import { useContactStore } from "@/lib/contact-store";
import type { Contact } from "@/types";

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
}));
vi.mock("@/hooks/useWorkspaceId", () => ({ useWorkspaceId: () => "workspace" }));
vi.mock("@/hooks/useCapabilities", () => ({ useCapabilities: () => ({ can: () => false }) }));
// Closed dialogs and the filter editor are unrelated to reporting; keep the
// real page, store, query hooks, table, status controls and cards under test.
vi.mock("@/components/contacts/contact-form-dialog", () => ({ ContactFormDialog: () => null }));
vi.mock("@/components/contacts/import-contacts-dialog", () => ({
  ImportContactsDialog: () => null,
}));
vi.mock("@/components/contacts/scrape-leads-dialog", () => ({ ScrapeLeadsDialog: () => null }));
vi.mock("@/components/contacts/bulk-tag-dialog", () => ({ BulkTagDialog: () => null }));
vi.mock("@/components/filters/contact-filter-builder", () => ({
  ContactFilterBuilder: () => null,
}));

const stats: ContactStatsResponse = {
  new_leads_30d: 5,
  new_leads_change: null,
  new_clients_30d: 1,
  new_clients_change: null,
  total_new_clients_ytd: 2,
  client_metric_basis: "creation_cohort_current_status",
  period_start: "2026-08-11T12:00:00Z",
  period_end: "2026-09-10T12:00:00Z",
  year_start: "2026-01-01T06:00:00Z",
  timezone: "America/Chicago",
};
const statusCounts = { all: 101, new: 100, contacted: 0, qualified: 1, converted: 0, lost: 0 };
const newContacts: Contact[] = Array.from({ length: 100 }, (_, id) => ({
  id,
  user_id: 1,
  first_name: `Lead ${id}`,
  status: "new",
  created_at: "2026-09-01T12:00:00Z",
  updated_at: "2026-09-01T12:00:00Z",
}));
const qualifiedContact: Contact = {
  ...newContacts[0],
  id: 101,
  first_name: "Off-page",
  status: "qualified",
};

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ContactsPage />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.restoreAllMocks();
  useContactStore.setState(useContactStore.getInitialState());
  useContactStore.setState({ contactsPageSize: 100 });
  vi.spyOn(contactsApi, "getStats").mockResolvedValue(stats);
});

describe("contacts reporting scope", () => {
  it("shows the off-page qualified count and keeps All at 101 after selecting a status", async () => {
    const list = vi.spyOn(contactsApi, "list").mockImplementation(async (_workspace, params) => ({
      items: params?.status === "qualified" ? [qualifiedContact] : newContacts,
      total: params?.status === "qualified" ? 1 : 101,
      page: 1,
      page_size: 100,
      pages: params?.status === "qualified" ? 1 : 2,
      status_counts: statusCounts,
    }));
    renderPage();
    expect(await screen.findByRole("button", { name: "All 101" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.queryByText("Off-page")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Qualified 1" }));
    await waitFor(() =>
      expect(list).toHaveBeenLastCalledWith(
        "workspace",
        expect.objectContaining({ status: "qualified" }),
      ),
    );
    expect(await screen.findByText("Off-page")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "All 101" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
    expect(screen.getByRole("button", { name: "Qualified 1" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("uses server search/filter counts rather than workspace totals or page rows", async () => {
    const filters = {
      logic: "and" as const,
      rules: [{ field: "source", operator: "equals", value: "website" }],
    };
    useContactStore.setState({ searchQuery: "roof", filters });
    const list = vi.spyOn(contactsApi, "list").mockResolvedValue({
      items: [qualifiedContact],
      total: 2,
      page: 1,
      page_size: 100,
      pages: 1,
      status_counts: { ...statusCounts, all: 2, new: 0, qualified: 2 },
    });
    renderPage();
    expect(await screen.findByRole("button", { name: "All 2" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Qualified 2" })).toBeInTheDocument();
    expect(list).toHaveBeenCalledWith(
      "workspace",
      expect.objectContaining({ search: "roof", filters: JSON.stringify(filters) }),
    );
  });

  it("replaces previous search/status filters with the card's exact creation cohort", async () => {
    useContactStore.setState({ searchQuery: "old search", statusFilter: "lost", contactsPage: 3 });
    const list = vi.spyOn(contactsApi, "list").mockResolvedValue({
      items: [],
      total: 0,
      page: 1,
      page_size: 100,
      pages: 1,
      status_counts: statusCounts,
    });
    renderPage();
    fireEvent.click(
      await screen.findByRole("button", {
        name: "View converted contacts, created in past 30 days",
      }),
    );
    await waitFor(() =>
      expect(list).toHaveBeenLastCalledWith("workspace", {
        page: 1,
        page_size: 100,
        sort_by: "last_activity_desc",
        filters: JSON.stringify({
          logic: "and",
          rules: [
            { field: "created_at", operator: "gte", value: stats.period_start },
            { field: "created_at", operator: "lt", value: stats.period_end },
            { field: "status", operator: "equals", value: "converted" },
          ],
        }),
      } satisfies ContactsListParams),
    );
    expect(screen.getByPlaceholderText("Search contacts…")).toHaveValue("");
  });
});

describe("honest creation-cohort cards", () => {
  it.each([0, 5])(
    "shows no growth percentage or trend arrow with a zero baseline (current=%s)",
    (current) => {
      const { container } = render(
        <ContactsStatsCards
          stats={{ ...stats, new_leads_30d: current, new_clients_30d: current }}
          isPending={false}
          onViewContacts={vi.fn()}
        />,
      );
      expect(screen.getAllByText("No baseline")).toHaveLength(2);
      expect(screen.queryByText(/\+100%|\+0%/)).not.toBeInTheDocument();
      expect(container.querySelector(".lucide-trending-up, .lucide-trending-down")).toBeNull();
      expect(screen.queryByText("New clients")).not.toBeInTheDocument();
      expect(screen.getByText("Created in past 30 days")).toBeInTheDocument();
      expect(
        screen.getByText(/conversion dates and reconversions are not recorded/i),
      ).toBeInTheDocument();
    },
  );

  it("keeps genuine positive and negative percentages", () => {
    render(
      <ContactsStatsCards
        stats={{ ...stats, new_leads_change: "+24%", new_clients_change: "-10%" }}
        isPending={false}
        onViewContacts={vi.fn()}
      />,
    );
    expect(screen.getByText("+24%")).toHaveClass("text-success");
    expect(screen.getByText("-10%")).toHaveClass("text-destructive");
  });

  it("drills into the workspace-local YTD boundary provided by the API", () => {
    const onViewContacts = vi.fn();
    render(<ContactsStatsCards stats={stats} isPending={false} onViewContacts={onViewContacts} />);
    fireEvent.click(
      screen.getByRole("button", { name: "View converted contacts, created year to date" }),
    );
    expect(onViewContacts).toHaveBeenCalledWith({
      logic: "and",
      rules: [
        { field: "created_at", operator: "gte", value: stats.year_start },
        { field: "created_at", operator: "lt", value: stats.period_end },
        { field: "status", operator: "equals", value: "converted" },
      ],
    });
  });
});
