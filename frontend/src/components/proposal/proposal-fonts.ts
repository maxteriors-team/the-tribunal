/**
 * Client-proposal typography — Cormorant Garamond (display) + Montserrat (UI),
 * self-hosted via `next/font/google` and exposed as CSS variables so
 * `proposal-theme.css` can reference them with no FOUT and no hashed class name.
 *
 * Spread `proposalFontVars` onto the `.proposal-view` root element.
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

/** Combined variable class to spread onto the `.proposal-view` root element. */
export const proposalFontVars = `${cormorant.variable} ${montserrat.variable}`;
