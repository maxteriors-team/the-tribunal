import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Circle } from "lucide-react";
import { describe, expect, it, vi } from "vitest";

import { WizardStepIndicator } from "./wizard-step-indicator";

const steps = [
  { id: "basics", label: "Basics", icon: Circle },
  { id: "audience", label: "Audience", icon: Circle },
  { id: "review", label: "Review", icon: Circle },
] as const;

describe("WizardStepIndicator", () => {
  it("keeps mobile icon-only steps named and exposes current state", async () => {
    const user = userEvent.setup();
    const onStepClick = vi.fn();
    render(
      <WizardStepIndicator
        steps={steps}
        currentStepIndex={1}
        currentStepId="audience"
        onStepClick={onStepClick}
      />,
    );

    expect(screen.getByRole("navigation", { name: "Setup progress" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Step 1: Basics (completed)" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Step 2: Audience (current)" })).toHaveAttribute(
      "aria-current",
      "step",
    );
    expect(screen.getByRole("button", { name: "Step 3: Review (upcoming)" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Step 1: Basics (completed)" }));
    expect(onStepClick).toHaveBeenCalledWith("basics");
  });
});
