import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { InvoicesList } from "@/components/invoices/invoices-list";
import { QuotesList } from "@/components/quotes/quotes-list";
import { queryKeys } from "@/lib/query-keys";
import { server } from "@/test/msw/server";
import type { Invoice, Quote } from "@/types";

const { workspaceId } = vi.hoisted(() => ({ workspaceId: vi.fn(() => "ws-1") }));
vi.mock("@/hooks/useWorkspaceId", () => ({ useWorkspaceId: workspaceId }));
vi.mock("@/hooks/useCapabilities", () => ({
  useCapabilities: () => ({ can: () => true }),
}));

const lists = [
  { resource: "invoices", prefix: "INV", List: InvoicesList, edit: "Edit invoice", save: "Save changes" },
  { resource: "quotes", prefix: "QUO", List: QuotesList, edit: "Edit quote", save: "Save changes" },
] as const;

function document(index: number, prefix: string): Invoice & Quote {
  const id = `${prefix}-${index}`;
  const timestamp = new Date(Date.UTC(2026, 0, 1, 0, index)).toISOString();
  return {
    id,
    workspace_id: "ws-1",
    contact_id: 7,
    contact_name: "Older Customer",
    number: `${prefix}-${String(index).padStart(6, "0")}`,
    title: "Garden lighting",
    status: "draft",
    subtotal: 100,
    tax_amount: 0,
    discount_amount: 0,
    total: 100,
    amount_paid: 0,
    currency: "USD",
    receipt_delivery: { status: "skipped" },
    created_at: timestamp,
    updated_at: timestamp,
    line_items: [{
      id: `${id}-line`, invoice_id: id, quote_id: id, name: "Lighting", quantity: 1,
      unit_price: 100, discount: 0, total: 100, is_optional: false, is_selected: true,
      created_at: timestamp, updated_at: timestamp,
    }],
  };
}

// Real API clients + list/dialog components; only the HTTP boundary is replaced.
// No delivery or payment handlers: accidental sends fail the suite's MSW guard.
function serveDocuments(resource: string, prefix: string, total: number) {
  const state = {
    rows: Array.from({ length: total }, (_, index) => document(total - index, prefix)),
    requests: [] as URLSearchParams[],
    deleted: [] as string[],
    updated: [] as string[],
    failList: false,
    failDelete: false,
    listWait: undefined as Promise<void> | undefined,
  };
  const path = `*/api/v1/workspaces/:workspaceId/${resource}`;
  server.use(
    http.get(path, async ({ request }) => {
      const params = new URL(request.url).searchParams;
      state.requests.push(params);
      if (state.failList) return HttpResponse.json({ detail: "List unavailable" }, { status: 500 });
      const page = Number(params.get("page") ?? 1);
      const pageSize = Number(params.get("page_size") ?? 50);
      const rows = state.rows.filter((row) =>
        (!params.has("status") || row.status === params.get("status")) &&
        (!params.has("contact_id") || String(row.contact_id) === params.get("contact_id")),
      );
      const response = HttpResponse.json({
        items: rows.slice((page - 1) * pageSize, page * pageSize),
        total: rows.length, page, page_size: pageSize, pages: Math.max(1, Math.ceil(rows.length / pageSize)),
      });
      await state.listWait;
      return response;
    }),
    http.get(`${path}/:id`, ({ params }) =>
      HttpResponse.json(state.rows.find((row) => row.id === params.id)),
    ),
    http.put(`${path}/:id`, async ({ params, request }) => {
      const body = await request.json();
      if (!body || typeof body !== "object") return new HttpResponse(null, { status: 422 });
      const index = state.rows.findIndex((row) => row.id === params.id);
      state.updated.push(String(params.id));
      state.rows[index] = { ...state.rows[index], ...body };
      return HttpResponse.json(state.rows[index]);
    }),
    http.delete(`${path}/:id`, ({ params }) => {
      if (state.failDelete) return HttpResponse.json({ detail: "Delete unavailable" }, { status: 500 });
      state.deleted.push(String(params.id));
      state.rows = state.rows.filter((row) => row.id !== params.id);
      return new HttpResponse(null, { status: 204 });
    }),
    http.get("*/api/v1/workspaces/:workspaceId/catalog-items", () => HttpResponse.json({
      items: [], total: 0, page: 1, page_size: 200, pages: 1,
    })),
    http.get("*/api/v1/workspaces/:workspaceId/contacts", () => HttpResponse.json({
      items: [{ id: 7, workspace_id: "ws-1", first_name: "Older", last_name: "Customer", phone_number: "+15555550107" }],
      total: 1, page: 1, page_size: 6, pages: 1,
    })),
  );
  return state;
}

function renderList(List: typeof InvoicesList) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  const result = render(<QueryClientProvider client={client}><List /></QueryClientProvider>);
  return { client, ...result };
}

beforeEach(() => {
  workspaceId.mockReturnValue("ws-1");
});

describe.each(lists)("$resource server pagination", ({ resource, prefix, List, edit, save }) => {
  it.each([0, 1, 100, 101, 305])("shows honest totals and reaches every record with %i documents", async (total) => {
    const state = serveDocuments(resource, prefix, total);
    renderList(List);
    const pageSize = 100;
    const pages = Math.max(1, Math.ceil(total / pageSize));
    const seen: string[] = [];
    for (let page = 1; page <= pages; page++) {
      const count = Math.min(pageSize, total - (page - 1) * pageSize);
      await waitFor(() => expect(screen.queryByText(`Showing ${count} of ${total} ${resource}`)).toBeInTheDocument());
      expect(screen.getByText(`${page} / ${pages}`)).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Previous" }).hasAttribute("disabled")).toBe(page === 1);
      expect(screen.getByRole("button", { name: "Next" }).hasAttribute("disabled")).toBe(page === pages);
      if (total) {
        const rows = within(screen.getByRole("table")).getAllByRole("row").slice(1);
        expect(rows).toHaveLength(count);
        seen.push(...rows.map((row) => within(row).getAllByRole("cell")[0].textContent ?? ""));
      }
      if (page < pages) await userEvent.click(screen.getByRole("button", { name: "Next" }));
    }
    expect(seen).toEqual(state.rows.map((row) => row.number));
    expect(state.requests.map((params) => params.get("page"))).toEqual(Array.from({ length: pages }, (_, index) => String(index + 1)));
    expect(state.requests.every((params) => params.get("page_size") === "100")).toBe(true);
    if (pages > 1) {
      await userEvent.click(screen.getByRole("button", { name: "Previous" }));
      await waitFor(() => expect(screen.getByText(`${pages - 1} / ${pages}`)).toBeInTheDocument());
    }
  });

  async function chooseStatus(status: string) {
    // Await Radix's positioning/focus updates without nesting userEvent's async wrapper.
    await act(async () => {
      fireEvent.keyDown(screen.getByRole("combobox", { name: "Status" }), { key: "Enter" });
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("option", { name: status }));
    });
  }

  async function filterToOlderCustomer() {
    await chooseStatus("Draft");
    const customer = screen.getByRole("combobox", { name: "Customer" });
    await userEvent.type(customer, "Older");
    await userEvent.click(await screen.findByRole("option", { name: /Older Customer/ }));
  }

  it("filters the entire dataset, resets changed filters, and clears empty results", async () => {
    const state = serveDocuments(resource, prefix, 101);
    state.rows.slice(0, 100).forEach((row) => { row.status = "sent"; row.contact_id = 8; });
    renderList(List);
    await screen.findByText(`Showing 100 of 101 ${resource}`);
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    await screen.findByText(`Showing 1 of 101 ${resource}`);
    await filterToOlderCustomer();
    await screen.findByText(`Showing 1 of 1 ${resource}`);
    expect(screen.getByText(`${prefix}-000001`)).toBeInTheDocument();
    expect(Object.fromEntries(state.requests.at(-1)!)).toEqual({ page: "1", page_size: "100", status: "draft", contact_id: "7" });
    await chooseStatus("Sent");
    await screen.findByText(`No matching ${resource}`);
    expect(screen.getByText(`Showing 0 of 0 ${resource}`)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Clear filters" }));
    await screen.findByText(`Showing 100 of 101 ${resource}`);
    expect(screen.getByRole("combobox", { name: "Customer" })).toHaveValue("");
    expect(Object.fromEntries(state.requests.at(-1)!)).toEqual({ page: "1", page_size: "100" });
  });

  it("keeps filters, page, and the selected older document while editing and refreshing", async () => {
    const state = serveDocuments(resource, prefix, 101);
    const { client } = renderList(List);
    await screen.findByText(`Showing 100 of 101 ${resource}`);
    await filterToOlderCustomer();
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    await screen.findByText(`Showing 1 of 101 ${resource}`);
    if (resource === "quotes") {
      await userEvent.click(screen.getByRole("button", { name: `${prefix}-000001` }));
    } else {
      await userEvent.click(screen.getByRole("button", { name: "Actions" }));
      await userEvent.click(screen.getByRole("menuitem", { name: "Edit invoice" }));
    }
    const dialog = await screen.findByRole("dialog", { name: new RegExp(edit, "i") });
    const notes = await within(dialog).findByLabelText("Notes");
    await userEvent.type(notes, "Keep this note");
    await act(async () => { await client.invalidateQueries({ queryKey: queryKeys[resource].all("ws-1") }); });
    expect(notes).toHaveValue("Keep this note");
    expect(within(dialog).getByText(new RegExp(`${prefix}-000001`))).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: save }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(state.updated).toEqual([`${prefix}-1`]);
    expect(screen.getByText("2 / 2")).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Customer" })).toHaveValue("Older Customer");
    expect(Object.fromEntries(state.requests.at(-1)!)).toEqual({ page: "2", page_size: "100", status: "draft", contact_id: "7" });
    expect(state.rows.at(-1)?.notes).toBe("Keep this note");
  });

  it.each([101, 102])("preserves older delete context, clamping only if needed (%i documents)", async (total) => {
    const state = serveDocuments(resource, prefix, total);
    state.failDelete = true;
    renderList(List);
    await screen.findByText(`Showing 100 of ${total} ${resource}`);
    await filterToOlderCustomer();
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    await screen.findByText(`Showing ${total - 100} of ${total} ${resource}`);
    const olderRow = screen.getByRole("row", { name: new RegExp(`${prefix}-000001`) });
    await userEvent.click(within(olderRow).getByRole("button", { name: "Actions" }));
    const deleteLabel = resource === "invoices" ? "Delete invoice" : "Delete quote";
    await userEvent.click(screen.getByRole("menuitem", { name: resource === "invoices" ? "Delete draft" : deleteLabel }));
    const dialog = screen.getByRole("alertdialog");
    await userEvent.click(within(dialog).getByRole("button", { name: deleteLabel }));
    await waitFor(() => expect(within(dialog).getByRole("button", { name: deleteLabel })).toBeEnabled());
    expect(within(dialog).getByText(new RegExp(`${prefix}-000001`))).toBeInTheDocument();
    expect(state.deleted).toEqual([]);
    state.failDelete = false;
    await userEvent.click(within(dialog).getByRole("button", { name: deleteLabel }));
    const lastPage = total === 101 ? 1 : 2;
    const lastCount = total === 101 ? 100 : 1;
    await screen.findByText(`Showing ${lastCount} of ${total - 1} ${resource}`);
    expect(screen.getByText(`${lastPage} / ${lastPage}`)).toBeInTheDocument();
    expect(state.deleted).toEqual([`${prefix}-1`]);
    expect(screen.getByRole("combobox", { name: "Customer" })).toHaveValue("Older Customer");
    const requestedPages = total === 101 ? ["2", "1"] : ["2"];
    expect(state.requests.slice(-requestedPages.length).map((params) => params.get("page"))).toEqual(requestedPages);
    expect(Object.fromEntries(state.requests.at(-1)!)).toEqual({ page: String(lastPage), page_size: "100", status: "draft", contact_id: "7" });
  });

  it("ignores a late page response after the status filter changes", async () => {
    const state = serveDocuments(resource, prefix, 101);
    state.rows.slice(0, 100).forEach((row) => { row.status = "sent"; });
    const { client } = renderList(List);
    await screen.findByText(`Showing 100 of 101 ${resource}`);
    let release = () => {};
    state.listWait = new Promise<void>((resolve) => { release = resolve; });
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    await waitFor(() => expect(state.requests.at(-1)?.get("page")).toBe("2"));
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.queryByText(/Showing/)).not.toBeInTheDocument();
    state.listWait = undefined;
    await chooseStatus("Sent");
    await screen.findByText(`Showing 100 of 100 ${resource}`);
    await act(async () => { release(); });
    await waitFor(() => expect(client.isFetching()).toBe(0));
    expect(screen.queryByText(`${prefix}-000001`)).not.toBeInTheDocument();
    expect(screen.getByText("1 / 1")).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Status" })).toHaveTextContent("Sent");
  });

  it("clears the old workspace's filters, page, and selected document on workspace change", async () => {
    const state = serveDocuments(resource, prefix, 101);
    const { client, rerender } = renderList(List);
    await screen.findByText(`Showing 100 of 101 ${resource}`);
    await filterToOlderCustomer();
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    await screen.findByText(`Showing 1 of 101 ${resource}`);
    await userEvent.click(screen.getByRole("button", { name: "Actions" }));
    await userEvent.click(screen.getByRole("menuitem", { name: resource === "invoices" ? "Delete draft" : "Delete quote" }));
    expect(screen.getByRole("alertdialog")).toHaveTextContent(`${prefix}-000001`);
    workspaceId.mockReturnValue("ws-2");
    state.rows = [{ ...document(1, "NEW"), workspace_id: "ws-2" }];
    rerender(<QueryClientProvider client={client}><List /></QueryClientProvider>);
    await screen.findByText("NEW-000001");
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(screen.queryByText(`${prefix}-000001`)).not.toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Customer" })).toHaveValue("");
    expect(screen.getByRole("combobox", { name: "Status" })).toHaveTextContent("All statuses");
    expect(screen.getByText("1 / 1")).toBeInTheDocument();
    expect(Object.fromEntries(state.requests.at(-1)!)).toEqual({ page: "1", page_size: "100" });
    expect(state.deleted).toEqual([]);
  });

  it("reports a later-page error without inventing zero totals, then retries the same page", async () => {
    const state = serveDocuments(resource, prefix, 101);
    renderList(List);
    await screen.findByText(`Showing 100 of 101 ${resource}`);
    state.failList = true;
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    await screen.findByRole("button", { name: /try again/i });
    expect(screen.queryByText(/Showing/)).not.toBeInTheDocument();
    expect(screen.queryByText(`No ${resource} yet`)).not.toBeInTheDocument();
    state.failList = false;
    await userEvent.click(screen.getByRole("button", { name: /try again/i }));
    await screen.findByText(`Showing 1 of 101 ${resource}`);
    expect(screen.getByText("2 / 2")).toBeInTheDocument();
  });
});
