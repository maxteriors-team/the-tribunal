"use client";

import { Loader2, PhoneIncoming, PhoneOff } from "lucide-react";

import { Button } from "@/components/ui/button";
import { formatPhoneNumber } from "@/lib/utils/phone";

interface IncomingCallBannerProps {
  /** Caller's number exactly as Telnyx delivered it; formatted for display here. */
  callerNumber: string;
  /** The operator accepted and the microphone/media handshake is in flight. */
  isConnecting: boolean;
  onAccept: () => void;
  onDecline: () => void;
}

/**
 * The "a customer is ringing this browser" banner.
 *
 * Deliberately separate from `SoftphoneBar`: that bar narrates a call the
 * operator started, this one is an interruption they have to answer or refuse.
 * Once accepted the bar takes over and this unmounts.
 */
export function IncomingCallBanner({
  callerNumber,
  isConnecting,
  onAccept,
  onDecline,
}: IncomingCallBannerProps) {
  const caller = formatPhoneNumber(callerNumber) || "Unknown caller";
  const announcement = isConnecting
    ? `Connecting call from ${caller}.`
    : `Incoming call from ${caller}. Accept or decline.`;

  return (
    <section
      aria-label="Incoming call"
      className="fixed inset-x-4 bottom-4 z-50 mx-auto flex max-w-xl items-center gap-3 rounded-lg border border-border bg-background p-3 shadow-lg"
    >
      <div className="flex size-10 shrink-0 items-center justify-center rounded-md border bg-muted">
        {isConnecting ? (
          <Loader2 className="size-5 animate-spin motion-reduce:animate-none" aria-hidden="true" />
        ) : (
          <PhoneIncoming
            className="size-5 animate-pulse motion-reduce:animate-none"
            aria-hidden="true"
          />
        )}
      </div>

      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium">{caller}</p>
        <p className="truncate text-sm text-muted-foreground">
          {isConnecting ? "Connecting…" : "Incoming call"}
        </p>
      </div>

      {/* The banner itself mounts when the call arrives, so the live region is
          inserted (not merely updated) — which is what screen readers announce. */}
      <p aria-live="assertive" aria-atomic="true" className="sr-only">
        {announcement}
      </p>

      <div className="flex shrink-0 items-center gap-2">
        <Button type="button" size="sm" disabled={isConnecting} onClick={onAccept}>
          <PhoneIncoming className="mr-2 size-4" aria-hidden="true" />
          Accept
        </Button>
        {/* Stays enabled while connecting: a stalled microphone prompt must
            never leave the operator stuck in a banner with no way out. */}
        <Button type="button" variant="destructive" size="sm" onClick={onDecline}>
          <PhoneOff className="mr-2 size-4" aria-hidden="true" />
          Decline
        </Button>
      </div>
    </section>
  );
}
