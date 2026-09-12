import type { ReactNode } from "react";

import { BeamLightCanvas } from "@/components/auth/beam-light-canvas";
import { BeamWordmark } from "@/components/brand/beam-mark";
import { PRODUCT_BRAND } from "@/lib/brand";

interface AuthShellProps {
  children: ReactNode;
}

/**
 * Shared frame for every unauthenticated surface (sign in, register, reset), so
 * the three pages stay one flow instead of three cards that drifted apart.
 *
 * The artwork is the full background at every width, with the form floating on
 * top of it. The card keeps its own solid surface, so contrast against the text
 * inside it never depends on whatever the beam is doing behind it.
 */
export function AuthShell({ children }: AuthShellProps) {
  return (
    <div className="relative min-h-screen overflow-hidden bg-sidebar text-sidebar-foreground">
      <BeamLightCanvas />

      {/* Holds the copy legible over the brightest part of the throw. */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 bg-gradient-to-b from-sidebar/80 via-sidebar/30 to-sidebar/85"
      />

      <main className="relative z-10 flex min-h-screen flex-col items-center justify-center gap-10 px-4 py-14">
        <div className="flex flex-col items-center gap-3 text-center">
          <BeamWordmark glyphClassName="size-7" />
          <p className="font-heading text-pretty text-3xl font-semibold tracking-tight text-sidebar-accent-foreground sm:text-4xl">
            {PRODUCT_BRAND.tagline}
          </p>
          <p className="max-w-md text-pretty text-sm leading-relaxed text-sidebar-foreground/75 sm:text-base">
            {PRODUCT_BRAND.description}
          </p>
        </div>

        <div className="w-full max-w-md">{children}</div>
      </main>
    </div>
  );
}
