import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { OfferBuilderClient } from "@/app/offers/new/offer-builder-client";
import { server } from "@/test/msw/server";

const workspaceState = vi.hoisted(() => ({
  id: null as string | null,
}));

vi.mock("@/hooks/useWorkspaceId", () => ({
  useWorkspaceId: () => workspaceState.id,
}));

interface RecordedResponse {
  requestUrl: string;
  status: number;
}

const validWorkspaceIds = new Set(["workspace-alpha", "workspace-beta"]);
let recordedResponses: RecordedResponse[];
let responseListener:
  | ((event: { request: Request; response: Response; requestId: string }) => void)
  | undefined;

function testTree(queryClient: QueryClient) {
  return (
    <QueryClientProvider client={queryClient}>
      <OfferBuilderClient />
    </QueryClientProvider>
  );
}

function renderOfferBuilder() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: Infinity },
    },
  });
  const view = render(testTree(queryClient));

  return { ...view, queryClient };
}

async function rerenderWithWorkspace(
  workspaceId: string | null,
  rerender: (ui: React.ReactNode) => void,
  queryClient: QueryClient,
) {
  workspaceState.id = workspaceId;
  rerender(testTree(queryClient));
  await act(async () => {
    await Promise.resolve();
  });
}

async function waitForRequestsToSettle(queryClient: QueryClient) {
  await waitFor(() => {
    expect(queryClient.isFetching()).toBe(0);
  });
}

function leadMagnetResponses() {
  return recordedResponses.filter(({ requestUrl }) => requestUrl.includes("/lead-magnets"));
}

function expectNoWorkspaceClientErrors() {
  const workspaceResponses = recordedResponses.filter(({ requestUrl }) =>
    requestUrl.includes("/api/v1/workspaces/"),
  );

  expect(workspaceResponses.filter(({ status }) => status >= 400 && status < 500)).toEqual([]);
  expect(
    workspaceResponses.some(({ requestUrl }) => requestUrl.includes("/workspaces/null/")),
  ).toBe(false);
}

beforeEach(() => {
  workspaceState.id = null;
  recordedResponses = [];

  server.use(
    http.get("http://localhost:3000/api/v1/workspaces/:workspaceId/lead-magnets", ({ params }) => {
      const workspaceId = String(params.workspaceId);
      if (!validWorkspaceIds.has(workspaceId)) {
        return HttpResponse.json({ detail: "Workspace not found" }, { status: 422 });
      }

      return HttpResponse.json({
        items: [],
        total: 0,
        page: 1,
        page_size: 100,
        pages: 0,
      });
    }),
  );

  responseListener = ({ request, response }) => {
    recordedResponses.push({ requestUrl: request.url, status: response.status });
  };
  server.events.on("response:mocked", responseListener);
});

afterEach(() => {
  if (responseListener) {
    server.events.removeListener("response:mocked", responseListener);
  }
});

describe("/offers/new workspace-scoped requests", () => {
  it("keeps lead-magnet queries idle during a cold workspace load", async () => {
    const { queryClient, rerender } = renderOfferBuilder();

    await waitForRequestsToSettle(queryClient);
    expect(leadMagnetResponses()).toEqual([]);

    await rerenderWithWorkspace("workspace-alpha", rerender, queryClient);
    await waitFor(() => {
      expect(leadMagnetResponses()).toHaveLength(1);
    });

    expect(new URL(leadMagnetResponses()[0].requestUrl).pathname).toBe(
      "/api/v1/workspaces/workspace-alpha/lead-magnets",
    );
    expectNoWorkspaceClientErrors();
  });

  it("does not issue a 4xx request while switching workspaces", async () => {
    workspaceState.id = "workspace-alpha";
    const { queryClient, rerender } = renderOfferBuilder();

    await waitFor(() => {
      expect(leadMagnetResponses()).toHaveLength(1);
    });

    await rerenderWithWorkspace(null, rerender, queryClient);
    await waitForRequestsToSettle(queryClient);
    expect(leadMagnetResponses()).toHaveLength(1);

    await rerenderWithWorkspace("workspace-beta", rerender, queryClient);
    await waitFor(() => {
      expect(leadMagnetResponses()).toHaveLength(2);
    });

    expect(leadMagnetResponses().map(({ requestUrl }) => new URL(requestUrl).pathname)).toEqual([
      "/api/v1/workspaces/workspace-alpha/lead-magnets",
      "/api/v1/workspaces/workspace-beta/lead-magnets",
    ]);
    expectNoWorkspaceClientErrors();
  });
});
