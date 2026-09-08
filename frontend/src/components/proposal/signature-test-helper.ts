import { screen } from "@testing-library/react";

import type { ProposalSignature } from "@/lib/api/public-proposals";

/**
 * Just the two interactions this helper performs.
 *
 * Structural rather than `UserEvent`, so it accepts both the bare `userEvent`
 * export and a `userEvent.setup()` instance -- the suites use both, and their
 * full types differ in members this helper never touches.
 */
type TypingUser = {
  type: (element: Element, text: string) => Promise<unknown>;
  click: (element: Element) => Promise<unknown>;
};

/**
 * Complete the e-signature ceremony in a test.
 *
 * Shared by both proposal view suites so that a change to the ceremony breaks
 * one helper rather than twenty assertions, and so neither suite can silently
 * drift into testing a form the other no longer renders.
 */
export async function signProposal(
  user: TypingUser,
  name = "Dana Homeowner",
): Promise<ProposalSignature> {
  await user.type(screen.getByLabelText(/type your full name/i), name);
  await user.click(screen.getByRole("checkbox", { name: /cancellation terms|terms of this proposal/i }));
  await user.click(screen.getByRole("checkbox", { name: /sign electronically/i }));
  return {
    signedName: name,
    econsentAccepted: true,
    cancellationAcknowledged: true,
  };
}

/** The ceremony payload a completed `signProposal` produces. */
export const SIGNED: ProposalSignature = {
  signedName: "Dana Homeowner",
  econsentAccepted: true,
  cancellationAcknowledged: true,
};
