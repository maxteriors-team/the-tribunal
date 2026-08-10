/**
 * The dead-link screen is the one page whose whole audience is customers who
 * cannot ask us anything, so its copy is the feature. These pin the three
 * claims that are easy to regress by "tidying" the wording later.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DeadPublicLink } from "@/components/shared/dead-public-link";

describe("DeadPublicLink", () => {
  it("names what the link was meant to open", () => {
    render(<DeadPublicLink subject="proposal" />);

    // Rendered across JSX expressions, so a lost space would read
    // "proposalisn't" — exactly the bug the first screenshot caught.
    expect(
      screen.getByRole("heading", { name: "This proposal isn’t available." }),
    ).toBeInTheDocument();
  });

  it("uses the caller's subject rather than a hardcoded one", () => {
    render(<DeadPublicLink subject="invoice" />);

    expect(
      screen.getByRole("heading", { name: "This invoice isn’t available." }),
    ).toBeInTheDocument();
  });

  it("points the customer at the message the link came from", () => {
    // The only action available to someone holding a dead link. Without it the
    // page is a full stop.
    render(<DeadPublicLink subject="proposal" />);

    expect(
      screen.getByText(/reply to the text or email you received/i),
    ).toBeInTheDocument();
  });

  it("never claims the link expired", () => {
    // An expired quote still resolves and renders its own banner with the real
    // business's contact details, so "expired" here described a state that
    // cannot reach this screen and told people to wait for a renewal that was
    // never coming.
    render(<DeadPublicLink subject="proposal" />);

    expect(screen.queryByText(/expired/i)).not.toBeInTheDocument();
  });

  it("offers no retry affordance", () => {
    // Nothing about a deleted or truncated link improves on a second attempt.
    render(<DeadPublicLink subject="proposal" />);

    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });
});
