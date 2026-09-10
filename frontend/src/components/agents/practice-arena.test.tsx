import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { toast } from "sonner";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PracticeArena } from "@/components/agents/practice-arena";
import { RehearsalChat } from "@/components/agents/rehearsal-chat";
import { agentsApi } from "@/lib/api/agents";
import { roleplayApi } from "@/lib/api/roleplay";
import type { RehearsalRun } from "@/types/roleplay";

vi.mock("@/hooks/useWorkspaceId", () => ({ useWorkspaceId: () => "workspace" }));
vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams("workspace=workspace&runId=saved-run"),
}));
vi.mock("@/lib/api/agents", () => ({ agentsApi: { list: vi.fn() } }));
vi.mock("@/lib/api/roleplay", async (original) => ({
  ...(await original<typeof import("@/lib/api/roleplay")>()),
  roleplayApi: {
    listRuns: vi.fn(),
    getRun: vi.fn(),
    createRun: vi.fn(),
    listPersonas: vi.fn(),
    advanceTurn: vi.fn(),
    scoreRun: vi.fn(),
    retryRun: vi.fn(),
  },
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() } }));

const run: RehearsalRun = {
  id: "saved-run",
  workspace_id: "workspace",
  agent_id: "agent",
  persona_id: "persona",
  agent_name: "Test rep",
  persona_name: "Test prospect",
  rehearsee: "ai",
  channel: "sms",
  status: "pending",
  pending_action: "agent",
  attempt_count: 1,
  retryable: false,
  overall_score: null,
  objection_coverage: null,
  tone_score: null,
  booking_attempted: null,
  max_turns: 1,
  transcript: [{ role: "prospect", content: "Hello" }],
  scores: {},
  strengths: [],
  gaps: [],
  suggestions: [],
  summary: null,
  error: null,
  created_at: "2026-09-10T12:00:00Z",
  updated_at: "2026-09-10T12:00:00Z",
  completed_at: null,
};

function renderArena() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <PracticeArena />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(agentsApi.list).mockResolvedValue({
    items: [],
    total: 0,
    page: 1,
    page_size: 50,
    pages: 0,
  });
  vi.mocked(roleplayApi.listPersonas).mockResolvedValue([]);
  vi.mocked(roleplayApi.listRuns).mockResolvedValue([run]);
  vi.mocked(roleplayApi.getRun).mockResolvedValue(run);
});

describe("rehearsal recovery", () => {
  it("reopens a durable identity after reload and polls to a legitimate zero report", async () => {
    vi.mocked(roleplayApi.getRun)
      .mockResolvedValueOnce(run)
      .mockResolvedValue({
        ...run,
        status: "completed",
        pending_action: null,
        overall_score: 0,
        summary: "Genuine zero result",
        completed_at: "2026-09-10T12:01:00Z",
      });
    renderArena();
    expect(await screen.findByText("Rehearsal in progress…")).toBeInTheDocument();
    expect(
      await screen.findByText("Genuine zero result", {}, { timeout: 4000 }),
    ).toBeInTheDocument();
    expect(roleplayApi.createRun).not.toHaveBeenCalled();
    expect(roleplayApi.getRun).toHaveBeenCalledWith("workspace", run.id);
    expect(toast.success).not.toHaveBeenCalled();
  });

  it("shows failures as unscored, keeps saved dialogue, and retries only the observed attempt", async () => {
    vi.mocked(roleplayApi.getRun).mockResolvedValue({
      ...run,
      status: "failed",
      retryable: true,
      pending_action: "score",
      attempt_count: 3,
      error: "Scorer rejected the request. Saved dialogue remains.",
    });
    vi.mocked(roleplayApi.retryRun).mockResolvedValue({ ...run, pending_action: "score" });
    renderArena();
    expect(await screen.findByText("Rehearsal failed — unscored")).toBeInTheDocument();
    expect(screen.getByText("Hello")).toBeInTheDocument();
    expect(screen.queryByText(/\/100/)).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Retry failed step" }));
    expect(roleplayApi.retryRun).toHaveBeenCalledWith("workspace", run.id, 3);
    expect(toast.success).not.toHaveBeenCalled();
  });

  it("does not announce scoring success or allow another turn while scoring is queued", async () => {
    const human = {
      ...run,
      rehearsee: "human",
      status: "running",
      pending_action: null,
      transcript: [...run.transcript, { role: "agent" as const, content: "Hi there" }],
    };
    vi.mocked(roleplayApi.scoreRun).mockResolvedValue({
      ...human,
      status: "pending",
      pending_action: "score",
    });
    const client = new QueryClient();
    const onScored = vi.fn();
    render(
      <QueryClientProvider client={client}>
        <RehearsalChat workspaceId="workspace" run={human} onUpdate={vi.fn()} onScored={onScored} />
      </QueryClientProvider>,
    );
    await userEvent.click(screen.getByRole("button", { name: /Finish.*score/ }));
    expect(await screen.findByRole("button", { name: /Send/ })).toBeDisabled();
    expect(toast.success).not.toHaveBeenCalled();
    expect(onScored).toHaveBeenCalledWith(expect.objectContaining({ status: "pending" }));
  });
});
