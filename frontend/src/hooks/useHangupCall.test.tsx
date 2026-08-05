import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { createElement, type ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { queryKeys } from "@/lib/query-keys";
import { server } from "@/test/msw/server";

import { useHangupCall } from "./useHangupCall";

const ORIGIN = "http://localhost:3000";
const CALL_ID = "call_abc123";

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

describe("useHangupCall", () => {
  it("posts to the call's hangup endpoint, invalidates the cache, and toasts success", async () => {
    let hitUrl: string | null = null;
    let hitMethod: string | null = null;
    server.use(
      http.post(
        `${ORIGIN}/api/v1/workspaces/:workspaceId/calls/:callId/hangup`,
        ({ request, params }) => {
          hitUrl = request.url;
          hitMethod = request.method;
          expect(params.workspaceId).toBe("ws_1");
          expect(params.callId).toBe(CALL_ID);
          return HttpResponse.json({ success: true });
        },
      ),
    );

    const onSuccess = vi.fn();
    const { wrapper, queryClient } = makeWrapper();
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");

    const { result } = renderHook(
      () => useHangupCall({ workspaceId: "ws_1", onSuccess }),
      { wrapper },
    );

    await result.current.mutateAsync(CALL_ID);

    expect(hitMethod).toBe("POST");
    expect(hitUrl).toBe(
      `${ORIGIN}/api/v1/workspaces/ws_1/calls/${CALL_ID}/hangup`,
    );
    // calls.live() nests under calls.all(), so this one key refreshes the live
    // roster and the call history together.
    await waitFor(() =>
      expect(invalidateSpy).toHaveBeenCalledWith({
        queryKey: queryKeys.calls.all("ws_1"),
      }),
    );
    expect(toastSuccess).toHaveBeenCalledWith("Call ended");
    expect(onSuccess).toHaveBeenCalledWith(CALL_ID);
    expect(toastError).not.toHaveBeenCalled();
  });

  it("rejects and toasts an error when the workspace is not loaded", async () => {
    const { wrapper } = makeWrapper();

    const { result } = renderHook(() => useHangupCall({ workspaceId: null }), {
      wrapper,
    });

    await expect(result.current.mutateAsync(CALL_ID)).rejects.toThrow(
      "Workspace not loaded",
    );

    await waitFor(() =>
      expect(toastError).toHaveBeenCalledWith("Workspace not loaded"),
    );
    expect(toastSuccess).not.toHaveBeenCalled();
  });

  it("surfaces the backend error message when the hangup fails", async () => {
    server.use(
      http.post(
        `${ORIGIN}/api/v1/workspaces/:workspaceId/calls/:callId/hangup`,
        () => HttpResponse.json({ detail: "Telnyx not configured" }, { status: 503 }),
      ),
    );

    const { wrapper } = makeWrapper();

    const { result } = renderHook(() => useHangupCall({ workspaceId: "ws_1" }), {
      wrapper,
    });

    await expect(result.current.mutateAsync(CALL_ID)).rejects.toThrow();

    await waitFor(() =>
      expect(toastError).toHaveBeenCalledWith("Telnyx not configured"),
    );
    expect(toastSuccess).not.toHaveBeenCalled();
  });
});
