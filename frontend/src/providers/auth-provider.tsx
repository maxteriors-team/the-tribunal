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
  login: (credentials: LoginCredentials) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

const PUBLIC_PATHS = ["/login", "/register"];
const PUBLIC_PATH_PREFIXES = ["/invite/", "/p/"];

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const router = useRouter();
  const pathname = usePathname();

  const isAuthenticated = user !== null;

  const fetchUser = useCallback(async () => {
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

    const isPublicPath =
      PUBLIC_PATHS.includes(pathname) ||
      PUBLIC_PATH_PREFIXES.some((prefix) => pathname.startsWith(prefix));

    if (!isAuthenticated && !isPublicPath) {
      router.replace("/login");
    } else if (isAuthenticated && PUBLIC_PATHS.includes(pathname)) {
      // Only redirect away from explicit public paths (login/register), not invite pages
      router.replace("/");
    }
  }, [isAuthenticated, isLoading, pathname, router]);

  const login = useCallback(async (credentials: LoginCredentials) => {
    // Backend sets both access_token and refresh_token as httpOnly cookies on
    // the response; the body is ignored here. Subsequent requests carry the
    // cookies automatically (axios is configured with withCredentials).
    await loginApi(credentials);
    const userData = await getCurrentUser();
    setUser(userData);
    router.replace("/");
  }, [router]);

  const logout = useCallback(() => {
    // Backend clears both auth cookies.
    api.post("/api/v1/auth/logout").catch(() => {});
    setUser(null);
    router.replace("/login");
  }, [router]);

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
