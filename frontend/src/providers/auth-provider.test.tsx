import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AuthProvider, safeRedirectPath, useAuth } from "@/providers/auth-provider";

// --- Hoisted mocks -------------------------------------------------------

const { replaceMock, pathnameMock, loginApiMock, getCurrentUserMock, apiPostMock } = vi.hoisted(
  () => ({
    replaceMock: vi.fn(),
    pathnameMock: vi.fn<() => string>(),
    loginApiMock: vi.fn(),
    getCurrentUserMock: vi.fn(),
    apiPostMock: vi.fn(),
  }),
);

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: replaceMock, push: vi.fn() }),
  usePathname: () => pathnameMock(),
}));

vi.mock("@/lib/api/auth", () => ({
  login: loginApiMock,
  getCurrentUser: getCurrentUserMock,
}));

vi.mock("@/lib/api", () => ({
  api: { post: apiPostMock },
}));

// --- Harness -------------------------------------------------------------

const USER = {
  id: 4,
  email: "admin@maxteriors.com",
  full_name: "Admin",
  is_active: true,
  created_at: "2026-01-01T00:00:00Z",
  default_workspace_id: "ws_real",
  must_change_password: false,
};

function Probe() {
  const { login, logout, isAuthenticated } = useAuth();
  return (
    <div>
      <div data-testid="auth">{isAuthenticated ? "yes" : "no"}</div>
      <button onClick={() => void login({ email: "a@b.com", password: "password123" })}>
        login
      </button>
      <button onClick={() => logout()}>logout</button>
    </div>
  );
}

function setUrl(url: string) {
  window.history.replaceState({}, "", url);
}

beforeEach(() => {
  replaceMock.mockReset();
  pathnameMock.mockReset().mockReturnValue("/login");
  loginApiMock.mockReset().mockResolvedValue(undefined);
  getCurrentUserMock.mockReset();
  apiPostMock.mockReset().mockResolvedValue({});
  setUrl("/");
});

afterEach(() => {
  vi.restoreAllMocks();
  setUrl("/");
});

// --- Tests ---------------------------------------------------------------

describe("safeRedirectPath", () => {
  it("accepts in-app paths", () => {
    expect(safeRedirectPath("/invite/abc")).toBe("/invite/abc");
  });

  it.each<{ value: string | null; why: string }>([
    { value: "//evil.com", why: "protocol-relative" },
    { value: "https://evil.com", why: "absolute URL" },
    { value: "/\\evil.com", why: "backslash variant" },
    { value: null, why: "missing" },
    { value: "", why: "empty" },
  ])("rejects $why", ({ value }) => {
    expect(safeRedirectPath(value)).toBeNull();
  });
});

describe("AuthProvider redirects", () => {
  it("sends an unauthenticated deep link to login WITH a return path", async () => {
    // She clicks an invite link while signed out. Losing the destination here
    // is what left the invitation unaccepted.
    getCurrentUserMock.mockRejectedValue(new Error("401"));
    pathnameMock.mockReturnValue("/settings");

    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(replaceMock).toHaveBeenCalledWith("/login?redirect=%2Fsettings");
    });
  });

  it("does not append a redirect for the root path", async () => {
    getCurrentUserMock.mockRejectedValue(new Error("401"));
    pathnameMock.mockReturnValue("/");

    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(replaceMock).toHaveBeenCalledWith("/login");
    });
  });

  it("returns to the invitation after signing out from it", async () => {
    // "Wrong account, let me switch" is the only reason to sign out from an
    // invite page — so the invite must survive the round trip.
    getCurrentUserMock.mockResolvedValue(USER);
    pathnameMock.mockReturnValue("/invite/tok123");

    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    );
    await waitFor(() => expect(screen.getByTestId("auth").textContent).toBe("yes"));

    await userEvent.click(screen.getByRole("button", { name: "logout" }));

    expect(replaceMock).toHaveBeenCalledWith("/login?redirect=%2Finvite%2Ftok123");
  });

  it("signs out to a bare login from a normal page", async () => {
    getCurrentUserMock.mockResolvedValue(USER);
    pathnameMock.mockReturnValue("/contacts");

    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    );
    await waitFor(() => expect(screen.getByTestId("auth").textContent).toBe("yes"));

    await userEvent.click(screen.getByRole("button", { name: "logout" }));

    expect(replaceMock).toHaveBeenCalledWith("/login");
  });

  /**
   * Sign in on `/login?redirect=<target>`.
   *
   * The provider deliberately skips the `/auth/me` probe on public paths such as
   * `/login`, so `getCurrentUser` is only ever called by `login()` itself here.
   */
  async function signInAt(url: string): Promise<void> {
    pathnameMock.mockReturnValue("/login");
    setUrl(url);
    getCurrentUserMock.mockResolvedValue(USER);

    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    );
    // Wait out the mount probe so the signed-out state has settled.
    await waitFor(() => expect(screen.getByTestId("auth").textContent).toBe("no"));
    replaceMock.mockClear();

    await userEvent.click(screen.getByRole("button", { name: "login" }));
    await waitFor(() => expect(getCurrentUserMock).toHaveBeenCalled());
  }

  it("honours ?redirect= after a successful login", async () => {
    await signInAt("/login?redirect=/invite/tok123");

    await waitFor(() => {
      expect(replaceMock).toHaveBeenCalledWith("/invite/tok123");
    });
  });

  it("refuses an off-site ?redirect= after login", async () => {
    await signInAt("/login?redirect=https://evil.com");

    await waitFor(() => {
      expect(replaceMock).toHaveBeenCalledWith("/");
    });
    expect(replaceMock).not.toHaveBeenCalledWith("https://evil.com");
  });
});
