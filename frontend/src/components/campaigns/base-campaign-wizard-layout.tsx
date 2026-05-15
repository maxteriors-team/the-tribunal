"use client";

import type { ReactNode } from "react";
import type { LucideIcon } from "lucide-react";
import { Send } from "lucide-react";
import { WizardContainer } from "@/components/wizard";
import type { UseWizardReturn, WizardStepDef } from "@/hooks/useWizard";

export interface BaseCampaignWizardLayoutProps<
  TStepId extends string,
  TFormData extends object = Record<string, unknown>,
> {
  /** Steps array passed to WizardContainer (must match the wizard instance). */
  steps: readonly WizardStepDef<TStepId>[];
  /** Return value of useWizard() — provides all navigation state/callbacks. */
  wizard: UseWizardReturn<TStepId, TFormData>;
  /** Called when the user submits the final step. */
  onSubmit: () => void | Promise<void>;
  isSubmitting?: boolean;
  onCancel?: () => void;
  submitLabel?: string;
  submittingLabel?: string;
  submitIcon?: LucideIcon;
  children: ReactNode;
}

/**
 * Shared layout wrapper for campaign creation wizards.
 * Accepts a `wizard` return value and renders WizardContainer with the
 * correct navigation props wired up, so each wizard only owns its step
 * definitions and step content — not the container plumbing.
 */
export function BaseCampaignWizardLayout<
  TStepId extends string,
  TFormData extends object = Record<string, unknown>,
>({
  steps,
  wizard,
  onSubmit,
  isSubmitting = false,
  onCancel,
  submitLabel = "Create Campaign",
  submittingLabel,
  submitIcon = Send,
  children,
}: BaseCampaignWizardLayoutProps<TStepId, TFormData>) {
  return (
    <WizardContainer
      steps={steps}
      currentStepId={wizard.currentStepId}
      currentStepIndex={wizard.currentStepIndex}
      onStepClick={wizard.goToStep}
      isFirstStep={wizard.isFirstStep}
      isLastStep={wizard.isLastStep}
      onPrevious={wizard.goPrevious}
      onNext={wizard.goNext}
      onSubmit={onSubmit}
      isSubmitting={isSubmitting}
      onCancel={onCancel}
      submitLabel={submitLabel}
      submittingLabel={submittingLabel}
      submitIcon={submitIcon}
    >
      {children}
    </WizardContainer>
  );
}
