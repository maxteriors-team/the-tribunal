import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { createElement, type ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { queryKeys } from "@/lib/query-keys";
import { server } from "@/test/msw/server";

import { useMarkAttendance } from "./useMarkAttendance";

const ORIGIN = "http://localhost:3000";
const WORKSPACE_ID = "ws_1";
const APPOINTMENT_ID = 42;

const { toastSuccess, toastError } = vi.hoisted(() => ({
  toastSuccess: vi.fn(),
  toastError: vi.fn(),
}));

vi.mock("sonner", () => ({
  toast: { success: toastSuccess, error: toastError },
}));

afterEach(() => {
  toastSuccess.mockReset();
  toastError.mockReset();
});

function makeWrapper() {
  const queryClient = new QueryClient({
    // Non-zero gcTime: these tests seed cache entries that no component
    // observes, and gcTime 0 collects them the moment they are written.
    defaultOptions: { queries: { retry: false, gcTime: 60_000, staleTime: 0 } },
  });
  const wrapper = ({ children }: { children: ReactNode }) =>
    createElement(QueryClientProvider, { client: queryClient }, children);
  return { wrapper, queryClient };
}

/** A cached list page holding one scheduled appointment. */
function seedList(queryClient: QueryClient) {
  const key = queryKeys.appointments.list(WORKSPACE_ID);
  queryClient.setQueryData(key, {
    items: [{ id: APPOINTMENT_ID, status: "scheduled" }],
    total: 1,
    page: 1,
    page_size: 50,
    pages: 1,
  });
  return key;
}

function cachedStatus(queryClient: QueryClient, key: readonly unknown[]) {
  const cached = queryClient.getQueryData<{ items: { status: string }[] }>(key);
  return cached?.items[0]?.status;
}

describe("useMarkAttendance", () => {
  it("PUTs the outcome and shows the cached row as no-show before the response lands", async () => {
    let sentBody: unknown = null;
    server.use(
      http.put(
        `${ORIGIN}/api/v1/workspaces/:workspaceId/appointments/:appointmentId`,
        async ({ request, params }) => {
          sentBody = await request.json();
          expect(params.workspaceId).toBe(WORKSPACE_ID);
          expect(params.appointmentId).toBe(String(APPOINTMENT_ID));
          return HttpResponse.json({ id: APPOINTMENT_ID, status: "no_show" });
        },
      ),
    );

    const { wrapper, queryClient } = makeWrapper();
    const key = seedList(queryClient);
    const { result } = renderHook(
      () => useMarkAttendance({ workspaceId: WORKSPACE_ID }),
      { wrapper },
    );

    result.current.mutate({ appointmentId: APPOINTMENT_ID, outcome: "no_show" });

    // Optimistic: the row flips before the network settles.
    await waitFor(() => expect(cachedStatus(queryClient, key)).toBe("no_show"));
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(sentBody).toEqual({ status: "no_show" });
    expect(toastSuccess).toHaveBeenCalledWith("Marked as a no-show");
  });

  it("rolls the optimistic status back when the request fails", async () => {
    server.use(
      http.put(
        `${ORIGIN}/api/v1/workspaces/:workspaceId/appointments/:appointmentId`,
        () => HttpResponse.json({ detail: "boom" }, { status: 500 }),
      ),
    );

    const { wrapper, queryClient } = makeWrapper();
    const key = seedList(queryClient);
    const { result } = renderHook(
      () => useMarkAttendance({ workspaceId: WORKSPACE_ID }),
      { wrapper },
    );

    result.current.mutate({ appointmentId: APPOINTMENT_ID, outcome: "completed" });

    await waitFor(() => expect(result.current.isError).toBe(true));
    // A failed marking must not leave a wrong attendance on screen.
    expect(cachedStatus(queryClient, key)).toBe("scheduled");
    expect(toastError).toHaveBeenCalled();
    expect(toastSuccess).not.toHaveBeenCalled();
  });
});
