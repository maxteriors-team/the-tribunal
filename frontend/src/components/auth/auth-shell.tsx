import type { ReactNode } from "react";

import { BeamLightCanvas } from "@/components/auth/beam-light-canvas";
import { BeamWordmark } from "@/components/brand/beam-mark";

interface AuthShellProps {
  children: ReactNode;
}

/**
 * Shared frame for every unauthenticated surface (sign in, register, reset), so
 * the three pages stay one flow instead of three centred cards that drifted.
 *
 * Below `lg` the artwork drops out entirely and the wordmark carries the brand,
 * which keeps the form the first thing a phone shows above the fold.
 */
export function AuthShell({ children }: AuthShellProps) {
  return (
    <div className="grid min-h-screen lg:grid-cols-[1.05fr_1fr]">
      <BeamLightCanvas />
      <main className="flex flex-col items-center justify-center gap-8 px-4 py-12">
        <BeamWordmark className="lg:hidden" />
        <div className="w-full max-w-md">{children}</div>
      </main>
    </div>
  );
}
