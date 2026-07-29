import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AttachPrompt } from "@/components/sales-wizard/attach-prompt";
import type { AttachWarning } from "@/types/sales-wizard";

const { listMock, useWorkspaceIdMock } = vi.hoisted(() => ({
  listMock: vi.fn(),
  useWorkspaceIdMock: vi.fn(),
}));

vi.mock("@/lib/api/catalog", () => ({
  catalogApi: { list: listMock },
}));

vi.mock("@/hooks/useWorkspaceId", () => ({
  useWorkspaceId: () => useWorkspaceIdMock(),
}));

function warning(overrides: Partial<AttachWarning> = {}): AttachWarning {
  return {
    primary_service: "roof",
    suggested_categories: ["gutters"],
    mode: "advisory",
    message: "This is a roof job with no add-on attached.",
    dismissal_reasons: ["Customer declined", "Already has"],
    require_dismissal_reason: true,
    ...overrides,
  };
}

function renderPrompt(props: Partial<Parameters<typeof AttachPrompt>[0]> = {}) {
  const onAdd = vi.fn();
  const onDismiss = vi.fn();
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <AttachPrompt
        warning={warning()}
        onAdd={onAdd}
        onDismiss={onDismiss}
        {...props}
      />
    </QueryClientProvider>,
  );
  return { onAdd, onDismiss };
}

describe("AttachPrompt", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useWorkspaceIdMock.mockReturnValue("ws-1");
    listMock.mockResolvedValue({
      items: [
        {
          id: "cat-gutters",
          name: "Gutter Guard",
          unit_price: 1200,
          service_category: "gutters",
        },
        {
          id: "cat-roof",
          name: "Roof Replacement",
          unit_price: 9000,
          service_category: "roof",
        },
      ],
      total: 2,
      page: 1,
      page_size: 200,
      pages: 1,
    });
  });

  it("leads with the action, not the complaint", () => {
    renderPrompt();

    expect(
      screen.getByRole("button", { name: /add gutters/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("This is a roof job with no add-on attached."),
    ).toBeInTheDocument();
  });

  it("says plainly that a blocking rule did not save the quote", () => {
    // A rep who believes a proposal is sent when it is not loses the job.
    renderPrompt({ warning: warning({ mode: "blocking" }) });

    expect(screen.getByRole("alert")).toHaveTextContent(/quote not saved/i);
  });

  it("keeps an advisory prompt out of the assertive live region", () => {
    renderPrompt();

    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("will not let a required reason be skipped", async () => {
    const user = userEvent.setup();
    const { onDismiss } = renderPrompt();

    const skip = screen.getByRole("button", { name: /^skip$/i });
    expect(skip).toBeDisabled();

    await user.selectOptions(
      screen.getByLabelText(/reason for skipping/i),
      "Already has",
    );

    expect(skip).toBeEnabled();
    await user.click(skip);
    expect(onDismiss).toHaveBeenCalledWith("Already has");
  });

  it("skips without a reason when the workspace does not require one", async () => {
    const user = userEvent.setup();
    const { onDismiss } = renderPrompt({
      warning: warning({ require_dismissal_reason: false }),
    });

    expect(
      screen.queryByLabelText(/reason for skipping/i),
    ).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /^skip$/i }));
    expect(onDismiss).toHaveBeenCalledWith(null);
  });

  it("offers only the suggested category's items, not the whole price book", async () => {
    const user = userEvent.setup();
    const { onAdd } = renderPrompt();

    await user.click(screen.getByRole("button", { name: /add gutters/i }));

    expect(
      await screen.findByRole("menuitem", { name: /gutter guard/i }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("menuitem", { name: /roof replacement/i }),
    ).not.toBeInTheDocument();

    await user.click(screen.getByRole("menuitem", { name: /gutter guard/i }));
    expect(onAdd).toHaveBeenCalledWith(
      expect.objectContaining({ id: "cat-gutters" }),
    );
  });

  it("names the gap when the price book has nothing in that category", async () => {
    const user = userEvent.setup();
    listMock.mockResolvedValue({
      items: [],
      total: 0,
      page: 1,
      page_size: 200,
      pages: 1,
    });
    renderPrompt();

    await user.click(screen.getByRole("button", { name: /add gutters/i }));

    expect(
      await screen.findByText(/no gutters items in your price book/i),
    ).toBeInTheDocument();
  });

  it("disables every action while a save is in flight", () => {
    renderPrompt({ busy: true, warning: warning({ require_dismissal_reason: false }) });

    expect(screen.getByRole("button", { name: /add gutters/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /^skip$/i })).toBeDisabled();
  });
});
