import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { createElement, type ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { CreateAppointmentRequest } from "@/lib/api/appointments";
import { queryKeys } from "@/lib/query-keys";
import { server } from "@/test/msw/server";

import { useCreateAppointment } from "./useCreateAppointment";

const ORIGIN = "http://localhost:3000";

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
    defaultOptions: { queries: { retry: false, gcTime: 0, staleTime: 0 } },
  });
  const wrapper = ({ children }: { children: ReactNode }) =>
    createElement(QueryClientProvider, { client: queryClient }, children);
  return { wrapper, queryClient };
}

const REQUEST: CreateAppointmentRequest = {
  contact_id: 5,
  scheduled_at: "2026-02-01T10:00:00.000Z",
  duration_minutes: 30,
};

describe("useCreateAppointment", () => {
  it("posts the appointment, invalidates the cache, and toasts success", async () => {
    let received: unknown = null;
    server.use(
      http.post(`${ORIGIN}/api/v1/workspaces/:workspaceId/appointments`, async ({ request, params }) => {
        received = await request.json();
        expect(params.workspaceId).toBe("ws_1");
        return HttpResponse.json({ id: 1, ...REQUEST });
      }),
    );

    const onSuccess = vi.fn();
    const { wrapper, queryClient } = makeWrapper();
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");

    const { result } = renderHook(
      () => useCreateAppointment({ workspaceId: "ws_1", onSuccess }),
      { wrapper },
    );

    await result.current.mutateAsync(REQUEST);

    expect(received).toMatchObject({ contact_id: 5, duration_minutes: 30 });
    await waitFor(() =>
      expect(invalidateSpy).toHaveBeenCalledWith({
        queryKey: queryKeys.appointments.all("ws_1"),
      }),
    );
    expect(toastSuccess).toHaveBeenCalledWith("Appointment scheduled successfully!");
    expect(onSuccess).toHaveBeenCalledTimes(1);
    expect(toastError).not.toHaveBeenCalled();
  });

  it("rejects and toasts an error when the workspace is not loaded", async () => {
    const { wrapper } = makeWrapper();

    const { result } = renderHook(
      () => useCreateAppointment({ workspaceId: null }),
      { wrapper },
    );

    await expect(result.current.mutateAsync(REQUEST)).rejects.toThrow("Workspace not loaded");

    // getApiErrorMessage surfaces the thrown Error's message over the fallback.
    await waitFor(() => expect(toastError).toHaveBeenCalledWith("Workspace not loaded"));
    expect(toastSuccess).not.toHaveBeenCalled();
  });

  it("surfaces the backend error message on a failed request", async () => {
    server.use(
      http.post(`${ORIGIN}/api/v1/workspaces/:workspaceId/appointments`, () =>
        HttpResponse.json({ message: "Slot already booked" }, { status: 409 }),
      ),
    );

    const { wrapper } = makeWrapper();

    const { result } = renderHook(
      () => useCreateAppointment({ workspaceId: "ws_1" }),
      { wrapper },
    );

    await expect(result.current.mutateAsync(REQUEST)).rejects.toThrow();

    await waitFor(() =>
      expect(toastError).toHaveBeenCalledWith("Slot already booked"),
    );
    expect(toastSuccess).not.toHaveBeenCalled();
  });
});
