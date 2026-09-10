import { pathToRegexp } from "path-to-regexp";
import { afterEach, describe, expect, it, vi } from "vitest";

/**
 * The marketing site builds this same frontend, so without the landing-only
 * redirect a homeowner arriving from an ad can reach the CRM login and every
 * authenticated route on a domain handed out in advertising.
 *
 * `LANDING_ONLY_SITE` is read at module load, so each case re-imports the
 * config with `vi.resetModules()` rather than mutating an already-loaded one.
 */

const LANDING_PAGE = "/p/landscape-lighting";

// Paths a visitor must be pulled off, because they are CRM surfaces.
const MUST_REDIRECT = ["/", "/login", "/contacts"];

// Paths the catch-all must leave alone. `/api/*` is the same-origin proxy the
// lead form posts through, so matching it here would silently break every
// submission while the page itself still looked fine.
const MUST_PASS_THROUGH = [
  LANDING_PAGE,
  "/api/v1/p/leads/x",
  "/_next/static/x",
  "/landscape-lighting/logo.png",
];

const ORIGINAL_FLAG = process.env.LANDING_ONLY_SITE;

async function loadRedirects(flag: string | undefined) {
  vi.resetModules();
  if (flag === undefined) {
    delete process.env.LANDING_ONLY_SITE;
  } else {
    process.env.LANDING_ONLY_SITE = flag;
  }
  const config = (await import("../../next.config")).default;
  return (await config.redirects?.()) ?? [];
}

afterEach(() => {
  if (ORIGINAL_FLAG === undefined) {
    delete process.env.LANDING_ONLY_SITE;
  } else {
    process.env.LANDING_ONLY_SITE = ORIGINAL_FLAG;
  }
});

describe("next.config landing-only mode", () => {
  it("adds a catch-all redirect to the landing page when LANDING_ONLY_SITE=1", async () => {
    const redirects = await loadRedirects("1");
    const catchAll = redirects.filter((entry) => entry.destination === LANDING_PAGE);

    expect(catchAll).toHaveLength(1);
    // Temporary: a 308 is cached almost permanently, which would strand this
    // hostname on the landing page if it is ever repurposed.
    expect(catchAll[0]?.permanent).toBe(false);
  });

  it.each(MUST_REDIRECT)("redirects %s away from the CRM", async (path) => {
    const redirects = await loadRedirects("1");
    const catchAll = redirects.find((entry) => entry.destination === LANDING_PAGE);

    // pathToRegexp is the matcher Next itself compiles `source` with.
    expect(pathToRegexp(catchAll!.source).test(path)).toBe(true);
  });

  it.each(MUST_PASS_THROUGH)("leaves %s reachable", async (path) => {
    const redirects = await loadRedirects("1");
    const catchAll = redirects.find((entry) => entry.destination === LANDING_PAGE);

    expect(pathToRegexp(catchAll!.source).test(path)).toBe(false);
  });

  it("adds no catch-all for the real CRM deployment", async () => {
    const redirects = await loadRedirects(undefined);

    expect(redirects.some((entry) => entry.destination === LANDING_PAGE)).toBe(false);
    // The unrelated redirects this config already carries must survive.
    expect(redirects.length).toBeGreaterThan(0);
  });

  it("treats any value other than 1 as the normal CRM deployment", async () => {
    const redirects = await loadRedirects("0");

    expect(redirects.some((entry) => entry.destination === LANDING_PAGE)).toBe(false);
  });
});
