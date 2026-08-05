import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { type ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { server } from "@/test/msw/server";
import type { Contact } from "@/types";

import {
  AutomationOptOut,
  hasNoAutomationTag,
  NO_AUTOMATION_TAG,
} from "./automation-opt-out";

const ORIGIN = "http://localhost:3000";
const WORKSPACE_ID = "ws_1";

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

function contact(tags: string[]): Contact {
  return {
    id: 7,
    first_name: "Casey",
    last_name: "Customer",
    phone_number: "+15125550000",
    tag_objects: tags.map((name, index) => ({
      id: `tag-${index}`,
      name,
      color: "#6366f1",
    })),
  } as unknown as Contact;
}

function renderControl(subject: Contact) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  return render(
    <AutomationOptOut contact={subject} workspaceId={WORKSPACE_ID} />,
    { wrapper },
  );
}

describe("hasNoAutomationTag", () => {
  it("matches the reserved tag whatever its casing", () => {
    expect(hasNoAutomationTag(contact([NO_AUTOMATION_TAG]))).toBe(true);
    expect(hasNoAutomationTag(contact(["No-Automation"]))).toBe(true);
    expect(hasNoAutomationTag(contact(["vip", "repeat"]))).toBe(false);
  });
});

describe("AutomationOptOut", () => {
  it("names both things it switches off, and what it does not", () => {
    renderControl(contact([]));

    expect(
      screen.getByText(/no automated follow-ups and no automatic pipeline moves/i),
    ).toBeInTheDocument();
    // The operator must not think this stops them working the contact.
    expect(
      screen.getByText(/Anything you do by hand still works/i),
    ).toBeInTheDocument();
  });

  it("adds the reserved tag while keeping the contact's other tags", async () => {
    let sentBody: { tags?: string[] } | null = null;
    server.use(
      http.put(
        `${ORIGIN}/api/v1/workspaces/:workspaceId/contacts/:contactId`,
        async ({ request }) => {
          sentBody = (await request.json()) as { tags?: string[] };
          return HttpResponse.json({ id: 7 });
        },
      ),
    );

    renderControl(contact(["vip"]));
    await userEvent.click(screen.getByRole("switch"));

    await waitFor(() => expect(sentBody).not.toBeNull());
    expect(sentBody!.tags).toEqual(["vip", NO_AUTOMATION_TAG]);
    await waitFor(() =>
      expect(toastSuccess).toHaveBeenCalledWith(
        "Automation paused for this contact",
      ),
    );
  });

  it("removes only the reserved tag when switched back off", async () => {
    let sentBody: { tags?: string[] } | null = null;
    server.use(
      http.put(
        `${ORIGIN}/api/v1/workspaces/:workspaceId/contacts/:contactId`,
        async ({ request }) => {
          sentBody = (await request.json()) as { tags?: string[] };
          return HttpResponse.json({ id: 7 });
        },
      ),
    );

    renderControl(contact(["vip", NO_AUTOMATION_TAG]));
    await userEvent.click(screen.getByRole("switch"));

    await waitFor(() => expect(sentBody).not.toBeNull());
    expect(sentBody!.tags).toEqual(["vip"]);
  });

  it("surfaces a failure instead of pretending the tag was applied", async () => {
    server.use(
      http.put(`${ORIGIN}/api/v1/workspaces/:workspaceId/contacts/:contactId`, () =>
        HttpResponse.json({ detail: "boom" }, { status: 500 }),
      ),
    );

    renderControl(contact([]));
    await userEvent.click(screen.getByRole("switch"));

    await waitFor(() => expect(toastError).toHaveBeenCalled());
    expect(toastSuccess).not.toHaveBeenCalled();
  });
});
