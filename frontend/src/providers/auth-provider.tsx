"use client";

import { useRouter, usePathname } from "next/navigation";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { api } from "@/lib/api";
import { getCurrentUser, login as loginApi, type User, type LoginCredentials } from "@/lib/api/auth";

interface AuthContextType {
  user: User | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  workspaceId: string | null;
  login: (credentials: LoginCredentials, options?: LoginOptions) => Promise<void>;
  logout: () => void;
}

interface LoginOptions {
  /** Where to land after a successful sign-in. Defaults to `?redirect=`, else "/". */
  redirectTo?: string;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

const PUBLIC_PATHS = ["/login", "/register"];
const PASSWORD_RECOVERY_PATHS = ["/forgot-password", "/reset-password"];
// Customer-facing Stripe Checkout return pages. Public like PUBLIC_PATHS, but
// deliberately not in that list: signed-in operators testing a payment should
// see the page too, not get bounced to "/".
const CUSTOMER_PATHS = ["/payment-complete", "/payment-cancelled"];
const PUBLIC_PATH_PREFIXES = ["/invite/", "/p/", "/embed/"];

function isPublicPathname(pathname: string): boolean {
  return (
    PUBLIC_PATHS.includes(pathname) ||
    PASSWORD_RECOVERY_PATHS.includes(pathname) ||
    CUSTOMER_PATHS.includes(pathname) ||
    PUBLIC_PATH_PREFIXES.some((prefix) => pathname.startsWith(prefix))
  );
}

/**
 * Accept only same-origin, in-app destinations for post-login redirects.
 *
 * Rejects absolute URLs, protocol-relative "//evil.com" (which the browser
 * treats as another origin) and backslash variants, so `?redirect=` cannot be
 * turned into an open redirect that bounces a freshly authenticated operator to
 * an attacker-controlled login-lookalike.
 */
export function safeRedirectPath(value: string | null): string | null {
  if (!value || !value.startsWith("/")) return null;
  if (value.startsWith("//") || value.includes("\\")) return null;
  return value;
}

function requestedRedirect(): string | null {
  if (typeof window === "undefined") return null;
  return safeRedirectPath(new URLSearchParams(window.location.search).get("redirect"));
}

/**
 * Build `/login?redirect=<here>` so signing in returns the user where they were.
 *
 * Dropping the destination is what stranded an invited teammate: she opened her
 * invitation, signed out to switch to the invited account, and came back to a
 * bare `/login` that had forgotten the invitation entirely — so she landed on
 * the dashboard with the invite still unaccepted and no way to find it again.
 */
function loginPathReturningTo(destination: string): string {
  const safe = safeRedirectPath(destination);
  if (!safe || safe === "/") return "/login";
  return `/login?redirect=${encodeURIComponent(safe)}`;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const router = useRouter();
  const pathname = usePathname();

  const isAuthenticated = user !== null;

  const fetchUser = useCallback(async () => {
    // Public surfaces (auth entry/recovery, /invite/, and all /p/ pages such as
    // the review rating-gate and offer landing pages) are visited by anonymous
    // users. Probing /auth/me there would 401 and trip the axios interceptor's
    // hard redirect to /login, breaking those public flows. Skip the probe and
    // resolve to signed-out so the public page renders.
    if (isPublicPathname(window.location.pathname)) {
      setUser(null);
      setIsLoading(false);
      return;
    }

    // Auth tokens live in httpOnly cookies — JS can’t check for them. We just
    // probe /auth/me; if the cookie is missing or expired the response
    // interceptor will attempt a refresh, and a final 401 means signed-out.
    try {
      const userData = await getCurrentUser();
      setUser(userData);
    } catch {
      setUser(null);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void fetchUser();
    }, 0);

    return () => window.clearTimeout(timer);
  }, [fetchUser]);

  useEffect(() => {
    if (isLoading) return;

    const isPublicPath = isPublicPathname(pathname);

    if (!isAuthenticated && !isPublicPath) {
      // Preserve the deep link so signing in resumes it instead of dumping the
      // user on the dashboard having silently lost where they were going.
      router.replace(loginPathReturningTo(pathname));
    } else if (isAuthenticated && PUBLIC_PATHS.includes(pathname)) {
      // Only redirect away from explicit public paths (login/register), not
      // invite pages. Honour ?redirect= so this effect does not race the
      // post-login redirect and yank an invitee off their invitation page.
      router.replace(requestedRedirect() ?? "/");
    }
  }, [isAuthenticated, isLoading, pathname, router]);

  const login = useCallback(async (credentials: LoginCredentials, options?: LoginOptions) => {
    // Backend sets both access_token and refresh_token as httpOnly cookies on
    // the response; the body is ignored here. Subsequent requests carry the
    // cookies automatically (axios is configured with withCredentials).
    await loginApi(credentials);
    const userData = await getCurrentUser();
    setUser(userData);
    // Honour where the user was headed. "Sign in to Accept" on an invitation
    // sends them to /login?redirect=/invite/<token>; hard-coding "/" here
    // dropped them on the dashboard with the invitation still unaccepted.
    router.replace(options?.redirectTo ?? requestedRedirect() ?? "/");
  }, [router]);

  const logout = useCallback(() => {
    // Backend clears both auth cookies.
    api.post("/api/v1/auth/logout").catch(() => {});
    setUser(null);
    // Signing out *from an invitation* means "wrong account, let me switch" — the
    // only reason to be on that page signed in as someone else. Come back to it
    // after the next sign-in instead of stranding the invite unaccepted.
    const returnTo = pathname.startsWith("/invite/") ? pathname : null;
    router.replace(returnTo ? loginPathReturningTo(returnTo) : "/login");
  }, [pathname, router]);

  const value = useMemo(
    () => ({
      user,
      isLoading,
      isAuthenticated,
      workspaceId: user?.default_workspace_id ?? null,
      login,
      logout,
    }),
    [user, isLoading, isAuthenticated, login, logout]
  );

  return <AuthContext value={value}>{children}</AuthContext>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}
