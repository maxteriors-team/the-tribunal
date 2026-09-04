import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CatalogItemDialog } from "@/components/catalog/catalog-item-dialog";
import { queryKeys } from "@/lib/query-keys";
import { selectOption } from "@/test/select-option";
import type { CatalogItem } from "@/types";

/**
 * The service-category / attach fields are what makes attach-rate reporting
 * possible, so this suite pins the mapping between the form and the payload:
 * the category select is free-form (a workspace's own trade round-trips through
 * "Custom"), and attach targets only ride along while the item is attachable.
 */

const { createMock, updateMock } = vi.hoisted(() => ({
  createMock: vi.fn(),
  updateMock: vi.fn(),
}));

vi.mock("@/lib/api/catalog", () => ({
  catalogApi: { create: createMock, update: updateMock },
}));

vi.mock("@/hooks/useWorkspaceId", () => ({
  useWorkspaceId: () => "ws-1",
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

function makeItem(overrides: Partial<CatalogItem> = {}): CatalogItem {
  return {
    id: "item-1",
    workspace_id: "ws-1",
    name: "Gutter guard",
    description: null,
    sku: null,
    kind: "service",
    unit_price: 12,
    taxable: true,
    is_active: true,
    service_category: "gutters",
    is_attachable: true,
    attach_targets: ["roof"],
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

function renderDialog(item?: CatalogItem) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  render(
    <QueryClientProvider client={client}>
      <CatalogItemDialog open onOpenChange={vi.fn()} item={item} />
    </QueryClientProvider>,
  );
  return client;
}

beforeEach(() => {
  vi.clearAllMocks();
  createMock.mockResolvedValue(makeItem());
  updateMock.mockResolvedValue(makeItem());
});

describe("CatalogItemDialog", () => {
  it("sends the category and attach targets picked for a new item", async () => {
    const user = userEvent.setup();
    renderDialog();

    await user.type(screen.getByLabelText("Name"), "Gutter guard");

    await selectOption(screen.getByRole("combobox", { name: "Service category" }), "Gutters");

    // Targets stay hidden until the item is marked attachable.
    expect(screen.queryByText("Attaches to")).not.toBeInTheDocument();
    await user.click(screen.getByRole("switch", { name: "Can be attached to other jobs" }));
    await user.click(screen.getByRole("checkbox", { name: "Roof" }));

    await user.click(screen.getByRole("button", { name: "Add item" }));

    await waitFor(() => expect(createMock).toHaveBeenCalledTimes(1));
    expect(createMock.mock.calls[0][1]).toMatchObject({
      name: "Gutter guard",
      service_category: "gutters",
      is_attachable: true,
      attach_targets: ["roof"],
    });
  });

  it("keeps a workspace's own category and clears targets when unattached", async () => {
    const user = userEvent.setup();
    renderDialog(makeItem({ service_category: "holiday-lighting", attach_targets: ["trim"] }));

    // A category outside the shared defaults reopens as free text, not dropped.
    expect(screen.getByLabelText("Category name")).toHaveValue("holiday-lighting");
    expect(screen.getByRole("checkbox", { name: "Trim" })).toBeChecked();

    await user.click(screen.getByRole("switch", { name: "Can be attached to other jobs" }));
    await user.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(updateMock).toHaveBeenCalledTimes(1));
    expect(updateMock.mock.calls[0][2]).toMatchObject({
      service_category: "holiday-lighting",
      is_attachable: false,
      attach_targets: [],
    });
  });

  it("uncategorizes an item with an explicit null", async () => {
    const user = userEvent.setup();
    renderDialog(makeItem());

    await selectOption(screen.getByRole("combobox", { name: "Service category" }), "Uncategorized");
    await user.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(updateMock).toHaveBeenCalledTimes(1));
    expect(updateMock.mock.calls[0][2]).toMatchObject({
      service_category: null,
    });
  });

  it("invalidates the landscape designer catalog after saving a price-book item", async () => {
    const user = userEvent.setup();
    const client = renderDialog(makeItem());
    const designerCatalogKey = queryKeys.salesWizard.catalog("ws-1");
    client.setQueryDefaults(designerCatalogKey, { gcTime: Infinity });
    client.setQueryData(designerCatalogKey, [makeItem()]);
    expect(client.getQueryState(designerCatalogKey)?.isInvalidated).toBe(false);

    await user.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(updateMock).toHaveBeenCalledTimes(1));
    await waitFor(() =>
      expect(client.getQueryState(designerCatalogKey)?.isInvalidated).toBe(true),
    );
  });
});
