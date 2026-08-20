import { Check } from "lucide-react";

import { HorizontalScroll } from "@/components/ui/horizontal-scroll";
import type { WizardStepDef } from "@/hooks/useWizard";

interface WizardStepIndicatorProps<TStepId extends string> {
  steps: readonly WizardStepDef<TStepId>[];
  currentStepIndex: number;
  currentStepId: TStepId;
  onStepClick: (stepId: TStepId) => void;
}

export function WizardStepIndicator<TStepId extends string>({
  steps,
  currentStepIndex,
  currentStepId,
  onStepClick,
}: WizardStepIndicatorProps<TStepId>) {
  return (
    <nav aria-label="Setup progress" className="border-b bg-muted/30 py-3">
      <HorizontalScroll
        activeKey={currentStepId}
        aria-label="Setup steps, scroll horizontally"
        data-testid="wizard-step-scroll"
        viewportClassName="px-4 sm:px-6"
      >
        <ol className="flex min-w-max items-center gap-2 pr-1">
          {steps.map((step, index) => {
            const Icon = step.icon;
            const isCompleted = index < currentStepIndex;
            const isCurrent = step.id === currentStepId;
            const stateLabel = isCurrent ? "current" : isCompleted ? "completed" : "upcoming";

            return (
              <li key={step.id}>
                <button
                  type="button"
                  onClick={() => onStepClick(step.id)}
                  aria-current={isCurrent ? "step" : undefined}
                  aria-label={`Step ${index + 1}: ${step.label} (${stateLabel})`}
                  className={`flex min-h-12 shrink-0 items-center gap-2 rounded-lg px-3 py-2 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 ${
                    isCurrent
                      ? "bg-primary text-primary-foreground"
                      : isCompleted
                        ? "text-primary hover:bg-primary/10"
                        : "text-muted-foreground hover:bg-muted"
                  }`}
                >
                  <span
                    aria-hidden="true"
                    className={`flex size-8 items-center justify-center rounded-full ${
                      isCurrent
                        ? "bg-primary-foreground/20"
                        : isCompleted
                          ? "bg-primary/20"
                          : "bg-muted"
                    }`}
                  >
                    {isCompleted ? <Check className="size-4" /> : <Icon className="size-4" />}
                  </span>
                  <span className="hidden text-sm font-medium lg:block">{step.label}</span>
                </button>
              </li>
            );
          })}
        </ol>
      </HorizontalScroll>
    </nav>
  );
}
