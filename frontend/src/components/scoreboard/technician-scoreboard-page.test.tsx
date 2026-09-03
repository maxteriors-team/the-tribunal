import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TechnicianScoreboardPage } from "@/components/scoreboard/technician-scoreboard-page";
import type {
  TechnicianScoreboard,
  TechnicianScoreboardDetail,
} from "@/lib/api/technician-scoreboard";
import { queryKeys } from "@/lib/query-keys";

const { getMock, detailMock, acknowledgeMock, workspaceIdMock, canMock } = vi.hoisted(() => ({
  getMock: vi.fn(),
  detailMock: vi.fn(),
  acknowledgeMock: vi.fn(),
  workspaceIdMock: vi.fn(),
  canMock: vi.fn(),
}));

vi.mock("@/lib/api/technician-scoreboard", () => ({
  technicianScoreboardApi: {
    get: getMock,
    detail: detailMock,
    acknowledgeLevel: acknowledgeMock,
  },
}));

vi.mock("@/hooks/useWorkspaceId", () => ({
  useWorkspaceId: () => workspaceIdMock(),
}));

vi.mock("@/hooks/useCapabilities", () => ({
  useCapabilities: () => ({ can: canMock }),
}));

const LEVEL_TITLES = [
  "Spark Starter",
  "Glow Getter",
  "Beam Builder",
  "Lumen Leader",
  "Circuit Champion",
  "Radiance Ranger",
  "Illumination Ace",
  "Master of Lumens",
  "Light Commander",
  "Lighting Lord",
] as const;
const LEVEL_THRESHOLDS = [0, 500, 1_250, 2_250, 3_500, 5_000, 7_000, 9_500, 12_500, 16_000];

function detail(overrides: Partial<TechnicianScoreboardDetail> = {}): TechnicianScoreboardDetail {
  return {
    technician_id: "11111111-1111-4111-8111-111111111111",
    name: "Alex Electrician",
    lifetime_xp: 600,
    monthly_xp: 350,
    level_number: 2,
    level_title: "Glow Getter",
    current_level_threshold: 500,
    next_level_number: 3,
    next_level_title: "Beam Builder",
    next_level_threshold: 1_250,
    xp_into_level: 100,
    xp_to_next_level: 650,
    level_progress: 100 / 750,
    attendance_days: 2,
    completed_jobs: 2,
    approved_upsells: 1,
    attendance_xp: 50,
    job_xp: 200,
    upsell_xp: 100,
    ...overrides,
  };
}

function scoreboard(overrides: Partial<TechnicianScoreboard> = {}): TechnicianScoreboard {
  return {
    period: {
      start_date: "2026-09-01",
      end_date: "2026-09-30",
      starts_at: "2026-09-01T04:00:00Z",
      ends_at: "2026-10-01T04:00:00Z",
      timezone: "America/New_York",
    },
    rules: {
      attendance_day_xp: 25,
      completed_job_xp: 100,
      upsell_base_xp: 100,
      upsell_value_divisor: 20,
      upsell_value_bonus_cap: 100,
      upsell_max_xp: 200,
    },
    levels: LEVEL_TITLES.map((title, index) => ({
      number: index + 1,
      title,
      lifetime_xp: LEVEL_THRESHOLDS[index],
    })),
    standings: [
      {
        technician_id: "11111111-1111-4111-8111-111111111111",
        name: "Alex Electrician",
        rank: 1,
        monthly_xp: 350,
        level_number: 2,
        level_title: "Glow Getter",
        is_viewer: true,
      },
      {
        technician_id: "22222222-2222-4222-8222-222222222222",
        name: "Bailey Bright",
        rank: 1,
        monthly_xp: 350,
        level_number: 1,
        level_title: "Spark Starter",
        is_viewer: false,
      },
      {
        technician_id: "33333333-3333-4333-8333-333333333333",
        name: "Charlie Current",
        rank: null,
        monthly_xp: 0,
        level_number: 1,
        level_title: "Spark Starter",
        is_viewer: false,
      },
    ],
    viewer_detail: detail(),
    viewer_level_seen: 1,
    ...overrides,
  };
}

function renderPage() {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0 },
      mutations: { retry: false },
    },
  });
  const view = render(
    <QueryClientProvider client={client}>
      <TechnicianScoreboardPage />
    </QueryClientProvider>,
  );
  return { ...view, client };
}

describe("TechnicianScoreboardPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    workspaceIdMock.mockReturnValue("workspace-1");
    canMock.mockImplementation((capability: string) => capability === "jobs:read");
    getMock.mockResolvedValue(scoreboard());
    detailMock.mockResolvedValue(detail());
    acknowledgeMock.mockResolvedValue({ level_seen: 2 });
  });

  it("shows private viewer progress, all levels, ties, zero-XP rows, and exact rules", async () => {
    renderPage();

    expect(await screen.findByRole("heading", { name: "Lighting League" })).toBeVisible();
    expect(await screen.findByText("600 lifetime XP")).toBeVisible();
    expect(screen.getByText("650 XP to Beam Builder")).toBeVisible();

    const levels = screen.getByRole("list", { name: "Lighting League levels" });
    expect(within(levels).getAllByRole("listitem")).toHaveLength(10);
    expect(within(levels).getByText("Lighting Lord")).toBeVisible();

    const standings = screen.getByRole("list", { name: "September 2026 technician standings" });
    expect(within(standings).getAllByText("Tied #1")).toHaveLength(2);
    expect(within(standings).getByText("Not ranked")).toBeVisible();
    expect(within(standings).queryByRole("button")).not.toBeInTheDocument();
    expect(detailMock).not.toHaveBeenCalled();

    expect(
      screen.getByText(/Every technician assigned at that moment receives full credit/),
    ).toBeVisible();
    expect(screen.getByText(/Standings reset monthly/)).toBeVisible();
    expect(
      screen.getByText(/does not set pay, prizes, discipline, or performance reviews/),
    ).toBeVisible();
    expect(document.querySelector('[data-slot="progress-indicator"]')).toHaveClass(
      "motion-reduce:transition-none",
    );
  });

  it("opens manager-only details by keyboard, retries safely, and returns focus", async () => {
    const user = userEvent.setup();
    canMock.mockReturnValue(true);
    detailMock.mockRejectedValueOnce(new Error("temporary")).mockResolvedValue(
      detail({
        technician_id: "22222222-2222-4222-8222-222222222222",
        name: "Bailey Bright",
        lifetime_xp: 725,
      }),
    );
    renderPage();

    const trigger = await screen.findByRole("button", {
      name: "View private Lighting League details for Bailey Bright",
    });
    trigger.focus();
    await user.keyboard("{Enter}");

    expect(await screen.findByRole("heading", { name: "Technician details" })).toBeVisible();
    expect(await screen.findByText("Details unavailable")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("725 lifetime XP")).toBeVisible();

    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(trigger).toHaveFocus();
  });

  it("announces pending and successful level acknowledgement without auto-dismissing", async () => {
    const user = userEvent.setup();
    let resolveAcknowledgement!: (value: { level_seen: number }) => void;
    acknowledgeMock.mockReturnValue(
      new Promise((resolve) => {
        resolveAcknowledgement = resolve;
      }),
    );
    renderPage();

    expect(
      await screen.findByRole("heading", { name: "Level 2 unlocked: Glow Getter" }),
    ).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Dismiss level-up message" }));
    expect(screen.getByRole("button", { name: "Dismissing level-up message" })).toBeDisabled();
    expect(screen.getByText("Dismissing level-up message.")).toHaveAttribute("role", "status");

    await act(async () => resolveAcknowledgement({ level_seen: 2 }));
    await waitFor(() =>
      expect(
        screen.queryByRole("heading", { name: "Level 2 unlocked: Glow Getter" }),
      ).not.toBeInTheDocument(),
    );
    expect(screen.getByText("Level-up message dismissed.")).toHaveAttribute("aria-live", "polite");
  });

  it("keeps a failed level acknowledgement visible and offers retry", async () => {
    const user = userEvent.setup();
    acknowledgeMock
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValue({ level_seen: 2 });
    renderPage();

    await user.click(await screen.findByRole("button", { name: "Dismiss level-up message" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "We could not dismiss this yet. Your level and XP are unchanged.",
    );
    await user.click(screen.getByRole("button", { name: "Try dismissing level-up message again" }));
    await waitFor(() =>
      expect(
        screen.queryByRole("heading", { name: "Level 2 unlocked: Glow Getter" }),
      ).not.toBeInTheDocument(),
    );
    expect(acknowledgeMock).toHaveBeenCalledTimes(2);
  });

  it("shows honest zero-XP guidance while preserving the active roster", async () => {
    const zeroDetail = detail({
      lifetime_xp: 0,
      monthly_xp: 0,
      level_number: 1,
      level_title: "Spark Starter",
      current_level_threshold: 0,
      next_level_number: 2,
      next_level_title: "Glow Getter",
      next_level_threshold: 500,
      xp_into_level: 0,
      xp_to_next_level: 500,
      level_progress: 0,
      attendance_days: 0,
      completed_jobs: 0,
      approved_upsells: 0,
      attendance_xp: 0,
      job_xp: 0,
      upsell_xp: 0,
    });
    getMock.mockResolvedValue(
      scoreboard({
        viewer_detail: zeroDetail,
        viewer_level_seen: 1,
        standings: scoreboard().standings.map((row) => ({ ...row, rank: null, monthly_xp: 0 })),
      }),
    );
    renderPage();

    expect(await screen.findByText(/No XP earned this month yet/)).toBeVisible();
    expect(screen.getByText("Charlie Current")).toBeVisible();
  });

  it("gives office users a Team setup path when no active technicians exist", async () => {
    canMock.mockReturnValue(true);
    getMock.mockResolvedValue(
      scoreboard({ standings: [], viewer_detail: null, viewer_level_seen: null }),
    );
    renderPage();

    const link = await screen.findByRole("link", { name: "Open Team settings" });
    expect(link).toHaveAttribute("href", "/settings?tab=team");
  });

  it("recovers initial and background failures without blanking stale standings", async () => {
    getMock.mockRejectedValueOnce(new Error("offline"));
    const first = renderPage();
    expect(await screen.findByText("Lighting League unavailable")).toBeVisible();
    getMock.mockResolvedValueOnce(scoreboard());
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("Bailey Bright")).toBeVisible();
    first.unmount();

    getMock.mockResolvedValueOnce(scoreboard());
    const { client } = renderPage();
    expect(await screen.findByText("Bailey Bright")).toBeVisible();
    getMock.mockRejectedValueOnce(new Error("background failure"));
    await client.refetchQueries({ queryKey: queryKeys.technicianScoreboard.all("workspace-1") });
    expect(await screen.findByText(/last loaded results remain visible/)).toBeVisible();
    expect(screen.getByText("Bailey Bright")).toBeVisible();
  });

  it("fails closed without job-read access", () => {
    canMock.mockReturnValue(false);
    renderPage();

    expect(screen.getByText("Access denied")).toBeVisible();
    expect(getMock).not.toHaveBeenCalled();
  });
});
