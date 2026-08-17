import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  knowledgeHook,
  summaryMutate,
  factMutate,
  summaryMutationHook,
  factMutationHook,
  toastSuccess,
  toastError,
} = vi.hoisted(() => ({
  knowledgeHook: vi.fn(),
  summaryMutate: vi.fn(),
  factMutate: vi.fn(),
  summaryMutationHook: vi.fn(),
  factMutationHook: vi.fn(),
  toastSuccess: vi.fn(),
  toastError: vi.fn(),
}));

vi.mock("@/hooks/useContacts", () => ({
  useContactAIKnowledge: knowledgeHook,
  useUpdateContactAIMemorySummary: summaryMutationHook,
  useUpdateContactAIMemoryFact: factMutationHook,
}));

vi.mock("sonner", () => ({
  toast: {
    success: toastSuccess,
    error: toastError,
  },
}));

import { ContactAIKnowledge } from "@/components/contacts/contact-detail/contact-ai-knowledge";
import type { ContactAIKnowledgeResponse } from "@/lib/api/contacts";

const WORKSPACE_ID = "6aee02cf-5ea9-49bd-88bb-d6cb720579a3";
const FACT_ID = "bc155b11-ccfe-4a69-a6f7-2f5604beefa9";

const knowledge: ContactAIKnowledgeResponse = {
  contact_id: 42,
  generated_at: "2026-08-17T12:00:00Z",
  structured_facts: [
    {
      key: "contact_status",
      label: "Contact status",
      value: "Qualified",
      source: "CRM contact record",
      observed_at: "2026-08-17T11:00:00Z",
    },
  ],
  next_action: {
    value: "Prepare for upcoming gutter cleaning appointment",
    due_at: "2026-08-19T14:00:00Z",
    source: "CRM appointment",
    observed_at: "2026-08-17T11:00:00Z",
  },
  memory_summary: {
    value: "Interested in a fall maintenance plan.",
    source: "AI from SMS",
    observed_at: "2026-08-16T12:00:00Z",
    expires_at: null,
  },
  memory_facts: [
    {
      id: FACT_ID,
      fact_type: "service_interest",
      label: "Service interest",
      value: "Roof cleaning",
      confidence: 0.82,
      source: "AI from SMS",
      observed_at: "2026-08-16T12:00:00Z",
      expires_at: "2026-09-16T12:00:00Z",
    },
  ],
  conflicts: [
    {
      fact_id: FACT_ID,
      label: "Contact status",
      generated_value: "New",
      authoritative_value: "Qualified",
      message: "CRM is current and takes priority over generated memory.",
    },
  ],
};

function mockLoaded(data: ContactAIKnowledgeResponse = knowledge) {
  knowledgeHook.mockReturnValue({
    data,
    isLoading: false,
    isError: false,
    refetch: vi.fn(),
  });
}

describe("ContactAIKnowledge", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    summaryMutate.mockResolvedValue(knowledge);
    factMutate.mockResolvedValue(knowledge);
    summaryMutationHook.mockReturnValue({ mutateAsync: summaryMutate, isPending: false });
    factMutationHook.mockReturnValue({ mutateAsync: factMutate, isPending: false });
  });

  it("shows structured context, next action, provenance, freshness, and conflicts", () => {
    mockLoaded();

    render(<ContactAIKnowledge workspaceId={WORKSPACE_ID} contactId={42} canEditMemory={true} />);

    expect(screen.getByRole("heading", { name: "What AI knows" })).toBeInTheDocument();
    expect(screen.getByText("CRM facts are read-only")).toBeInTheDocument();
    expect(screen.getAllByText("Qualified")).toHaveLength(2);
    expect(
      screen.getByText("Prepare for upcoming gutter cleaning appointment"),
    ).toBeInTheDocument();
    expect(screen.getByText("Interested in a fall maintenance plan.")).toBeInTheDocument();
    expect(screen.getByText("Roof cleaning")).toBeInTheDocument();
    expect(screen.getAllByText("AI from SMS")).toHaveLength(2);
    expect(screen.getByRole("heading", { name: "Conflicts need review" })).toBeInTheDocument();
    expect(screen.getByText("Generated memory", { selector: "dt" })).toBeInTheDocument();
  });

  it("labels and focuses the correction dialog, then updates only the generated fact", async () => {
    mockLoaded();
    const user = userEvent.setup();

    render(<ContactAIKnowledge workspaceId={WORKSPACE_ID} contactId={42} canEditMemory={true} />);

    const trigger = screen.getByRole("button", {
      name: "Correct generated memory: Service interest",
    });
    trigger.focus();
    await user.keyboard("{Enter}");

    const textarea = screen.getByLabelText("Corrected memory");
    await waitFor(() => expect(textarea).toHaveFocus());
    await user.clear(textarea);
    await user.type(textarea, "Gutter cleaning");
    const saveButton = screen.getByRole("button", { name: "Save correction" });
    saveButton.focus();
    await user.keyboard("{Enter}");

    await waitFor(() =>
      expect(factMutate).toHaveBeenCalledWith({
        factId: FACT_ID,
        value: "Gutter cleaning",
      }),
    );
    expect(summaryMutate).not.toHaveBeenCalled();
    expect(toastSuccess).toHaveBeenCalledWith("AI memory corrected");
    await waitFor(() => expect(trigger).toHaveFocus());
  });

  it("confirms removal and sends null without exposing edits to read-only operators", async () => {
    mockLoaded();
    const user = userEvent.setup();
    const { rerender } = render(
      <ContactAIKnowledge workspaceId={WORKSPACE_ID} contactId={42} canEditMemory={true} />,
    );

    await user.click(
      screen.getByRole("button", { name: "Remove generated memory: Service interest" }),
    );
    expect(screen.getByText(/authoritative CRM records stay unchanged/i)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Remove generated memory" }));

    await waitFor(() => expect(factMutate).toHaveBeenCalledWith({ factId: FACT_ID, value: null }));

    rerender(
      <ContactAIKnowledge workspaceId={WORKSPACE_ID} contactId={42} canEditMemory={false} />,
    );
    expect(
      screen.queryByRole("button", { name: /correct generated memory/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /remove generated memory:/i }),
    ).not.toBeInTheDocument();
  });

  it("uses shared page states for loading, error retry, and empty memory", async () => {
    const user = userEvent.setup();
    const refetch = vi.fn();
    knowledgeHook.mockReturnValue({
      data: undefined,
      isLoading: true,
      isError: false,
      refetch,
    });
    const { rerender } = render(
      <ContactAIKnowledge workspaceId={WORKSPACE_ID} contactId={42} canEditMemory={true} />,
    );
    expect(screen.getByText("Loading AI knowledge")).toBeInTheDocument();

    knowledgeHook.mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: true,
      refetch,
    });
    rerender(<ContactAIKnowledge workspaceId={WORKSPACE_ID} contactId={42} canEditMemory={true} />);
    await user.click(screen.getByRole("button", { name: "Retry" }));
    expect(refetch).toHaveBeenCalledTimes(1);

    mockLoaded({
      ...knowledge,
      structured_facts: [],
      next_action: null,
      memory_summary: null,
      memory_facts: [],
      conflicts: [],
    });
    rerender(<ContactAIKnowledge workspaceId={WORKSPACE_ID} contactId={42} canEditMemory={true} />);
    expect(screen.getByText("No structured facts yet")).toBeInTheDocument();
    expect(screen.getByText("No next action")).toBeInTheDocument();
    expect(screen.getByText("No generated memory yet")).toBeInTheDocument();
  });
});
