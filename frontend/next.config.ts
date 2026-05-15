import { withSentryConfig } from "@sentry/nextjs";
import type { NextConfig } from "next";

import { getBackendUrl } from "./src/lib/utils/backend-url";

const BACKEND_URL = getBackendUrl();

const nextConfig: NextConfig = {
  turbopack: { root: __dirname },
  async rewrites() {
    return [
      {
        // Proxy all API calls to the backend (avoids CORS issues)
        source: "/api/:path*",
        destination: `${BACKEND_URL}/api/:path*`,
      },
    ];
  },
};

export default withSentryConfig(nextConfig, {
  // Only print logs for uploading source maps in CI
  silent: !process.env.CI,
  // Upload a larger set of source maps for prettier stack traces (increases build time)
  widenClientFileUpload: true,
  // Automatically tree-shake Sentry logger statements to reduce bundle size
  disableLogger: true,
});
