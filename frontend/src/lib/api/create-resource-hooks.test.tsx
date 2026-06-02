import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { createElement, type ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { createResourceQueryKeys } from "@/lib/query-keys";
import { server } from "@/test/msw/server";
import type { PaginatedResponse } from "@/types/api";

import { createApiClient, type ApiClient, type FullApiClient } from "./create-api-client";
import { createResourceHooks } from "./create-resource-hooks";

const ORIGIN = "http://localhost:3000";

// Build expected invalidation keys from the same factory the hooks use, so the
// assertions track the centralized key contract rather than inline literals.
const widgetsAll = createResourceQueryKeys("widgets").all("ws_1");
const contactsAll = createResourceQueryKeys("contacts").all("ws_1");

interface Widget {
  id: number;
  name: string;
}

function makeList(items: Widget[]): PaginatedResponse<Widget> {
  return { items, total: items.length, page: 1, page_size: 50, pages: 1 };
}

function makeWrapper(client?: QueryClient) {
  const queryClient =
    client ??
    new QueryClient({
      defaultOptions: { queries: { retry: false, gcTime: 0, staleTime: 0 } },
    });
  const wrapper = ({ children }: { children: ReactNode }) =>
    createElement(QueryClientProvider, { client: queryClient }, children);
  return { wrapper, queryClient };
}

function widgetApi() {
  return createApiClient<Widget, { name: string }, { name?: string }>({
    resourcePath: "widgets",
  }) as FullApiClient<Widget, { name: string }, { name?: string }>;
}

describe("createResourceHooks — query key wiring", () => {
  it("exposes the centralized resource query keys", () => {
    const hooks = createResourceHooks({ resourceKey: "widgets", apiClient: widgetApi() });
    expect(hooks.queryKeys.all("ws_1")).toEqual(["widgets", "ws_1"]);
    expect(hooks.queryKeys.detail("ws_1", 7)).toEqual(["widgets", "ws_1", 7]);
    expect(hooks.queryKeys.list("ws_1", { page: 2 })).toEqual([
      "widgets",
      "ws_1",
      { page: 2 },
    ]);
  });

  it("omits hooks that are disabled via include flags", () => {
    const hooks = createResourceHooks({
      resourceKey: "widgets",
      apiClient: widgetApi(),
      includeGet: false,
      includeDelete: false,
    });
    expect(hooks.useList).toBeDefined();
    expect(hooks.useCreate).toBeDefined();
    expect(hooks.useUpdate).toBeDefined();
    expect((hooks as Partial<typeof hooks>).useGet).toBeUndefined();
    expect((hooks as Partial<typeof hooks>).useDelete).toBeUndefined();
  });
});

describe("createResourceHooks — useList", () => {
  it("fetches the list for a workspace", async () => {
    server.use(
      http.get(`${ORIGIN}/api/v1/workspaces/:workspaceId/widgets`, () =>
        HttpResponse.json(makeList([{ id: 1, name: "Alpha" }])),
      ),
    );

    const hooks = createResourceHooks({ resourceKey: "widgets", apiClient: widgetApi() });
    const { wrapper } = makeWrapper();

    const { result } = renderHook(() => hooks.useList("ws_1"), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.items).toEqual([{ id: 1, name: "Alpha" }]);
  });

  it("is disabled (does not fetch) when the workspace id is empty", async () => {
    const listSpy = vi.fn();
    server.use(
      http.get(`${ORIGIN}/api/v1/workspaces/:workspaceId/widgets`, () => {
        listSpy();
        return HttpResponse.json(makeList([]));
      }),
    );

    const hooks = createResourceHooks({ resourceKey: "widgets", apiClient: widgetApi() });
    const { wrapper } = makeWrapper();

    const { result } = renderHook(() => hooks.useList(""), { wrapper });

    // Disabled query stays pending and never fires the request.
    expect(result.current.fetchStatus).toBe("idle");
    await Promise.resolve();
    expect(listSpy).not.toHaveBeenCalled();
  });
});

describe("createResourceHooks — useGet", () => {
  it("fetches a single resource by id", async () => {
    server.use(
      http.get(`${ORIGIN}/api/v1/workspaces/:workspaceId/widgets/:id`, ({ params }) =>
        HttpResponse.json({ id: Number(params.id), name: "Solo" }),
      ),
    );

    const hooks = createResourceHooks({ resourceKey: "widgets", apiClient: widgetApi() });
    const { wrapper } = makeWrapper();

    const { result } = renderHook(() => hooks.useGet("ws_1", 42), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual({ id: 42, name: "Solo" });
  });

  it("throws a helpful error when the api client lacks a get method", async () => {
    const apiClient = { list: vi.fn() } as unknown as ApiClient<Widget, { name: string }, { name?: string }>;
    const hooks = createResourceHooks({ resourceKey: "widgets", apiClient });
    const { wrapper } = makeWrapper();

    const { result } = renderHook(() => hooks.useGet("ws_1", 1), { wrapper });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error?.message).toMatch(/does not have a 'get' method/);
  });
});

describe("createResourceHooks — mutations invalidate caches", () => {
  it("useCreate invalidates the resource and its related resources on success", async () => {
    server.use(
      http.post(`${ORIGIN}/api/v1/workspaces/:workspaceId/widgets`, () =>
        HttpResponse.json({ id: 1, name: "New" }),
      ),
    );

    const hooks = createResourceHooks({
      resourceKey: "widgets",
      apiClient: widgetApi(),
      invalidateKeys: ["contacts"],
    });
    const { wrapper, queryClient } = makeWrapper();
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");

    const { result } = renderHook(() => hooks.useCreate("ws_1"), { wrapper });

    await result.current.mutateAsync({ name: "New" });

    await waitFor(() => {
      expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: widgetsAll });
      expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: contactsAll });
    });
  });

  it("useUpdate sends the id-scoped PUT and invalidates the resource", async () => {
    let received: unknown = null;
    server.use(
      http.put(`${ORIGIN}/api/v1/workspaces/:workspaceId/widgets/:id`, async ({ request, params }) => {
        received = { id: params.id, body: await request.json() };
        return HttpResponse.json({ id: Number(params.id), name: "Updated" });
      }),
    );

    const hooks = createResourceHooks({ resourceKey: "widgets", apiClient: widgetApi() });
    const { wrapper, queryClient } = makeWrapper();
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");

    const { result } = renderHook(() => hooks.useUpdate("ws_1"), { wrapper });

    const updated = await result.current.mutateAsync({ id: 7, data: { name: "Updated" } });

    expect(received).toEqual({ id: "7", body: { name: "Updated" } });
    expect(updated).toEqual({ id: 7, name: "Updated" });
    await waitFor(() =>
      expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: widgetsAll }),
    );
  });

  it("useDelete issues a DELETE and invalidates the resource", async () => {
    let deletedId: string | readonly string[] | undefined = undefined;
    server.use(
      http.delete(`${ORIGIN}/api/v1/workspaces/:workspaceId/widgets/:id`, ({ params }) => {
        deletedId = params.id;
        return new HttpResponse(null, { status: 204 });
      }),
    );

    const hooks = createResourceHooks({ resourceKey: "widgets", apiClient: widgetApi() });
    const { wrapper, queryClient } = makeWrapper();
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");

    const { result } = renderHook(() => hooks.useDelete("ws_1"), { wrapper });

    await result.current.mutateAsync(7);

    expect(deletedId).toBe("7");
    await waitFor(() =>
      expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: widgetsAll }),
    );
  });

  it("does not invalidate when a mutation fails", async () => {
    server.use(
      http.post(`${ORIGIN}/api/v1/workspaces/:workspaceId/widgets`, () =>
        HttpResponse.json({ message: "boom" }, { status: 500 }),
      ),
    );

    const hooks = createResourceHooks({ resourceKey: "widgets", apiClient: widgetApi() });
    const { wrapper, queryClient } = makeWrapper();
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");

    const { result } = renderHook(() => hooks.useCreate("ws_1"), { wrapper });

    await expect(result.current.mutateAsync({ name: "x" })).rejects.toThrow();
    expect(invalidateSpy).not.toHaveBeenCalled();
  });
});
