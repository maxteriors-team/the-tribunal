import { withSentryConfig } from "@sentry/nextjs";
import type { NextConfig } from "next";

import { getBackendUrl } from "./src/lib/utils/backend-url";

const BACKEND_URL = getBackendUrl();

// Security headers applied to every route. The app is a private CRM, so we
// also hard-block search indexing at the HTTP layer (belt-and-braces with
// app/robots.ts and the `robots` metadata in app/layout.tsx).
const SECURITY_HEADERS = [
  {
    key: "X-Robots-Tag",
    value: "noindex, nofollow, noarchive, nosnippet, noimageindex",
  },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  {
    key: "Permissions-Policy",
    value: "geolocation=(), microphone=(), camera=()",
  },
  {
    key: "Strict-Transport-Security",
    value: "max-age=63072000; includeSubDomains; preload",
  },
];

// Voice embeds need microphone access within their own document. The host
// iframe still has to delegate it explicitly with `allow="microphone"`.
const EMBED_SECURITY_HEADERS = SECURITY_HEADERS.map((header) =>
  header.key === "Permissions-Policy"
    ? { ...header, value: "geolocation=(), microphone=(self), camera=()" }
    : header,
);

// Production embeds require HTTPS parents. Local HTTP parents remain available
// in `next dev` so the real iframe flow can be exercised by Playwright.
const EMBED_FRAME_ANCESTORS =
  process.env.NODE_ENV === "development"
    ? "frame-ancestors http: https:"
    : "frame-ancestors https:";

const nextConfig: NextConfig = {
  serverExternalPackages: ["@prestyj/pixel"],
  turbopack: { root: __dirname },
  // Avatar image sources. Any host that may legitimately serve a user-supplied
  // avatar URL needs to be allow-listed for next/image. Add new hosts here
  // (rather than reaching for `unoptimized`) so we still get optimization +
  // CSP protection.
  images: {
    remotePatterns: [
      { protocol: "https", hostname: "www.gravatar.com", pathname: "/avatar/**" },
      { protocol: "https", hostname: "secure.gravatar.com", pathname: "/avatar/**" },
      { protocol: "https", hostname: "gravatar.com", pathname: "/avatar/**" },
      // Google profile images (used by OAuth login flows)
      { protocol: "https", hostname: "lh3.googleusercontent.com" },
      // Generic CDN-uploaded avatars
      { protocol: "https", hostname: "avatars.githubusercontent.com" },
      { protocol: "https", hostname: "*.public.blob.vercel-storage.com" },
      { protocol: "https", hostname: "*.amazonaws.com" },
      { protocol: "https", hostname: "*.r2.cloudflarestorage.com" },
    ],
  },
  async redirects() {
    return [
      {
        // /recurring-jobs was renamed to /service-plans. Reps keep the old URL
        // bookmarked and it is linked from older emails, so without this the
        // rename hands them a 404 instead of the page they asked for.
        //
        // Temporary (307) rather than permanent (308) on purpose: browsers cache
        // a 308 more or less forever, so if the route is ever renamed again or
        // /recurring-jobs is reused, anyone who hit the permanent version could
        // not reach it without clearing their cache. The cost of 307 is one
        // redirect hop on a stale bookmark.
        source: "/recurring-jobs",
        destination: "/service-plans",
        permanent: false,
      },
      {
        source: "/recurring-jobs/:path*",
        destination: "/service-plans/:path*",
        permanent: false,
      },
    ];
  },
  async rewrites() {
    return [
      {
        // Proxy all API calls to the backend (avoids CORS issues)
        source: "/api/:path*",
        destination: `${BACKEND_URL}/api/:path*`,
      },
    ];
  },
  async headers() {
    return [
      {
        // Everything except /embed/* : the dashboard must never be framable,
        // so we send both the legacy X-Frame-Options and the modern CSP
        // `frame-ancestors` directive.
        source: "/((?!embed).*)",
        headers: [
          ...SECURITY_HEADERS,
          { key: "X-Frame-Options", value: "DENY" },
          {
            key: "Content-Security-Policy",
            value: "frame-ancestors 'none'",
          },
        ],
      },
      {
        // DELIBERATE EXCEPTION - DO NOT "FIX" THIS.
        // /embed/[publicId] is the chat/voice widget that customers embed in
        // an <iframe> on their own websites. Sending X-Frame-Options: DENY or
        // frame-ancestors 'none' here would break every live customer embed.
        // Production parents must use HTTPS; backend domain validation still
        // authorizes each parent before any config or provider call succeeds.
        source: "/embed/:path*",
        headers: [
          ...EMBED_SECURITY_HEADERS,
          {
            key: "Content-Security-Policy",
            value: EMBED_FRAME_ANCESTORS,
          },
        ],
      },
    ];
  },
};

// Sentry release + source-map upload requires a server-side auth token. When
// ``SENTRY_AUTH_TOKEN`` isn't configured (e.g. preview / local builds, or
// production envs where the token hasn't been provisioned yet) the plugin
// emits two warnings per build ("Will not create release", "Will not upload
// source maps"). Detect that here and explicitly disable the source-maps
// pipeline so the build stays warning-free until a real token is wired up.
const SENTRY_HAS_AUTH_TOKEN = Boolean(process.env.SENTRY_AUTH_TOKEN);

export default withSentryConfig(nextConfig, {
  // Only print logs for uploading source maps in CI
  silent: !process.env.CI,
  // Upload a larger set of source maps for prettier stack traces (increases build time)
  widenClientFileUpload: true,
  sourcemaps: {
    disable: !SENTRY_HAS_AUTH_TOKEN,
  },
  // Automatically tree-shake Sentry logger statements to reduce bundle size.
  // (Moved from the top-level ``disableLogger`` to the new ``webpack.treeshake``
  // path so the build no longer emits the @sentry/nextjs deprecation warning.)
  webpack: {
    treeshake: {
      removeDebugLogging: true,
    },
  },
});
