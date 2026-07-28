/**
 * The three lighting services a design can cover, and what each one promises.
 *
 * A rep photographs one house and may sell any combination: landscape fixtures,
 * year-round permanent track, seasonal Christmas — or all three on the same
 * photo. The toggle drives two things that must never drift apart:
 *
 * 1. **The palette** — only the selected services' products are drawable.
 * 2. **The client's value propositions** — each service argues for itself in its
 *    own terms. Landscape sells nightly curb appeal and safety; permanent sells
 *    never climbing a ladder again; Christmas sells a low-commitment season.
 *    Showing one generic list for a three-service quote is how a customer ends
 *    up thinking they're buying one thing.
 *
 * Copy is operator-editable in the pricing config (`landscape.perks`,
 * `permanent.perks`, `christmas.perks`); the fallbacks here only cover a
 * workspace that hasn't customized them.
 */
import type { PricingSettings } from "@/types/sales-wizard";

export type ServiceKey = "landscape" | "permanent" | "christmas";

export interface ServiceSpec {
  key: ServiceKey;
  /** Short label for the toggle. */
  label: string;
  /** Client-facing headline for this service's value-prop block. */
  headline: string;
  /** One line under the headline framing what the service is. */
  summary: string;
}

export const SERVICES: readonly ServiceSpec[] = [
  {
    key: "landscape",
    label: "Landscape",
    headline: "Architectural Landscape Lighting",
    summary:
      "Brass and copper fixtures lighting your home, trees, and walkways every night of the year.",
  },
  {
    key: "permanent",
    label: "Permanent",
    headline: "Permanent Roofline Lighting",
    summary:
      "Track installed once under the eaves — every color, every holiday, controlled from your phone.",
  },
  {
    key: "christmas",
    label: "Christmas",
    headline: "Seasonal Christmas Lighting",
    summary:
      "Professionally installed for the season, then taken down and stored for you.",
  },
] as const;

const SPEC_BY_KEY = new Map(SERVICES.map((spec) => [spec.key, spec]));

export function serviceSpec(key: ServiceKey): ServiceSpec {
  return SPEC_BY_KEY.get(key) ?? SERVICES[0];
}

/** Fallbacks for a workspace that hasn't edited its value propositions. */
const FALLBACK_PERKS: Record<ServiceKey, string[]> = {
  landscape: [
    "Your home is the one people notice on the street after dark",
    "Safe, lit walkways, steps, and driveway every night of the year",
    "A lit house is a harder target — no dark corners to hide in",
    "Low-voltage LED: pennies a night to run, decades of fixture life",
  ],
  permanent: [
    "Installed once — never put up or take down lights again",
    "App-controlled colors, scenes, and schedules year-round",
    "Works for every holiday, game day, and party — not just Christmas",
    "Hidden when off — a clean roofline in daylight",
  ],
  christmas: [
    "Lower upfront cost to get a festive look this season",
    "Professional install, takedown, and off-season storage handled for you",
    "Switch up the design or colors from year to year",
    "Nothing permanently attached to your home",
  ],
};

/**
 * The value propositions the homeowner reads for one service.
 *
 * Landscape additionally folds in the chosen package's own selling points, so a
 * Best-package customer reads about color-changing fixtures and a Good-package
 * customer does not — the pitch matches what they're actually buying.
 */
export function serviceValueProps(
  service: ServiceKey,
  pricing: PricingSettings | null | undefined,
  tierKey?: string | null,
): string[] {
  const configured =
    service === "landscape"
      ? pricing?.landscape?.perks
      : service === "permanent"
        ? pricing?.permanent?.perks
        : pricing?.christmas?.perks;

  const base = configured?.length ? [...configured] : [...FALLBACK_PERKS[service]];
  if (service !== "landscape") return base;

  const tier = (pricing?.tiers ?? []).find((t) => t.key === tierKey);
  const points = tier?.points ?? [];
  // Package points first: they are the most specific thing we can say.
  return [...points, ...base.filter((line) => !points.includes(line))];
}

/**
 * The client-facing theme for a set of services.
 *
 * The holiday palette (evergreen, holly, a garland of red/green bulbs across
 * the top) is right for a Christmas quote and wrong for everything else: a
 * homeowner buying year-round brass landscape lighting should not be shown a
 * Christmas page. So the theme follows what is actually being sold rather than
 * being a mode someone has to remember to switch.
 *
 * Returns the festive class only when Christmas is part of the offer; otherwise
 * the neutral brass-on-black base, which reads as premium architectural
 * lighting.
 */
export function clientThemeClass(services: readonly ServiceKey[]): string {
  return services.includes("christmas") ? "cmp-festive" : "";
}
