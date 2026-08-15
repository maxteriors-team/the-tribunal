import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { OpportunityFollowups } from "@/components/opportunities/opportunity-followups";
import type { OpportunityTask } from "@/types";

/**
 * The point of this panel is *whose* record the follow-up lands on. A contact
 * can have several jobs running at once, so every write here has to carry the
 * opportunity id — a note filed against the contact instead is indistinguishable
 * from a note about a different job.
 */
const { addNoteMock, createTaskMock, updateTaskMock } = vi.hoisted(() => ({
  addNoteMock: vi.fn(),
  createTaskMock: vi.fn(),
  updateTaskMock: vi.fn(),
}));

vi.mock("@/lib/api/opportunities", () => ({
  opportunitiesApi: {
    addNote: addNoteMock,
    createTask: createTaskMock,
    updateTask: updateTaskMock,
  },
}));

vi.mock("@/components/workspaces/team-member-picker", () => ({
  TeamMemberPicker: ({
    value,
    onValueChange,
    label,
  }: {
    value: number | null;
    onValueChange: (value: number | null) => void;
    label?: string;
  }) => (
    <select
      aria-label={label ?? "Team member"}
      value={value ?? ""}
      onChange={(event) =>
        onValueChange(event.target.value ? Number(event.target.value) : null)
      }
    >
      <option value="">Unassigned</option>
      <option value="22">Jordan Lee</option>
    </select>
  ),
}));

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

function makeTask(overrides: Partial<OpportunityTask> = {}): OpportunityTask {
  return {
    id: "task-1",
    opportunity_id: "opp-1",
    title: "Send the quote",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

function renderPanel(tasks: OpportunityTask[] = []) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  render(
    <QueryClientProvider client={client}>
      <OpportunityFollowups workspaceId="ws-1" opportunityId="opp-1" tasks={tasks} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  addNoteMock.mockResolvedValue({ id: "act-1" });
  createTaskMock.mockResolvedValue(makeTask());
  updateTaskMock.mockResolvedValue(makeTask({ completed_at: "2026-01-02T00:00:00Z" }));
});

describe("OpportunityFollowups notes", () => {
  it("files a note against the opportunity", async () => {
    const user = userEvent.setup();
    renderPanel();

    await user.type(screen.getByLabelText("Note about this deal"), "Left voicemail");
    await user.click(screen.getByRole("button", { name: "Add" }));

    await waitFor(() => expect(addNoteMock).toHaveBeenCalled());
    expect(addNoteMock).toHaveBeenCalledWith("ws-1", "opp-1", {
      body: "Left voicemail",
      kind: "note",
    });
  });

  it("can post the same text as a status update instead", async () => {
    const user = userEvent.setup();
    renderPanel();

    await user.type(screen.getByLabelText("Note about this deal"), "Roof measured");
    await user.click(screen.getByRole("button", { name: "Update" }));
    await user.click(screen.getByRole("button", { name: "Add" }));

    await waitFor(() => expect(addNoteMock).toHaveBeenCalled());
    expect(addNoteMock.mock.calls[0][2]).toMatchObject({ kind: "update" });
  });

  it("will not submit an empty or whitespace-only note", async () => {
    const user = userEvent.setup();
    renderPanel();

    expect(screen.getByRole("button", { name: "Add" })).toBeDisabled();
    await user.type(screen.getByLabelText("Note about this deal"), "   ");
    expect(screen.getByRole("button", { name: "Add" })).toBeDisabled();
    expect(addNoteMock).not.toHaveBeenCalled();
  });

  it("clears the box after saving so the note is not posted twice", async () => {
    const user = userEvent.setup();
    renderPanel();

    const box = screen.getByLabelText("Note about this deal");
    await user.type(box, "Left voicemail");
    await user.click(screen.getByRole("button", { name: "Add" }));

    await waitFor(() => expect(box).toHaveValue(""));
  });
});

describe("OpportunityFollowups tasks", () => {
  it("creates a task on the opportunity", async () => {
    const user = userEvent.setup();
    renderPanel();

    await user.click(screen.getByRole("tab", { name: "Task" }));
    await user.type(screen.getByLabelText("Task title"), "Call Lisa back");
    await user.click(screen.getByRole("button", { name: "Add task" }));

    await waitFor(() => expect(createTaskMock).toHaveBeenCalled());
    expect(createTaskMock).toHaveBeenCalledWith("ws-1", "opp-1", {
      title: "Call Lisa back",
      due_at: null,
      assigned_user_id: null,
    });
  });

  it("tags a user on a scheduled task", async () => {
    const user = userEvent.setup();
    renderPanel();

    await user.click(screen.getByRole("tab", { name: "Task" }));
    await user.type(screen.getByLabelText("Task title"), "Call Lisa back");
    await user.selectOptions(screen.getByLabelText("Tag a user"), "22");
    await user.click(screen.getByRole("button", { name: "Add task" }));

    await waitFor(() =>
      expect(createTaskMock).toHaveBeenCalledWith("ws-1", "opp-1", {
        title: "Call Lisa back",
        due_at: null,
        assigned_user_id: 22,
      }),
    );
  });

  it("sends the chosen due date", async () => {
    const user = userEvent.setup();
    renderPanel();

    await user.click(screen.getByRole("tab", { name: "Task" }));
    await user.type(screen.getByLabelText("Task title"), "Call Lisa back");
    await user.type(screen.getByLabelText("Due"), "2026-09-01");
    await user.click(screen.getByRole("button", { name: "Add task" }));

    await waitFor(() => expect(createTaskMock).toHaveBeenCalled());
    const sent = createTaskMock.mock.calls[0][2].due_at as string;
    // Midday local, so the stored instant lands on the day the operator picked
    // no matter which side of UTC the workspace sits on.
    expect(new Date(sent).toISOString()).toContain("2026-09-01");
  });

  it("lists existing tasks with their due date", () => {
    renderPanel([makeTask({ due_at: "2099-09-01T12:00:00Z" })]);

    expect(screen.getByText("Send the quote")).toBeVisible();
    expect(screen.getByText(/Due Sep 1, 2099/)).toBeVisible();
  });

  it("flags an open task past its due date as overdue", () => {
    renderPanel([makeTask({ due_at: "2020-01-01T12:00:00Z" })]);

    expect(screen.getByText(/Overdue/)).toBeVisible();
  });

  it("does not flag a completed task as overdue", () => {
    renderPanel([
      makeTask({ due_at: "2020-01-01T12:00:00Z", completed_at: "2020-02-01T00:00:00Z" }),
    ]);

    expect(screen.queryByText(/Overdue/)).toBeNull();
  });

  it("completes a task from its checkbox", async () => {
    const user = userEvent.setup();
    renderPanel([makeTask()]);

    await user.click(screen.getByRole("checkbox", { name: "Complete Send the quote" }));

    await waitFor(() => expect(updateTaskMock).toHaveBeenCalled());
    expect(updateTaskMock).toHaveBeenCalledWith("ws-1", "opp-1", "task-1", { completed: true });
  });

  it("reopens a completed task", async () => {
    const user = userEvent.setup();
    renderPanel([makeTask({ completed_at: "2026-01-02T00:00:00Z" })]);

    await user.click(screen.getByRole("checkbox", { name: "Reopen Send the quote" }));

    await waitFor(() => expect(updateTaskMock).toHaveBeenCalled());
    expect(updateTaskMock.mock.calls[0][3]).toEqual({ completed: false });
  });

  it("shows open work above anything already done", () => {
    renderPanel([
      makeTask({ id: "done", title: "Done thing", completed_at: "2026-01-02T00:00:00Z" }),
      makeTask({ id: "open", title: "Open thing" }),
    ]);

    const rendered = screen.getAllByRole("listitem").map((li) => li.textContent);
    expect(rendered[0]).toContain("Open thing");
    expect(rendered[1]).toContain("Done thing");
  });
});
