import type { Metadata, Viewport } from "next";
import { Inter, Manrope } from "next/font/google";

import { Spotlight } from "@/components/effects/spotlight";
import { Providers } from "@/providers/providers";
import "./globals.css";

import EZPixelClient from "../../ez-pixel.client";

const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin"],
});

const manrope = Manrope({
  variable: "--font-manrope",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "AI CRM - Unified Customer Communications",
  description:
    "AI-powered CRM for managing customer relationships through voice, SMS, and email",
  // iOS "Add to Home Screen" polish: full-screen standalone app with a
  // proper title under the icon (Android reads the same from manifest.ts).
  appleWebApp: {
    capable: true,
    statusBarStyle: "black-translucent",
    title: "Maxteriors",
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
        className={`${inter.variable} ${manrope.variable} font-sans antialiased relative min-h-screen`}
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
