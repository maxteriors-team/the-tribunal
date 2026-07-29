import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AttachRulesSettingsTab } from "@/components/settings/attach-rules-settings-tab";
import type { AttachRulesSettings } from "@/types/sales-wizard";

const { getMock, updateMock, listCatalogMock, useWorkspaceIdMock } = vi.hoisted(
  () => ({
    getMock: vi.fn(),
    updateMock: vi.fn(),
    listCatalogMock: vi.fn(),
    useWorkspaceIdMock: vi.fn(),
  }),
);

vi.mock("@/lib/api/attach-rules", () => ({
  attachRulesApi: { get: getMock, update: updateMock },
}));

vi.mock("@/lib/api/sales-wizard", () => ({
  salesWizardApi: { listCatalog: listCatalogMock },
}));

vi.mock("@/hooks/useWorkspaceId", () => ({
  useWorkspaceId: () => useWorkspaceIdMock(),
}));

function config(overrides: Partial<AttachRulesSettings> = {}): AttachRulesSettings {
  return {
    enabled: true,
    rules: [
      {
        primary_category: "roof",
        suggested_categories: ["gutters"],
        mode: "advisory",
      },
    ],
    prompt_template: "This is a {primary} job with no add-on attached.",
    dismissal_reasons: ["Customer declined"],
    require_dismissal_reason: true,
    ...overrides,
  };
}

function renderTab() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <AttachRulesSettingsTab />
    </QueryClientProvider>,
  );
}

describe("AttachRulesSettingsTab", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useWorkspaceIdMock.mockReturnValue("ws-1");
    getMock.mockResolvedValue(config());
    updateMock.mockImplementation(async (_ws: string, body: AttachRulesSettings) => body);
    listCatalogMock.mockResolvedValue([
      { id: "1", name: "Roof Replacement", unit_price: 9000, service_category: "roof" },
      { id: "2", name: "Gutter Guard", unit_price: 1200, service_category: "gutters" },
      { id: "3", name: "Trim Wrap", unit_price: 800, service_category: "trim" },
      { id: "4", name: "Hand-typed", unit_price: 100, service_category: null },
    ]);
  });

  it("reads each rule back as the sentence the operator wrote", async () => {
    renderTab();

    expect(
      await screen.findByText(/job should also quote/i),
    ).toBeInTheDocument();
    expect(screen.getByDisplayValue("roof")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /gutters/i }),
    ).toBeInTheDocument();
  });

  it("spells out what each enforcement mode does to a rep", async () => {
    renderTab();

    await screen.findByLabelText(/enforcement/i);
    // Blocking is the one expensive choice on this page; it must never be
    // picked without the consequence being stated.
    expect(
      screen.getByText(/the quote still saves/i),
    ).toBeInTheDocument();
  });

  it("offers suggestions from the workspace price book only", async () => {
    const user = userEvent.setup();
    renderTab();

    await user.click(await screen.findByLabelText(/prompt to add/i));

    const menu = await screen.findByRole("menu");
    expect(within(menu).getByRole("menuitemcheckbox", { name: "trim" })).toBeInTheDocument();
    expect(within(menu).getByRole("menuitemcheckbox", { name: "gutters" })).toBeInTheDocument();
    // The uncategorised item contributes no category.
    expect(within(menu).queryByRole("menuitemcheckbox", { name: "" })).toBeNull();
  });

  it("saves the edited rule set", async () => {
    const user = userEvent.setup();
    renderTab();

    await user.click(await screen.findByLabelText(/prompt to add/i));
    await user.click(
      await screen.findByRole("menuitemcheckbox", { name: "trim" }),
    );
    await user.keyboard("{Escape}");
    await user.click(screen.getByRole("button", { name: /save attach rules/i }));

    await waitFor(() => expect(updateMock).toHaveBeenCalled());
    const [, body] = updateMock.mock.calls[0];
    expect(body.rules[0].suggested_categories).toEqual(["gutters", "trim"]);
  });

  it("drops a rule with no job type rather than saving a rule that cannot fire", async () => {
    const user = userEvent.setup();
    renderTab();

    await user.click(await screen.findByRole("button", { name: /add a rule/i }));
    await user.click(screen.getByRole("button", { name: /save attach rules/i }));

    await waitFor(() => expect(updateMock).toHaveBeenCalled());
    const [, body] = updateMock.mock.calls[0];
    expect(body.rules).toHaveLength(1);
  });

  it("refuses to require a reason with no reasons to choose from", async () => {
    const user = userEvent.setup();
    getMock.mockResolvedValue(config({ dismissal_reasons: [] }));
    renderTab();

    await user.click(
      await screen.findByRole("button", { name: /save attach rules/i }),
    );

    await waitFor(() => expect(updateMock).not.toHaveBeenCalled());
  });

  it("warns that rules do nothing while the master switch is off", async () => {
    const user = userEvent.setup();
    renderTab();

    await user.click(
      await screen.findByLabelText(/prompt for attachable services/i),
    );

    expect(
      screen.getByText(/attach prompts are switched off/i),
    ).toBeInTheDocument();
  });
});
