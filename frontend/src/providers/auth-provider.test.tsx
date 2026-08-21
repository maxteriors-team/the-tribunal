import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AuthProvider, safeRedirectPath, useAuth } from "@/providers/auth-provider";

// --- Hoisted mocks -------------------------------------------------------

const {
  replaceMock,
  pathnameMock,
  loginApiMock,
  getCurrentUserMock,
  apiPostMock,
  queryClientClearMock,
} = vi.hoisted(() => ({
  replaceMock: vi.fn(),
  pathnameMock: vi.fn<() => string>(),
  loginApiMock: vi.fn(),
  getCurrentUserMock: vi.fn(),
  apiPostMock: vi.fn(),
  queryClientClearMock: vi.fn(),
}));

vi.mock("@tanstack/react-query", () => ({
  useQueryClient: () => ({ clear: queryClientClearMock }),
}));

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
  queryClientClearMock.mockReset();
  setUrl("/");
});

afterEach(() => {
  vi.restoreAllMocks();
  setUrl("/");
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

  it.each([
    "/forgot-password",
    "/reset-password?token=public-recovery-route-test-token-0000",
  ])("keeps the password recovery page public at %s", async (url) => {
    const pathname = url.split("?")[0];
    pathnameMock.mockReturnValue(pathname);
    setUrl(url);

    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    );

    await waitFor(() => expect(screen.getByTestId("auth").textContent).toBe("no"));
    expect(getCurrentUserMock).not.toHaveBeenCalled();
    expect(replaceMock).not.toHaveBeenCalled();
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

    expect(queryClientClearMock).toHaveBeenCalledTimes(1);
    expect(replaceMock).toHaveBeenCalledWith("/login");
  });

  it("honours ?redirect= after a successful login", async () => {
    await signInAt("/login?redirect=/invite/tok123");

    await waitFor(() => {
      expect(replaceMock).toHaveBeenCalledWith("/invite/tok123");
    });
    expect(queryClientClearMock).toHaveBeenCalledTimes(1);
  });

  it("refuses an off-site ?redirect= after login", async () => {
    await signInAt("/login?redirect=https://evil.com");

    await waitFor(() => {
      expect(replaceMock).toHaveBeenCalledWith("/");
    });
    expect(replaceMock).not.toHaveBeenCalledWith("https://evil.com");
  });

  it.each([
    "https://evil.com",
    "//evil.com",
    "/\\evil.com",
  ])("refuses %s as a post-login destination", async (hostile) => {
    await signInAt(`/login?redirect=${hostile}`);

    await waitFor(() => {
      expect(replaceMock).toHaveBeenCalledWith("/");
    });
    expect(replaceMock).not.toHaveBeenCalledWith(hostile);
  });
});

/**
 * The journey that was reported broken: "I was invited but I still can't get in."
 *
 * She opened her invitation, signed out to switch to the invited account, signed
 * back in — and landed on the dashboard with the invitation still pending, no
 * way left in the product to reach it. The halves are asserted individually
 * above; these pin the *journey*, because two separate fixes each passed their
 * own unit tests while the end-to-end trip stayed broken.
 */
describe("invited teammate round trip (regression)", () => {
  const INVITE = "/invite/gbqtqbxM66i2YFhjHTZ";

  it("lets a signed-out invitee stay on the invitation instead of bouncing them", async () => {
    // `/invite/` is deliberately public: an invitee without an account has to be
    // able to read who invited them and reach "Create Account & Join". Bouncing
    // them to /login here would strand exactly the people invitations exist for.
    getCurrentUserMock.mockRejectedValue(new Error("401"));
    pathnameMock.mockReturnValue(INVITE);

    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    );

    await waitFor(() => expect(screen.getByTestId("auth").textContent).toBe("no"));
    expect(replaceMock).not.toHaveBeenCalled();
  });

  it("returns to the invitation after signing in from it", async () => {
    // The invite page sends "I already have an account" to
    // /login?redirect=/invite/<token>. Signing in there must resume the
    // invitation — landing on the dashboard is precisely the reported bug.
    await signInAt(`/login?redirect=${INVITE}`);

    await waitFor(() => {
      expect(replaceMock).toHaveBeenCalledWith(INVITE);
    });
    expect(replaceMock).not.toHaveBeenCalledWith("/");
  });

  it("survives signing out from the invitation to switch accounts", async () => {
    // She was signed in as the wrong account — the only reason to sign out from
    // an invitation page. The invite has to outlive the sign-out.
    getCurrentUserMock.mockResolvedValue(USER);
    pathnameMock.mockReturnValue(INVITE);

    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    );
    await waitFor(() => expect(screen.getByTestId("auth").textContent).toBe("yes"));

    await userEvent.click(screen.getByRole("button", { name: "logout" }));

    expect(replaceMock).toHaveBeenCalledWith(`/login?redirect=${encodeURIComponent(INVITE)}`);
    expect(replaceMock).not.toHaveBeenCalledWith("/login");
  });
});

