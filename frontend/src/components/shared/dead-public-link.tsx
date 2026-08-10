/**
 * What a customer sees when a public link no longer resolves.
 *
 * This is the only screen in the product whose entire audience is people who
 * are not our users and cannot ask us anything: a homeowner who was texted a
 * proposal, tapped it, and got nothing. The previous version was
 * `PageErrorState` on a black background — a dashboard component built for an
 * operator who can retry or navigate away. A customer can do neither, so it
 * read as "this company's software is broken" and ended the conversation.
 *
 * Three things this deliberately does NOT do:
 *
 * 1. **Name the business.** A token that no longer resolves has no workspace to
 *    look up — the row is gone. Inventing "Contact Maxteriors" here would put
 *    one tenant's name on every other tenant's dead link.
 * 2. **Offer a retry button.** Nothing about a deleted or mistyped link gets
 *    better on a second request; a button that always fails is worse than none.
 * 3. **Claim the link expired.** An expired quote still resolves and renders
 *    its own "this proposal has expired" banner with the real business's
 *    contact details. Saying "expired" here described a state that never
 *    reaches this screen, and sent people to wait for a renewal that was never
 *    coming.
 *
 * What is left is the truth (the link doesn't lead anywhere) plus the one
 * action that actually works: reply to the message it came from, which reaches
 * the business directly and is a channel the customer already has open.
 */
import { proposalFontVars } from "@/components/proposal/proposal-fonts";

import "@/components/proposal/proposal-theme.css";

interface DeadPublicLinkProps {
  /**
   * What the link was meant to open, lowercase, as a customer would say it —
   * "proposal", "invoice", "review request". Used mid-sentence.
   */
  subject: string;
}

export function DeadPublicLink({ subject }: DeadPublicLinkProps) {
  return (
    <div
      className={`proposal-view ${proposalFontVars} flex min-h-screen items-center justify-center px-6 py-16`}
    >
      {/* Spacing is `gap`, not margins: the proposal theme resets
          `.proposal-view * { margin: 0 }`, which out-specifies every Tailwind
          `mt-*` utility and silently crushed this layout into one block. */}
      <div
        className="w-full max-w-md text-center"
        style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: "1.25rem" }}
      >
        <div className="present-eyebrow">Link unavailable</div>

        <h1
          className="text-3xl leading-tight"
          style={{ fontFamily: "var(--font-cormorant), serif", color: "var(--t1)" }}
        >
          {/* Explicit space: JSX drops whitespace between an expression and a
              following line, which rendered this as "proposalisn't". */}
          This {subject}
          {" "}
          isn&rsquo;t available.
        </h1>

        <p className="text-sm leading-relaxed" style={{ color: "var(--t2)" }}>
          The link may have been changed or removed since it was sent, or it may
          have been cut short on its way to you.
        </p>

        {/* The whole point of the screen. A customer who got here still has the
            original text or email in front of them, and replying to it lands
            with the business that sent it. */}
        <p className="text-sm leading-relaxed" style={{ color: "var(--t2)" }}>
          Reply to the text or email you received and they can send you a new
          one.
        </p>

        <div
          className="h-px w-16"
          style={{ background: "var(--bdr-g)", marginTop: "1rem" }}
          aria-hidden="true"
        />
      </div>
    </div>
  );
}
