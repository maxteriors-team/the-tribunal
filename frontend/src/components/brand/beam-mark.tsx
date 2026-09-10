import { useId } from "react";

import { PRODUCT_BRAND } from "@/lib/brand";
import { cn } from "@/lib/utils";

interface BeamGlyphProps {
  className?: string;
}

/**
 * The BEAM glyph: a fixture throwing a cone of light.
 *
 * The bar takes `currentColor` so the mark inherits whatever surface it sits
 * on; the cone always renders in the brand amber so the "light" reads as light
 * on both the dark auth panel and the app's light chrome.
 */
export function BeamGlyph({ className }: BeamGlyphProps) {
  // Two marks on one page would otherwise share a gradient id and the second
  // would inherit the first one's stops.
  const coneId = useId();

  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
      className={cn("size-6", className)}
    >
      <defs>
        <linearGradient id={coneId} x1="12" y1="6" x2="12" y2="21" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="var(--primary)" stopOpacity="0.9" />
          <stop offset="1" stopColor="var(--primary)" stopOpacity="0.05" />
        </linearGradient>
      </defs>
      <path d="M8.6 6.6h6.8L21 20.6H3z" fill={`url(#${coneId})`} />
      <rect x="7" y="2.6" width="10" height="3.4" rx="1.7" fill="currentColor" />
    </svg>
  );
}

interface BeamWordmarkProps {
  className?: string;
  glyphClassName?: string;
}

/** Glyph plus wordmark, for headers and the auth surfaces. */
export function BeamWordmark({ className, glyphClassName }: BeamWordmarkProps) {
  return (
    <span className={cn("inline-flex items-center gap-2.5", className)}>
      <BeamGlyph className={glyphClassName} />
      <span className="text-xl font-semibold tracking-[0.18em]">{PRODUCT_BRAND.name}</span>
    </span>
  );
}
