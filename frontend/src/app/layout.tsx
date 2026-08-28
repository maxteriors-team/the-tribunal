import type { Metadata, Viewport } from "next";
import { Golos_Text } from "next/font/google";

import { Spotlight } from "@/components/effects/spotlight";
import { PRODUCT_BRAND } from "@/lib/brand";
import { Providers } from "@/providers/providers";
import "./globals.css";

import EZPixelClient from "../../ez-pixel.client";

// Golos Text is the Maxteriors brand face: maxteriorslighting.com loads it at
// weights 400–900 and uses nothing else. One variable family now covers both
// body and headings, so the app ships a single font instead of Inter + Manrope.
const golos = Golos_Text({
  variable: "--font-golos",
  subsets: ["latin"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "AI CRM - Unified Customer Communications",
  description: "AI-powered CRM for managing customer relationships through voice, SMS, and email",
  // This is a private CRM: nothing here should ever land in a search index.
  // Every route inherits this unless it explicitly overrides `robots`.
  robots: { index: false, follow: false, nocache: true },
  // iOS "Add to Home Screen" polish: full-screen standalone app with a
  // proper title under the icon (Android reads the same from manifest.ts).
  appleWebApp: {
    capable: true,
    statusBarStyle: "black-translucent",
    title: PRODUCT_BRAND.name,
  },
};

export const viewport: Viewport = {
  themeColor: "#0a0a0a",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body
        className={`${golos.variable} font-sans antialiased relative min-h-screen`}
      >
        <EZPixelClient />

        <Providers>
          <Spotlight className="fixed" />
          <div className="relative z-10">{children}</div>
        </Providers>
      </body>
    </html>
  );
}
