import type { MetadataRoute } from "next";

/**
 * The CRM stays out of every search index. The only exceptions are public
 * marketing pages, which exist to be found. `allow` must be listed before
 * `disallow` here; crawlers apply the most specific rule, so the narrower
 * allow wins over the blanket disallow for these paths only.
 *
 * Keep this in sync with `INDEXABLE_MARKETING_PATHS` in next.config.ts: the
 * HTTP `X-Robots-Tag` header there is what actually enforces noindex, and a
 * path allowed here but still sent that header will not be indexed.
 */
const INDEXABLE_MARKETING_PATHS = ["/p/landscape-lighting"];

export default function robots(): MetadataRoute.Robots {
  return {
    rules: [{ userAgent: "*", allow: INDEXABLE_MARKETING_PATHS, disallow: "/" }],
  };
}
