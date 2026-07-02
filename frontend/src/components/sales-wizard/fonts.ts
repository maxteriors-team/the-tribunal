/**
 * Sales-wizard typography — loaded via `next/font` for zero FOUT.
 *
 * The uploaded landscape-lighting wizard used Cormorant Garamond (display) +
 * Montserrat (UI) from a Google Fonts `<link>`. We keep the exact same faces but
 * self-host them through `next/font/google`, exposing them as CSS variables so
 * the ported stylesheet (`theme.css`) can reference them without a hashed class
 * name. Applied by adding `cormorant.variable` + `montserrat.variable` to the
 * `.sales-wizard` (and public proposal) container.
 */
import { Cormorant_Garamond, Montserrat } from "next/font/google";

export const cormorant = Cormorant_Garamond({
  variable: "--font-cormorant",
  subsets: ["latin"],
  weight: ["300", "400", "600"],
  style: ["normal", "italic"],
  display: "swap",
});

export const montserrat = Montserrat({
  variable: "--font-montserrat",
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  display: "swap",
});

/** Combined variable class to spread onto the wizard/proposal root element. */
export const salesWizardFontVars = `${cormorant.variable} ${montserrat.variable}`;
