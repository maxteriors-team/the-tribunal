import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { NewAppointmentDialog } from "@/components/calendar/new-appointment-dialog";
import { can as roleCan, roleTier, type Capability } from "@/lib/permissions";
import { server } from "@/test/msw/server";

/**
 * Agent lookup on the create-appointment form, checked at the network boundary.
 *
 * The calendar keeps this dialog mounted whether or not it is open, so an
 * ungated `useAgents` cost every operator a `GET /agents` on every calendar page
 * load — and a field technician a 403, since that route is `crm:read`. Nothing
 * here mocks the API layer, so a leaked request is observable as a request.
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

// Nothing below this line is stubbed: the real assignee picker and contact
// combobox stay in the tree so the recorder sees this dialog's *whole* request
// profile, not just the query under test.

function signedInAs(role: string) {
  capabilitiesMock.mockReturnValue({
    tier: roleTier(role),
    can: (capability: Capability) => roleCan(role, capability),
  });
}

const AGENTS_PAGE = {
  items: [{ id: "agent-1", name: "Reminder Bot", reminder_enabled: true }],
  total: 1,
  page: 1,
  page_size: 100,
  pages: 1,
};

const FORBIDDEN = { detail: "You do not have permission to perform this action" };

/**
 * Record every workspace-scoped GET this dialog makes, answering each with the
 * status the backend would actually send this role. Recording the whole
 * `crm:read` surface — not just `agents` — is what makes "a technician requests
 * nothing" a real claim rather than one endpoint's alibi.
 */
function recordWorkspaceRequests(status: 200 | 403) {
  const requested: string[] = [];
  const respond = (payload: Record<string, unknown>) =>
    status === 403
      ? HttpResponse.json(FORBIDDEN, { status: 403 })
      : HttpResponse.json(payload);

  for (const origin of ["http://localhost:3000", "http://localhost:8000"]) {
    server.use(
      http.get(`${origin}/api/v1/workspaces/:workspaceId/agents`, ({ request }) => {
        const url = new URL(request.url);
        requested.push(`${url.pathname}${url.search}`);
        return respond(AGENTS_PAGE);
      }),
      // The assignee picker's roster, reached only by `jobs:write` roles.
      http.get(
        `${origin}/api/v1/workspaces/:workspaceId/bookable-staff`,
        ({ request }) => {
          requested.push(new URL(request.url).pathname);
          return respond({ items: [] });
        },
      ),
      // The contact picker searches on keystroke; it must stay quiet on mount.
      http.get(
        `${origin}/api/v1/workspaces/:workspaceId/contacts`,
        ({ request }) => {
          requested.push(new URL(request.url).pathname);
          return respond({ items: [], total: 0, page: 1, page_size: 50, pages: 0 });
        },
      ),
    );
  }

  return requested;
}

/** Only the agents lookups, for assertions about that query specifically. */
const agentCalls = (requested: string[]) =>
  requested.filter((entry) => entry.includes("/agents"));

function renderDialog(open: boolean) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return render(
    <QueryClientProvider client={client}>
      <NewAppointmentDialog open={open} onOpenChange={() => {}} />
    </QueryClientProvider>,
  );
}

/**
 * Give any request this dialog might make time to reach MSW. Act-wrapped so a
 * leak shows up as a recorded request rather than as a React act warning.
 */
async function settle() {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 50));
  });
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

describe("agent lookup for a field technician", () => {
  it("requests nothing at all, even with the form open", async () => {
    signedInAs("technician");
    const requested = recordWorkspaceRequests(403);

    renderDialog(true);
    await screen.findByText("New Appointment");
    await settle();

    // Not just the agents query: the whole dialog stays off the network.
    expect(requested).toEqual([]);
    // A 403 surfacing through axios would land here; nothing was asked for.
    expect(consoleErrorSpy).not.toHaveBeenCalled();
  });

  it("leaves the agent picker usable rather than stuck loading", async () => {
    signedInAs("technician");
    recordWorkspaceRequests(403);

    renderDialog(true);
    await screen.findByText("New Appointment");
    await settle();

    // A disabled query stays `pending` forever — the field must not read as
    // perpetually loading, or stay disabled, because of it.
    expect(screen.queryByText("Loading agents...")).not.toBeInTheDocument();
    const agentPicker = screen.getByRole("combobox", { name: /Assigned Agent/ });
    expect(agentPicker).not.toBeDisabled();
    expect(agentPicker).toHaveTextContent("No agent");
  });

  it("closes the client field rather than letting autofocus search the roster", async () => {
    signedInAs("technician");
    const requested = recordWorkspaceRequests(403);

    renderDialog(true);
    await screen.findByText("New Appointment");

    // The dialog autofocuses its first field; typing into an open picker is
    // what fetched the contact list, so the field must not accept focus.
    const clientField = screen.getByPlaceholderText(
      "You do not have access to the client list",
    );
    expect(clientField).toBeDisabled();
    await userEvent.click(clientField);
    await settle();

    expect(requested).toEqual([]);
  });
});

describe("agent lookup for office roles", () => {
  it("does not fetch while the dialog is closed", async () => {
    const requested = recordWorkspaceRequests(200);

    renderDialog(false);
    await settle();

    expect(requested).toEqual([]);
    expect(screen.queryByText("New Appointment")).not.toBeInTheDocument();
  });

  it.each(["owner", "admin"])("loads the agent list on open for %s", async (role) => {
    signedInAs(role);
    const requested = recordWorkspaceRequests(200);

    renderDialog(true);

    await waitFor(() => expect(agentCalls(requested)).toHaveLength(1));
    // Unchanged params: only active agents, one page deep.
    expect(agentCalls(requested)[0]).toContain("active_only=true");
    expect(agentCalls(requested)[0]).toContain("page_size=100");
    await waitFor(() =>
      expect(screen.queryByText("Loading agents...")).not.toBeInTheDocument(),
    );
    expect(consoleErrorSpy).not.toHaveBeenCalled();
  });
});
