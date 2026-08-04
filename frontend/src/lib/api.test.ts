import type { AxiosAdapter, AxiosResponse, InternalAxiosRequestConfig } from "axios";
import { AxiosHeaders } from "axios";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api, apiGet, logout } from "@/lib/api";

// --- Test helpers --------------------------------------------------------

type Responder = (config: InternalAxiosRequestConfig) => Promise<AxiosResponse> | AxiosResponse;

function makeResponse(
  config: InternalAxiosRequestConfig,
  status: number,
  data: unknown = {},
): AxiosResponse {
  return {
    data,
    status,
    statusText: status === 200 ? "OK" : "Error",
    headers: {},
    config,
  };
}

function makeAxiosError(
  config: InternalAxiosRequestConfig,
  status: number,
): Error & { response: AxiosResponse; config: InternalAxiosRequestConfig; isAxiosError: true } {
  const err = new Error(`Request failed with status code ${status}`) as Error & {
    response: AxiosResponse;
    config: InternalAxiosRequestConfig;
    isAxiosError: true;
  };
  err.response = makeResponse(config, status);
  err.config = config;
  err.isAxiosError = true;
  return err;
}

function installAdapter(responder: Responder): AxiosAdapter {
  const adapter: AxiosAdapter = async (config) => {
    return responder(config as InternalAxiosRequestConfig);
  };
  api.defaults.adapter = adapter;
  return adapter;
}

// --- Setup ---------------------------------------------------------------

const originalAdapter = api.defaults.adapter;
const originalHref = window.location.href;

beforeEach(() => {
  // Reset any href changes made by logout()
  window.history.replaceState({}, "", "/");
  vi.spyOn(console, "error").mockImplementation(() => {});
});

afterEach(() => {
  api.defaults.adapter = originalAdapter;
  vi.restoreAllMocks();
  window.history.replaceState({}, "", originalHref);
});

// --- Tests ---------------------------------------------------------------

describe("api response interceptor", () => {
  it("passes through successful responses", async () => {
    installAdapter((config) => makeResponse(config, 200, { ok: true }));

    const data = await apiGet<{ ok: boolean }>("/api/v1/health");

    expect(data).toEqual({ ok: true });
  });

  it("refreshes the access token on 401 and retries the original request", async () => {
    const calls: string[] = [];
    let firstHealthCall = true;

    installAdapter((config) => {
      const url = config.url ?? "";
      calls.push(`${(config.method ?? "get").toUpperCase()} ${url}`);

      if (url.includes("/api/v1/auth/refresh")) {
        return makeResponse(config, 200, {});
      }
      if (url.includes("/api/v1/health")) {
        if (firstHealthCall) {
          firstHealthCall = false;
          throw makeAxiosError(config, 401);
        }
        return makeResponse(config, 200, { ok: true });
      }
      throw makeAxiosError(config, 404);
    });

    const data = await apiGet<{ ok: boolean }>("/api/v1/health");

    expect(data).toEqual({ ok: true });
    expect(calls).toEqual([
      "GET /api/v1/health",
      "POST /api/v1/auth/refresh",
      "GET /api/v1/health",
    ]);
  });

  it("queues concurrent 401s while a refresh is in flight, then drains them", async () => {
    const calls: string[] = [];
    const retriedUrls = new Set<string>();
    let refreshResolve: (() => void) | null = null;
    const refreshPromise = new Promise<void>((resolve) => {
      refreshResolve = resolve;
    });

    installAdapter((config) => {
      const url = config.url ?? "";
      const method = (config.method ?? "get").toUpperCase();
      calls.push(`${method} ${url}`);

      if (url.includes("/api/v1/auth/refresh")) {
        return refreshPromise.then(() => makeResponse(config, 200, {}));
      }

      // Retried call (after refresh) succeeds; first call fails.
      if (retriedUrls.has(url)) {
        return makeResponse(config, 200, { url });
      }
      retriedUrls.add(url);
      throw makeAxiosError(config, 401);
    });

    const aPromise = apiGet<{ url: string }>("/api/v1/a");
    const bPromise = apiGet<{ url: string }>("/api/v1/b");

    // Let the first 401s land and the interceptor enqueue.
    await Promise.resolve();
    await Promise.resolve();

    // Unblock the refresh.
    expect(refreshResolve).not.toBeNull();
    refreshResolve!();

    const [a, b] = await Promise.all([aPromise, bPromise]);
    expect(a).toEqual({ url: "/api/v1/a" });
    expect(b).toEqual({ url: "/api/v1/b" });

    // Exactly one refresh should have happened across both concurrent calls.
    const refreshCount = calls.filter((c) => c.includes("/api/v1/auth/refresh")).length;
    expect(refreshCount).toBe(1);
  });

  it("redirects to /login when refresh itself fails", async () => {
    installAdapter((config) => {
      const url = config.url ?? "";

      if (url.includes("/api/v1/auth/refresh")) {
        throw makeAxiosError(config, 401);
      }
      if (url.includes("/api/v1/auth/logout")) {
        return makeResponse(config, 200, {});
      }
      throw makeAxiosError(config, 401);
    });

    // jsdom's location.href setter just records the value.
    const hrefSetter = vi.fn();
    Object.defineProperty(window, "location", {
      configurable: true,
      value: new Proxy(window.location, {
        set(target, prop, value) {
          if (prop === "href") {
            hrefSetter(value);
            return true;
          }
          (target as unknown as Record<string | symbol, unknown>)[prop] = value;
          return true;
        },
      }),
    });

    await expect(apiGet("/api/v1/protected")).rejects.toThrow();

    expect(hrefSetter).toHaveBeenCalledWith("/login");
  });

  it("does not attempt to refresh when the refresh endpoint itself returns 401", async () => {
    const calls: string[] = [];
    installAdapter((config) => {
      const url = config.url ?? "";
      calls.push(url);
      throw makeAxiosError(config, 401);
    });

    await expect(
      api.post("/api/v1/auth/refresh", undefined, {
        // Bypass the logout side-effect: just assert the 401 propagates without
        // a second refresh attempt.
        headers: new AxiosHeaders(),
      }),
    ).rejects.toThrow();

    // Only the single refresh call — no recursive retry.
    const refreshCalls = calls.filter((c) => c.includes("/api/v1/auth/refresh"));
    expect(refreshCalls.length).toBe(1);
  });

  it("propagates non-401 errors without attempting refresh", async () => {
    const calls: string[] = [];
    installAdapter((config) => {
      const url = config.url ?? "";
      calls.push(url);
      throw makeAxiosError(config, 500);
    });

    await expect(apiGet("/api/v1/boom")).rejects.toThrow();

    expect(calls).toEqual(["/api/v1/boom"]);
    expect(calls.some((c) => c.includes("/api/v1/auth/refresh"))).toBe(false);
  });
});

/** Spy on `window.location.href` assignments while pretending to be at `at`. */
function captureHrefAt(at: string): ReturnType<typeof vi.fn> {
  window.history.replaceState({}, "", at);
  const hrefSetter = vi.fn();
  Object.defineProperty(window, "location", {
    configurable: true,
    value: new Proxy(window.location, {
      set(target, prop, value) {
        if (prop === "href") {
          hrefSetter(value);
          return true;
        }
        (target as unknown as Record<string | symbol, unknown>)[prop] = value;
        return true;
      },
    }),
  });
  return hrefSetter;
}

describe("logout()", () => {
  it("calls the logout endpoint and redirects to /login", async () => {
    const postSpy = vi.spyOn(api, "post").mockResolvedValue({ data: {} } as AxiosResponse);
    const hrefSetter = captureHrefAt("/");

    logout();

    expect(postSpy).toHaveBeenCalledWith("/api/v1/auth/logout");
    expect(hrefSetter).toHaveBeenCalledWith("/login");
  });

  it("preserves the current location so sign-in can resume it", () => {
    // This path fires on the 401 from a signed-out deep link and hard-navigates,
    // beating the auth provider's own guard. Dropping the destination here is
    // what turned an opened invitation into "dashboard, invite still pending".
    vi.spyOn(api, "post").mockResolvedValue({ data: {} } as AxiosResponse);
    const hrefSetter = captureHrefAt("/invite/tok123");

    logout();

    expect(hrefSetter).toHaveBeenCalledWith("/login?redirect=%2Finvite%2Ftok123");
  });

  it("keeps the query string of the interrupted destination", () => {
    vi.spyOn(api, "post").mockResolvedValue({ data: {} } as AxiosResponse);
    const hrefSetter = captureHrefAt("/contacts?view=leads");

    logout();

    expect(hrefSetter).toHaveBeenCalledWith("/login?redirect=%2Fcontacts%3Fview%3Dleads");
  });

  it("does not redirect at all when already on /login", () => {
    // Guards the infinite reload loop: /login 401s on first paint.
    vi.spyOn(api, "post").mockResolvedValue({ data: {} } as AxiosResponse);
    const hrefSetter = captureHrefAt("/login");

    logout();

    expect(hrefSetter).not.toHaveBeenCalled();
  });
});
