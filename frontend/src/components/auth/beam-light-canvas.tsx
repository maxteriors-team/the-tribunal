import { BeamWordmark } from "@/components/brand/beam-mark";
import { PRODUCT_BRAND } from "@/lib/brand";

/**
 * The lead field. Contacts sitting in the dark until the beam reaches them.
 *
 * Hardcoded rather than generated: `Math.random()` here would produce one field
 * on the server and a different one on the client and break hydration. `i` is
 * the resting opacity, falling off with distance from FOCUS, so the picture
 * reads as "these got lit, those are still waiting". The lower-left is kept
 * empty because the headline sits there, and nothing goes past x 560 because
 * the panel crops there on a laptop and a half-dot reads as a glitch.
 */
const LEADS: ReadonlyArray<{ cx: number; cy: number; r: number; i: number }> = [
  // In the pool, worked next.
  { cx: 448, cy: 596, r: 4, i: 0.92 },
  { cx: 424, cy: 700, r: 4, i: 0.84 },
  { cx: 350, cy: 600, r: 3.8, i: 0.78 },
  // Reached by the beam.
  { cx: 470, cy: 654, r: 4, i: 0.62 },
  { cx: 452, cy: 556, r: 3.6, i: 0.58 },
  { cx: 300, cy: 484, r: 3.6, i: 0.52 },
  { cx: 516, cy: 700, r: 3.4, i: 0.46 },
  { cx: 252, cy: 522, r: 3.4, i: 0.42 },
  // Still out in the dark.
  { cx: 556, cy: 604, r: 3.2, i: 0.32 },
  { cx: 336, cy: 440, r: 3, i: 0.28 },
  { cx: 548, cy: 478, r: 3.2, i: 0.24 },
  { cx: 152, cy: 456, r: 3, i: 0.22 },
  { cx: 88, cy: 512, r: 3, i: 0.18 },
];

/** Where the beam lands: the lead currently being worked. */
const FOCUS = { cx: 402, cy: 628 };

/**
 * Sign-in artwork: one beam finding leads in the dark.
 *
 * Decorative, so the whole panel is hidden from assistive technology. Every
 * word a screen reader needs is in the form column beside it.
 */
export function BeamLightCanvas() {
  return (
    <div className="relative hidden overflow-hidden bg-sidebar text-sidebar-foreground lg:flex lg:flex-col lg:justify-between">
      <svg
        viewBox="0 0 600 800"
        preserveAspectRatio="xMidYMid slice"
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 size-full"
      >
        <defs>
          {/* Reaches zero well above the cone's bottom edge, so the light fades
              out instead of ending on a visible straight cut. */}
          <linearGradient id="beam-throw" x1="300" y1="84" x2="366" y2="690" gradientUnits="userSpaceOnUse">
            <stop offset="0" stopColor="var(--primary)" stopOpacity="0.5" />
            <stop offset="0.3" stopColor="var(--primary)" stopOpacity="0.26" />
            <stop offset="0.55" stopColor="var(--primary)" stopOpacity="0.12" />
            <stop offset="0.78" stopColor="var(--primary)" stopOpacity="0.05" />
            <stop offset="0.95" stopColor="var(--primary)" stopOpacity="0" />
          </linearGradient>
          <radialGradient id="beam-hotspot">
            <stop offset="0" stopColor="var(--primary)" stopOpacity="0.72" />
            <stop offset="1" stopColor="var(--primary)" stopOpacity="0" />
          </radialGradient>
          <radialGradient id="beam-pool">
            <stop offset="0" stopColor="var(--primary)" stopOpacity="0.28" />
            <stop offset="1" stopColor="var(--primary)" stopOpacity="0" />
          </radialGradient>
          {/* Softens the cone's cut sides so it reads as light, not a polygon. */}
          <filter id="beam-soften" x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation="6" />
          </filter>
        </defs>

        {/* Sweep pivots at the fixture; the fade sits inside it so the two
            animations don't fight over one element's transform. The blur stays
            on the innermost group, letting the browser filter once and then
            just re-transform the cached result each frame. */}
        <g className="beam-sweep">
          <g className="beam-reveal">
            <ellipse cx="366" cy="656" rx="250" ry="64" fill="url(#beam-pool)" />
            <g filter="url(#beam-soften)">
              <path d="M266 84h68l254 622H144z" fill="url(#beam-throw)" />
              <circle cx="300" cy="94" r="104" fill="url(#beam-hotspot)" />
            </g>
          </g>
        </g>

        {/* The fixture the light comes from, and the pivot the sweep turns on. */}
        <rect x="264" y="70" width="72" height="14" rx="7" fill="var(--primary)" />

        {LEADS.map((lead) => (
          <circle
            key={`${lead.cx}-${lead.cy}`}
            cx={lead.cx}
            cy={lead.cy}
            r={lead.r}
            fill="var(--primary)"
            fillOpacity={lead.i}
            className="beam-lead"
            // Staggered left to right, so leads light up as the beam finds them.
            style={{ animationDelay: `${260 + lead.cx}ms` }}
          />
        ))}

        {/* The one lead in the middle of the pool, ringed like a live record. */}
        <g className="beam-lead" style={{ animationDelay: `${260 + FOCUS.cx}ms` }}>
          <circle cx={FOCUS.cx} cy={FOCUS.cy} r="19" fill="var(--primary)" fillOpacity="0.12" />
          <circle
            cx={FOCUS.cx}
            cy={FOCUS.cy}
            r="11"
            fill="none"
            stroke="var(--primary)"
            strokeOpacity="0.6"
          />
          <circle cx={FOCUS.cx} cy={FOCUS.cy} r="4.8" fill="var(--primary)" />
        </g>
      </svg>

      {/* Only the corner the headline occupies is darkened; the lit field stays. */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute bottom-0 left-0 h-1/2 w-1/2 bg-gradient-to-tr from-sidebar via-sidebar/45 to-transparent"
      />

      <div className="relative z-10 p-10 xl:p-14">
        <BeamWordmark glyphClassName="size-7 text-sidebar-foreground" />
      </div>

      <div className="relative z-10 max-w-sm p-10 xl:max-w-md xl:p-14">
        <p className="font-heading text-pretty text-4xl font-semibold tracking-tight text-sidebar-accent-foreground xl:text-5xl">
          {PRODUCT_BRAND.tagline}
        </p>
        <p className="mt-4 text-pretty text-base leading-relaxed text-sidebar-foreground/75">
          {PRODUCT_BRAND.description}
        </p>
      </div>
    </div>
  );
}
