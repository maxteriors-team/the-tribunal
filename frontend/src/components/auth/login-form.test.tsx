import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LoginForm } from "./login-form";

const { login } = vi.hoisted(() => ({ login: vi.fn() }));

vi.mock("@/providers/auth-provider", () => ({
  useAuth: () => ({ login }),
}));

afterEach(() => {
  login.mockReset();
});

describe("LoginForm", () => {
  it("replaces a raw Axios 401 with actionable copy and focuses the alert", async () => {
    login.mockRejectedValue({
      message: "Request failed with status code 401",
      response: { status: 401, data: { detail: "Incorrect email or password" } },
    });
    const user = userEvent.setup();
    render(<LoginForm />);

    await user.type(screen.getByLabelText("Email"), "operator@example.com");
    await user.type(screen.getByLabelText("Password"), "not-the-password");
    await user.click(screen.getByRole("button", { name: "Sign In" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(
      "Email or password is incorrect. Try again or reset your password.",
    );
    expect(alert).not.toHaveTextContent("Request failed with status code 401");
    await waitFor(() => expect(alert).toHaveFocus());
  });

  it("gives a network failure a plain recovery step", async () => {
    login.mockRejectedValue(new Error("Network Error"));
    const user = userEvent.setup();
    render(<LoginForm />);

    await user.type(screen.getByLabelText("Email"), "operator@example.com");
    await user.type(screen.getByLabelText("Password"), "not-the-password");
    await user.click(screen.getByRole("button", { name: "Sign In" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(
      "We couldn't reach the sign-in service. Check your connection and try again.",
    );
    expect(alert).toHaveFocus();
  });
});
