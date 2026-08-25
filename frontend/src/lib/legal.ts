export const TERMS_AND_CONDITIONS_URL =
  "https://maxteriorslighting.com/terms-and-conditions/";

const LEGACY_TERMS_PATHS = new Set(["/terms", "/terms/", "/terms-conditions", "/terms-conditions/"]);

/** Keep stored proposal/footer links on the canonical customer terms page. */
export function canonicalizeTermsUrl(href: string): string {
  try {
    const url = new URL(href);
    const hostname = url.hostname.toLowerCase().replace(/^www\./, "");
    if (hostname === "maxteriorslighting.com" && LEGACY_TERMS_PATHS.has(url.pathname)) {
      return TERMS_AND_CONDITIONS_URL;
    }
  } catch {
    return href;
  }
  return href;
}
