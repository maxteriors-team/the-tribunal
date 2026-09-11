import type { CSSProperties } from "react";

/** Where the light comes from, and the point the sweep pivots on. */
const FIXTURE = { cx: 250, cy: 90 };

/**
 * Where the beam lands: the lead currently being worked.
 *
 * Low and left on purpose. The sign-in card is centred both ways, so the pool
 * sits below it and the throw passes beside it; a centred pool would hide the
 * busiest part of the picture behind the form.
 */
const FOCUS = { cx: 330, cy: 850 };

/**
 * The lead field. Contacts sitting in the dark until the beam reaches them.
 *
 * Hardcoded rather than generated: `Math.random()` here would produce one field
 * on the server and a different one on the client and break hydration. `i` is
 * the resting opacity, falling off with distance from the pool, so the picture
 * reads as "these got lit, those are still waiting".
 *
 * Everything lives low and left because the canvas is `slice`-cropped from the
 * top-left: a phone sees only that corner, while the dots trailing off to the
 * right exist to fill a wide desktop.
 */
const LEADS: ReadonlyArray<{ cx: number; cy: number; r: number; i: number }> = [
  // In the pool, worked next.
  { cx: 216, cy: 872, r: 5, i: 0.95 },
  { cx: 430, cy: 826, r: 4.6, i: 0.88 },
  { cx: 330, cy: 938, r: 4.4, i: 0.78 },
  // Reached by the beam.
  { cx: 128, cy: 792, r: 4.4, i: 0.6 },
  { cx: 520, cy: 902, r: 4.2, i: 0.54 },
  { cx: 268, cy: 748, r: 4, i: 0.5 },
  { cx: 452, cy: 736, r: 3.8, i: 0.44 },
  { cx: 60, cy: 900, r: 4, i: 0.4 },
  { cx: 620, cy: 800, r: 3.8, i: 0.36 },
  // Still out in the dark.
  { cx: 712, cy: 908, r: 3.6, i: 0.28 },
  { cx: 806, cy: 764, r: 3.6, i: 0.24 },
  { cx: 900, cy: 872, r: 3.4, i: 0.2 },
  { cx: 1012, cy: 796, r: 3.4, i: 0.17 },
  { cx: 1140, cy: 900, r: 3.2, i: 0.15 },
  { cx: 1268, cy: 780, r: 3.2, i: 0.13 },
  { cx: 1392, cy: 876, r: 3, i: 0.11 },
  { cx: 1508, cy: 806, r: 3, i: 0.1 },
];

/**
 * Per-dot animation timings.
 *
 * Twinkle and drift run on deliberately mismatched periods so the field never
 * visibly resynchronises into a single pulse. Derived from the index rather
 * than random, for the same hydration reason the positions are fixed.
 */
function leadMotion(index: number): CSSProperties {
  return {
    // Reveal stagger: leads light up outward from the middle of the pool.
    animationDelay: `${260 + index * 90}ms`,
    "--beam-twinkle-duration": `${3.1 + (index % 5) * 0.72}s`,
    "--beam-drift-duration": `${11 + (index % 4) * 3.4}s`,
    "--beam-phase": `-${index * 0.63}s`,
  } as CSSProperties;
}

/**
 * Sign-in artwork: one beam finding leads in the dark.
 *
 * Sits behind the whole auth surface. Anchored top-left rather than centred,
 * because a centred crop drops the fixture off a phone's narrow band entirely
 * and leaves only a stray corner glow.
 *
 * Decorative, so it is hidden from assistive technology. Every word a screen
 * reader needs is in the form on top of it.
 */
export function BeamLightCanvas() {
  return (
    <svg
      viewBox="0 0 1600 1000"
      preserveAspectRatio="xMinYMin slice"
      aria-hidden="true"
      className="pointer-events-none absolute inset-0 size-full"
    >
      <defs>
        {/* Reaches zero below the pool, so the light fades out instead of
            ending on a visible straight cut. */}
        <linearGradient
          id="beam-throw"
          x1={FIXTURE.cx}
          y1={FIXTURE.cy}
          x2={FOCUS.cx}
          y2="1000"
          gradientUnits="userSpaceOnUse"
        >
          <stop offset="0" stopColor="var(--primary)" stopOpacity="0.42" />
          <stop offset="0.35" stopColor="var(--primary)" stopOpacity="0.18" />
          <stop offset="0.65" stopColor="var(--primary)" stopOpacity="0.08" />
          <stop offset="0.88" stopColor="var(--primary)" stopOpacity="0.02" />
          <stop offset="1" stopColor="var(--primary)" stopOpacity="0" />
        </linearGradient>
        <radialGradient id="beam-hotspot">
          <stop offset="0" stopColor="var(--primary)" stopOpacity="0.7" />
          <stop offset="1" stopColor="var(--primary)" stopOpacity="0" />
        </radialGradient>
        <radialGradient id="beam-pool">
          <stop offset="0" stopColor="var(--primary)" stopOpacity="0.28" />
          <stop offset="1" stopColor="var(--primary)" stopOpacity="0" />
        </radialGradient>
        {/* Softens the cone's cut sides so it reads as light, not a polygon. */}
        <filter id="beam-soften" x="-50%" y="-50%" width="200%" height="200%">
          <feGaussianBlur stdDeviation="11" />
        </filter>
      </defs>

      {/* Sweep pivots at the fixture; the fade sits inside it so the two
          animations never fight over one element's transform. The blur stays on
          the innermost group, letting the browser filter once and then just
          re-transform the cached result each frame. */}
      <g className="beam-sweep">
        <g className="beam-reveal">
          <ellipse cx={FOCUS.cx} cy={FOCUS.cy} rx="520" ry="124" fill="url(#beam-pool)" />
          <g filter="url(#beam-soften)">
            <path d="M186 90h128l360 930H-140z" fill="url(#beam-throw)" />
            <circle cx={FIXTURE.cx} cy={FIXTURE.cy} r="170" fill="url(#beam-hotspot)" />
          </g>
        </g>
      </g>

      <rect x="190" y="74" width="120" height="18" rx="9" fill="var(--primary)" />

      {LEADS.map((lead, index) => (
        <g key={`${lead.cx}-${lead.cy}`} className="beam-lead" style={leadMotion(index)}>
          <circle
            cx={lead.cx}
            cy={lead.cy}
            r={lead.r}
            fill="var(--primary)"
            fillOpacity={lead.i}
            className="beam-star"
          />
        </g>
      ))}

      {/* The one lead in the middle of the pool, ringed like a live record. It
          holds still: it is the fixed point the drifting field reads against. */}
      <g className="beam-lead" style={{ animationDelay: "980ms" }}>
        <circle cx={FOCUS.cx} cy={FOCUS.cy} r="26" fill="var(--primary)" fillOpacity="0.12" />
        <circle
          cx={FOCUS.cx}
          cy={FOCUS.cy}
          r="15"
          fill="none"
          stroke="var(--primary)"
          strokeOpacity="0.6"
          strokeWidth="1.4"
        />
        <circle cx={FOCUS.cx} cy={FOCUS.cy} r="6.4" fill="var(--primary)" />
      </g>
    </svg>
  );
}
