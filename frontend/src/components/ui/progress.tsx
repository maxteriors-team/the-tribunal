"use client";

import * as ProgressPrimitive from "@radix-ui/react-progress";
import * as React from "react";

import { cn } from "@/lib/utils";

function Progress({
  className,
  value,
  max = 100,
  ...props
}: React.ComponentProps<typeof ProgressPrimitive.Root>) {
  const scale = max > 0 ? Math.min(1, Math.max(0, (value ?? 0) / max)) : 0;

  return (
    <ProgressPrimitive.Root
      data-slot="progress"
      value={value}
      max={max}
      className={cn("bg-primary/20 relative h-2 w-full overflow-hidden rounded-full", className)}
      {...props}
    >
      <ProgressPrimitive.Indicator
        data-slot="progress-indicator"
        className="bg-primary h-full w-full flex-1 origin-left transition-transform motion-reduce:transition-none rtl:origin-right"
        style={{ transform: `scaleX(${scale})` }}
      />
    </ProgressPrimitive.Root>
  );
}

export { Progress };
