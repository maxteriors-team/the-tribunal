import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { NewMessageNotifier } from "@/components/layout/new-message-notifier";
import { RecentChatsMenu } from "@/components/layout/recent-chats-menu";
import { can as roleCan, roleTier, type Capability } from "@/lib/permissions";
import { server } from "@/test/msw/server";

/**
 * The header's chat surfaces, checked at the network boundary.
 *
 * Both endpoints behind them are `crm:read`, which a field technician does not
 * have: before these gates the shell polled `conversations/unread` every 15s on
 * every page of a technician's session and logged a 403 each time. Nothing here
 * mocks the API layer — real hooks, real axios, MSW answering — so a leaked
 * request is observable as a request, not as a mock call count.
 *
 * Roles come from the real permission matrix, so these break if the matrix and
 * the UI gates ever drift apart.
 */

const { useWorkspaceIdMock, capabilitiesMock } = vi.hoisted(() => ({
  useWorkspaceIdMock: vi.fn(),
  capabilitiesMock: vi.fn(),
}));

vi.mock("@/hooks/useWorkspaceId", () => ({
  useWorkspaceId: () => useWorkspaceIdMock(),
}));

vi.mock("@/hooks/useCapabilities", () => ({
  useCapabilities: () => capabilitiesMock(),
}));

function signedInAs(role: string) {
  capabilitiesMock.mockReturnValue({
    tier: roleTier(role),
    can: (capability: Capability) => roleCan(role, capability),
  });
}

/**
 * Answer every conversation route with the 403 the backend would send a
 * technician, recording each request. Owners get the same recorder with a
 * normal payload, so both roles are measured the same way.
 */
function recordConversationRequests(status: 200 | 403) {
  const requested: string[] = [];
  const respond = (payload: Record<string, unknown>) =>
    status === 403
      ? HttpResponse.json(
          { detail: "You do not have permission to perform this action" },
          { status: 403 },
        )
      : HttpResponse.json(payload);

  for (const origin of ["http://localhost:3000", "http://localhost:8000"]) {
    server.use(
      http.get(
        `${origin}/api/v1/workspaces/:workspaceId/conversations/unread`,
        ({ request }) => {
          requested.push(new URL(request.url).pathname);
          return respond({ unread_conversations: 2, unread_messages: 5 });
        },
      ),
      http.get(
        `${origin}/api/v1/workspaces/:workspaceId/conversations`,
        ({ request }) => {
          requested.push(new URL(request.url).pathname);
          return respond({ items: [], total: 0, page: 1, page_size: 12, pages: 0 });
        },
      ),
    );
  }

  return requested;
}

/**
 * Give the rollup poll every chance to fire before declaring silence.
 * Act-wrapped so a leak shows up as a recorded request, not an act warning.
 */
async function settle() {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 50));
  });
}

function renderHeaderChat() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return render(
    <QueryClientProvider client={client}>
      <NewMessageNotifier />
      <RecentChatsMenu />
    </QueryClientProvider>,
  );
}

let consoleErrorSpy: ReturnType<typeof vi.spyOn>;

beforeEach(() => {
  vi.clearAllMocks();
  useWorkspaceIdMock.mockReturnValue("ws-1");
  signedInAs("owner");
  // Pass-through: the shared setup's console.error wrapper still sees React
  // act warnings; this only records what the components logged.
  consoleErrorSpy = vi.spyOn(console, "error");
});

afterEach(() => {
  consoleErrorSpy.mockRestore();
});

describe("header chat surfaces for a field technician", () => {
  it("polls nothing and renders no chat entry point", async () => {
    signedInAs("technician");
    const requested = recordConversationRequests(403);

    renderHeaderChat();

    await waitFor(() => expect(capabilitiesMock).toHaveBeenCalled());
    await settle();

    expect(requested).toEqual([]);
    expect(
      screen.queryByRole("button", { name: /Recent chats/ }),
    ).not.toBeInTheDocument();
    // A 403 surfacing through axios would land here; nothing was asked for.
    expect(consoleErrorSpy).not.toHaveBeenCalled();
  });

  it("stays silent for a lead technician too", async () => {
    signedInAs("lead_technician");
    const requested = recordConversationRequests(403);

    renderHeaderChat();
    await settle();

    expect(requested).toEqual([]);
    expect(consoleErrorSpy).not.toHaveBeenCalled();
  });
});

describe("header chat surfaces for office roles", () => {
  it.each(["owner", "admin", "manager"])(
    "still polls the unread rollup and shows the badge for %s",
    async (role) => {
      signedInAs(role);
      const requested = recordConversationRequests(200);

      renderHeaderChat();

      const trigger = await screen.findByRole("button", {
        name: "Recent chats, 5 unread",
      });
      expect(trigger).toBeInTheDocument();
      expect(requested).toContain("/api/v1/workspaces/ws-1/conversations/unread");
    },
  );

  it("still defers the thread list until the menu is opened", async () => {
    const requested = recordConversationRequests(200);

    renderHeaderChat();
    await screen.findByRole("button", { name: /Recent chats/ });

    expect(requested).not.toContain("/api/v1/workspaces/ws-1/conversations");
  });
});
