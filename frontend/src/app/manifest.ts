import type { MetadataRoute } from "next";

import { PRODUCT_BRAND } from "@/lib/brand";

/**
 * PWA manifest — makes the CRM installable from the browser
 * (iOS: Share → Add to Home Screen; Android: Install app prompt).
 * Crews get a full-screen, app-like experience with the dashboard
 * as the entry point.
 */
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: `${PRODUCT_BRAND.name} CRM`,
    short_name: PRODUCT_BRAND.shortName,
    description: PRODUCT_BRAND.description,
    start_url: "/dashboard",
    display: "standalone",
    background_color: "#0a0a0a",
    theme_color: "#0a0a0a",
    icons: [
      { src: "/icon-192.png", sizes: "192x192", type: "image/png" },
      {
        src: "/icon-512.png",
        sizes: "512x512",
        type: "image/png",
        purpose: "any",
      },
    ],
  };
}
