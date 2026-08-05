import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LiveCallsPanel } from "@/components/calls/live-calls-panel";
import type { LiveCall } from "@/lib/api/calls";
import { server } from "@/test/msw/server";

const ORIGIN = "http://localhost:3000";
const WORKSPACE_ID = "ws_1";
const CALL_ID = "call_abc123";

const { toastSuccess, toastError } = vi.hoisted(() => ({
  toastSuccess: vi.fn(),
  toastError: vi.fn(),
}));

vi.mock("@/hooks/useWorkspaceId", () => ({
  useWorkspaceId: () => "ws_1",
}));

vi.mock("sonner", () => ({
  toast: { success: toastSuccess, error: toastError },
}));

afterEach(() => {
  toastSuccess.mockReset();
  toastError.mockReset();
});

function liveCall(overrides: Partial<LiveCall> = {}): LiveCall {
  return {
    call_id: CALL_ID,
    workspace_id: WORKSPACE_ID,
    direction: "outbound",
    agent_name: "Jamie",
    contact_name: "Dana Reeves",
    contact_phone: "+15555550123",
    started_at: "2026-08-04T10:00:00.000Z",
    duration_seconds: 42,
    supervisor_count: 0,
    barged: false,
    ...overrides,
  };
}

/** Serves the live roster so the panel has a call to render. */
function mockLiveRoster(calls: LiveCall[]) {
  server.use(
    http.get(`${ORIGIN}/api/v1/workspaces/:workspaceId/calls/live`, () =>
      HttpResponse.json({ items: calls }),
    ),
  );
}

function renderPanel() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0, staleTime: 0 } },
  });
  return render(
    <QueryClientProvider client={client}>
      <LiveCallsPanel />
    </QueryClientProvider>,
  );
}

/**
 * Click a row's "End call", then confirm in the dialog.
 *
 * Hanging up is destructive and unrecoverable, so the roster button only opens
 * a confirm. The dialog's own action is also labelled "End call", so the
 * confirm is taken from within the dialog to avoid matching the row button.
 */
async function endCallAndConfirm(rowIndex = 0) {
  const rowButtons = await screen.findAllByRole("button", { name: /end call/i });
  await userEvent.click(rowButtons[rowIndex]);

  const dialog = await screen.findByRole("alertdialog");
  await userEvent.click(within(dialog).getByRole("button", { name: /end call/i }));
}

describe("LiveCallsPanel — end call", () => {
  it("posts to the hangup endpoint for the clicked call and toasts success", async () => {
    mockLiveRoster([liveCall()]);

    let hangupUrl: string | null = null;
    server.use(
      http.post(
        `${ORIGIN}/api/v1/workspaces/:workspaceId/calls/:callId/hangup`,
        ({ request }) => {
          hangupUrl = request.url;
          return HttpResponse.json({ success: true });
        },
      ),
    );

    renderPanel();
    await endCallAndConfirm();

    await waitFor(() =>
      expect(hangupUrl).toBe(
        `${ORIGIN}/api/v1/workspaces/${WORKSPACE_ID}/calls/${CALL_ID}/hangup`,
      ),
    );
    await waitFor(() => expect(toastSuccess).toHaveBeenCalledWith("Call ended"));
    expect(toastError).not.toHaveBeenCalled();
  });

  it("asks for confirmation and hangs up nothing until the operator confirms", async () => {
    mockLiveRoster([liveCall()]);

    let hangupCount = 0;
    server.use(
      http.post(
        `${ORIGIN}/api/v1/workspaces/:workspaceId/calls/:callId/hangup`,
        () => {
          hangupCount += 1;
          return HttpResponse.json({ success: true });
        },
      ),
    );

    renderPanel();

    // The button sits next to "Supervise" in a roster that reorders while it
    // polls, so a single misclick must never drop a live customer call.
    await userEvent.click(await screen.findByRole("button", { name: /end call/i }));

    const dialog = await screen.findByRole("alertdialog");
    expect(within(dialog).getByText(/Dana Reeves/)).toBeInTheDocument();
    expect(within(dialog).getByText(/cannot be undone/i)).toBeInTheDocument();

    await userEvent.click(within(dialog).getByRole("button", { name: /keep call/i }));

    await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
    expect(hangupCount).toBe(0);
    expect(toastSuccess).not.toHaveBeenCalled();
    // The call is still live and still on the roster.
    expect(screen.getByText("Dana Reeves")).toBeInTheDocument();
  });

  it("only disables the row being dropped, leaving other live calls actionable", async () => {
    mockLiveRoster([
      liveCall(),
      liveCall({ call_id: "call_other", contact_name: "Sam Okafor" }),
    ]);

    // Held open so both rows are observable mid-flight.
    let release: () => void = () => {};
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    server.use(
      http.post(
        `${ORIGIN}/api/v1/workspaces/:workspaceId/calls/:callId/hangup`,
        async () => {
          await gate;
          return HttpResponse.json({ success: true });
        },
      ),
    );

    renderPanel();
    await endCallAndConfirm(0);

    // Regression: a bare `isPending` froze every row, so one hangup locked the
    // operator out of ending any other call on the roster.
    await waitFor(() => {
      const [first, second] = screen.getAllByRole("button", { name: /end call/i });
      expect(first).toBeDisabled();
      expect(second).toBeEnabled();
    });

    release();
    await waitFor(() => expect(toastSuccess).toHaveBeenCalledWith("Call ended"));
  });

  it("keeps the button disabled while the hangup is in flight", async () => {
    mockLiveRoster([liveCall()]);

    // Held-open response so the in-flight (pending) state is observable.
    let release: () => void = () => {};
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    server.use(
      http.post(
        `${ORIGIN}/api/v1/workspaces/:workspaceId/calls/:callId/hangup`,
        async () => {
          await gate;
          return HttpResponse.json({ success: true });
        },
      ),
    );

    renderPanel();
    const endCall = (await screen.findAllByRole("button", { name: /end call/i }))[0];
    await endCallAndConfirm();

    // Still pending: a second click must not fire a second hangup.
    await waitFor(() => expect(endCall).toBeDisabled());

    release();
    await waitFor(() => expect(toastSuccess).toHaveBeenCalledWith("Call ended"));
  });

  it("surfaces the backend error and leaves the call on the roster", async () => {
    mockLiveRoster([liveCall()]);
    server.use(
      http.post(
        `${ORIGIN}/api/v1/workspaces/:workspaceId/calls/:callId/hangup`,
        () => HttpResponse.json({ detail: "Telnyx not configured" }, { status: 503 }),
      ),
    );

    renderPanel();
    await endCallAndConfirm();

    await waitFor(() =>
      expect(toastError).toHaveBeenCalledWith("Telnyx not configured"),
    );
    expect(toastSuccess).not.toHaveBeenCalled();
    expect(screen.getByText("Dana Reeves")).toBeInTheDocument();
  });
});
