import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { ComparisonDecline } from "@/components/estimator/comparison-decline";
import { server } from "@/test/msw/server";

const ORIGIN = "http://localhost:3000";
const TOKEN = "tok_abc";

function renderDecline(declined = false) {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ComparisonDecline token={TOKEN} declined={declined} />
    </QueryClientProvider>,
  );
}

describe("ComparisonDecline", () => {
  it("sends the client's reason and then stops asking", async () => {
    let body: { reason?: string | null } | undefined;
    server.use(
      http.post(`${ORIGIN}/api/v1/p/compare/:token/decline`, async ({ request }) => {
        body = (await request.json()) as { reason?: string | null };
        return HttpResponse.json({ token: TOKEN, is_declined: true, message: "ok" });
      }),
    );
    renderDecline();

    await userEvent.click(screen.getByRole("button", { name: "Not moving forward?" }));
    await userEvent.type(screen.getByLabelText(/Mind telling us why/i), "Went with a neighbor");
    await userEvent.click(screen.getByRole("button", { name: "Confirm" }));

    await waitFor(() => expect(body?.reason).toBe("Went with a neighbor"));
    // The page must not keep offering a decision it already has.
    expect(await screen.findByRole("status")).toHaveTextContent(/Thanks for letting us know/i);
    expect(screen.queryByRole("button", { name: "Confirm" })).not.toBeInTheDocument();
  });

  it("shows the recorded state when an already-declined estimate is reopened", () => {
    renderDecline(true);

    // Reopening the link later must not invite a second decline.
    expect(screen.getByRole("status")).toHaveTextContent(/Thanks for letting us know/i);
    expect(screen.queryByRole("button", { name: "Not moving forward?" })).not.toBeInTheDocument();
  });

  it("sends no reason when the client skips the note", async () => {
    let body: { reason?: string | null } | undefined;
    server.use(
      http.post(`${ORIGIN}/api/v1/p/compare/:token/decline`, async ({ request }) => {
        body = (await request.json()) as { reason?: string | null };
        return HttpResponse.json({ token: TOKEN, is_declined: true, message: "ok" });
      }),
    );
    renderDecline();

    await userEvent.click(screen.getByRole("button", { name: "Not moving forward?" }));
    await userEvent.click(screen.getByRole("button", { name: "Confirm" }));

    // Declining must never be gated on explaining yourself.
    await waitFor(() => expect(body).toBeDefined());
    expect(body?.reason).toBeNull();
  });

  it("keeps the client's typed reason when the send fails", async () => {
    server.use(
      http.post(`${ORIGIN}/api/v1/p/compare/:token/decline`, () =>
        HttpResponse.json({ detail: "nope" }, { status: 500 }),
      ),
    );
    renderDecline();

    await userEvent.click(screen.getByRole("button", { name: "Not moving forward?" }));
    await userEvent.type(screen.getByLabelText(/Mind telling us why/i), "Too expensive");
    await userEvent.click(screen.getByRole("button", { name: "Confirm" }));

    // Retyping the reason after a failure is how people give up instead.
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.getByLabelText(/Mind telling us why/i)).toHaveValue("Too expensive");
  });
});
