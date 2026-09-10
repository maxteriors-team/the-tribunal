import { useMutation, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import {
  ErrorBoundaryHandler,
  type ErrorComponent,
} from "next/dist/client/components/error-boundary";
import type { ComponentType, PropsWithChildren } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PracticeArena } from "@/components/agents/practice-arena";
import { FindLeadsPage } from "@/components/contacts/find-leads-page";
import { roleplayApi } from "@/lib/api/roleplay";
import { queryKeys } from "@/lib/query-keys";
import { Providers } from "@/providers/providers";
import { server } from "@/test/msw/server";

const { toastError } = vi.hoisted(() => ({ toastError: vi.fn() }));
const workspaceId = "ws_test_default";
const personasUrl = `*/api/v1/workspaces/${workspaceId}/roleplay/personas`;

// Keep the real query provider, API client, route fallback, and installed Next
// boundary. Only unrelated account/telephony/theme integrations are stubbed.
vi.mock("@sentry/nextjs", () => ({ captureException: vi.fn() }));
vi.mock("@/providers/auth-provider", () => ({
  AuthProvider: ({ children }: PropsWithChildren) => children,
}));
vi.mock("@/providers/workspace-provider", () => ({
  WorkspaceProvider: ({ children }: PropsWithChildren) => children,
}));
vi.mock("@/providers/softphone-provider", () => ({
  SoftphoneProvider: ({ children }: PropsWithChildren) => children,
}));
vi.mock("next-themes", () => ({
  ThemeProvider: ({ children }: PropsWithChildren) => children,
}));
vi.mock("@/hooks/useWorkspaceId", () => ({ useWorkspaceId: () => "ws_test_default" }));
vi.mock("@/hooks/useCapabilities", () => ({ useCapabilities: () => ({ can: () => true }) }));
vi.mock("sonner", () => ({
  Toaster: () => null,
  toast: { error: toastError, success: vi.fn() },
}));

type RouteError = ComponentType<{ error: Error; reset: () => void }>;
const routeErrors = import.meta.glob("./**/error.tsx", { eager: true }) as Record<
  string,
  { default: RouteError }
>;

function renderRoute(path: string, children = <PracticeArena />) {
  const RouteError = routeErrors[path].default;
  const errorComponent: ErrorComponent = ({ error, reset }) => {
    if (!(error instanceof Error)) throw error;
    return <RouteError error={error} reset={reset} />;
  };
  let queryClient: QueryClient;
  function QueryControls({ children }: PropsWithChildren) {
    queryClient = useQueryClient();
    const defaults = queryClient.getDefaultOptions();
    // Skip automatic backoff only; retain the production throwOnError policy.
    queryClient.setDefaultOptions({
      ...defaults,
      queries: { ...defaults.queries, retry: false },
    });
    return children;
  }
  const view = render(
    <Providers>
      <QueryControls>
        <ErrorBoundaryHandler pathname={path} errorComponent={errorComponent}>
          {children}
        </ErrorBoundaryHandler>
      </QueryControls>
    </Providers>,
    { onCaughtError: () => {} },
  );
  return { ...view, client: () => queryClient };
}

function mockPracticeChoices() {
  server.use(
    http.get(`*/api/v1/workspaces/${workspaceId}/agents`, () =>
      HttpResponse.json({
        items: [{ id: "agent-1", name: "Retry agent" }],
        total: 1,
        page: 1,
        page_size: 50,
        pages: 1,
      }),
    ),
    http.get(personasUrl, () =>
      HttpResponse.json([
        {
          id: "persona-1",
          name: "Skeptical customer",
          difficulty: "medium",
          objections: [],
          description: "A customer with questions",
          is_builtin: true,
        },
      ]),
    ),
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  server.use(
    http.get(`*/api/v1/workspaces/${workspaceId}/roleplay/runs`, () => HttpResponse.json([])),
  );
});

describe("F01: installed Next route boundary recovery", () => {
  it("covers every route fallback, including the root", () => {
    expect(Object.keys(routeErrors)).toHaveLength(27);
    expect(routeErrors).toHaveProperty("./error.tsx");
  });

  it.each(Object.keys(routeErrors))(
    "%s retries a real failed query until the service recovers",
    async (path) => {
      const user = userEvent.setup();
      let unavailable = true;
      let requests = 0;
      server.use(
        http.get(personasUrl, () => {
          requests += 1;
          return unavailable
            ? HttpResponse.json({ detail: "Practice service unavailable" }, { status: 503 })
            : HttpResponse.json([]);
        }),
      );
      const { client } = renderRoute(path);
      client().setQueryData(["unrelated-draft"], { text: "Keep this draft" });

      const retry = await screen.findByRole("button", { name: "Try again" });
      expect(requests).toBe(1);
      expect(screen.queryByRole("heading", { name: "Practice Arena" })).not.toBeInTheDocument();
      expect(screen.getByRole("link", { name: "Back to app" })).toHaveAttribute("href", "/");

      // A second outage must remain retryable, not loop automatically or go blank.
      await user.click(retry);
      await waitFor(() => expect(requests).toBe(2));
      await screen.findByRole("button", { name: "Try again" });
      expect(screen.getByRole("link", { name: "Back to app" })).toBeVisible();

      unavailable = false;
      await user.click(screen.getByRole("button", { name: "Try again" }));
      expect(await screen.findByRole("heading", { name: "Practice Arena" })).toBeVisible();
      expect(requests).toBe(3);
      expect(screen.queryByRole("button", { name: "Try again" })).not.toBeInTheDocument();
      expect(client().getQueryData(["unrelated-draft"])).toEqual({ text: "Keep this draft" });
    },
  );

  it.each([422, 503])(
    "keeps a handled %s search failure and its input inside the form",
    async (status) => {
      const user = userEvent.setup();
      const searches: unknown[] = [];
      let unavailable = true;
      server.use(
        http.post(`*/api/v1/workspaces/${workspaceId}/scraping/search`, async ({ request }) => {
          searches.push(await request.json());
          return unavailable
            ? HttpResponse.json({ detail: "Search temporarily unavailable" }, { status })
            : HttpResponse.json({
                results: [],
                total_found: 0,
                query: "Gutter cleaners in Austin",
              });
        }),
      );
      renderRoute("./find-leads/error.tsx", <FindLeadsPage />);
      const input = screen.getByPlaceholderText(/plumbers in Austin/);
      await user.type(input, "Gutter cleaners in Austin");
      await user.click(screen.getByRole("button", { name: "Search" }));

      await waitFor(() => expect(toastError).toHaveBeenCalled());
      expect(screen.getByPlaceholderText(/plumbers in Austin/)).toHaveValue(
        "Gutter cleaners in Austin",
      );
      expect(screen.getByRole("button", { name: "Search" })).toBeEnabled();
      expect(screen.queryByRole("button", { name: "Try again" })).not.toBeInTheDocument();

      unavailable = false;
      await user.click(screen.getByRole("button", { name: "Search" }));
      expect(await screen.findByText("0 selected")).toBeVisible();
      expect(searches).toEqual([
        { query: "Gutter cleaners in Austin", max_results: 60 },
        { query: "Gutter cleaners in Austin", max_results: 60 },
      ]);
    },
  );

  it("keeps practice selections and an inline retry when a background query fails", async () => {
    const user = userEvent.setup();
    mockPracticeChoices();
    const { client } = renderRoute(
      "./agents/error.tsx",
      <PracticeArena initialAgentId="agent-1" />,
    );
    await user.click(await screen.findByRole("combobox", { name: "Prospect persona" }));
    await user.click(screen.getByRole("option", { name: /Skeptical customer/ }));
    server.use(
      http.get(personasUrl, () =>
        HttpResponse.json({ detail: "Practice service unavailable" }, { status: 503 }),
      ),
    );

    await act(async () => {
      await client().invalidateQueries({ queryKey: queryKeys.roleplay.personas(workspaceId) });
    });
    expect(await screen.findByText(/Some practice data couldn't refresh/)).toBeVisible();
    expect(screen.getByRole("combobox", { name: "Agent" })).toHaveTextContent("Retry agent");
    expect(screen.getByRole("combobox", { name: "Prospect persona" })).toHaveTextContent(
      "Skeptical customer",
    );

    mockPracticeChoices();
    await user.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() =>
      expect(screen.queryByText(/Some practice data couldn't refresh/)).not.toBeInTheDocument(),
    );
    expect(client().getQueryState(queryKeys.roleplay.personas(workspaceId))?.status).toBe(
      "success",
    );
    expect(screen.getByRole("combobox", { name: "Prospect persona" })).toHaveTextContent(
      "Skeptical customer",
    );
  });

  it("shows fallback feedback when a mutation has no feature-level error handler", async () => {
    const user = userEvent.setup();
    server.use(
      http.post(`*/api/v1/workspaces/${workspaceId}/roleplay/runs`, () =>
        HttpResponse.json({ detail: "Practice temporarily unavailable" }, { status: 503 }),
      ),
    );
    function SubmitWithoutErrorHandler() {
      const mutation = useMutation({
        mutationFn: () =>
          roleplayApi.createRun(workspaceId, { agent_id: "agent-1", persona_id: "persona-1" }),
      });
      return (
        <button disabled={mutation.isPending} onClick={() => mutation.mutate()}>
          Submit
        </button>
      );
    }
    renderRoute("./agents/error.tsx", <SubmitWithoutErrorHandler />);
    await user.click(screen.getByRole("button", { name: "Submit" }));
    await waitFor(() => {
      expect(toastError).toHaveBeenCalledExactlyOnceWith("Practice temporarily unavailable");
      expect(screen.getByRole("button", { name: "Submit" })).toBeEnabled();
    });
    expect(screen.queryByRole("link", { name: "Back to app" })).not.toBeInTheDocument();
  });

  it("keeps practice selections when submitting fails under the default mutation policy", async () => {
    const user = userEvent.setup();
    mockPracticeChoices();
    server.use(
      http.post(`*/api/v1/workspaces/${workspaceId}/roleplay/runs`, () =>
        HttpResponse.json({ detail: "Practice temporarily unavailable" }, { status: 503 }),
      ),
    );
    renderRoute("./agents/error.tsx", <PracticeArena initialAgentId="agent-1" />);
    await user.click(await screen.findByRole("combobox", { name: "Prospect persona" }));
    await user.click(screen.getByRole("option", { name: /Skeptical customer/ }));
    await user.click(screen.getByRole("button", { name: "Run rehearsal" }));
    await waitFor(() => {
      expect(toastError).toHaveBeenCalledOnce();
      expect(screen.getByRole("button", { name: "Run rehearsal" })).toBeEnabled();
    });
    expect(screen.getByRole("combobox", { name: "Agent" })).toHaveTextContent("Retry agent");
    expect(screen.getByRole("combobox", { name: "Prospect persona" })).toHaveTextContent(
      "Skeptical customer",
    );
    expect(screen.queryByRole("link", { name: "Back to app" })).not.toBeInTheDocument();
  });
});
