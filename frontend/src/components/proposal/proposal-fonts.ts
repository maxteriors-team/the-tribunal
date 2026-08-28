/**
 * Client-proposal typography — Golos Text, the Maxteriors brand face.
 *
 * The page previously paired Cormorant Garamond (display serif) with Montserrat
 * (UI). That serif read as a different company from the heavy geometric logo
 * sitting directly above it, so both roles now resolve to the one brand family
 * that maxteriorslighting.com uses; weight carries the display/UI distinction
 * instead of a second typeface.
 *
 * `proposal-theme.css` maps its historical `--font-cormorant` / `--font-montserrat`
 * variables onto this one, so the ~40 rules referencing them keep working and
 * this file stays the single place the proposal's typeface is decided.
 *
 * Spread `proposalFontVars` onto the `.proposal-view` root element.
 */
import { Golos_Text } from "next/font/google";

export const golos = Golos_Text({
  variable: "--font-golos-proposal",
  subsets: ["latin"],
  display: "swap",
});

/** Variable class to spread onto the `.proposal-view` root element. */
export const proposalFontVars = golos.variable;
