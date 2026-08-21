"use client";

import type { LucideIcon } from "lucide-react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { type ReactNode } from "react";

import { ScrollArea } from "@/components/ui/scroll-area";
import type { WizardStepDef } from "@/hooks/useWizard";

import { WizardFooter } from "./wizard-footer";
import { WizardStepIndicator } from "./wizard-step-indicator";

interface WizardContainerProps<TStepId extends string> {
  steps: readonly WizardStepDef<TStepId>[];
  currentStepId: TStepId;
  currentStepIndex: number;
  onStepClick: (stepId: TStepId) => void;
  isFirstStep: boolean;
  isLastStep: boolean;
  onPrevious: () => void;
  onNext: () => void;
  onSubmit: () => void;
  isSubmitting?: boolean;
  onCancel?: () => void;
  submitLabel?: string;
  submittingLabel?: string;
  submitIcon?: LucideIcon;
  children: ReactNode;
}

export function WizardContainer<TStepId extends string>({
  steps,
  currentStepId,
  currentStepIndex,
  onStepClick,
  isFirstStep,
  isLastStep,
  onPrevious,
  onNext,
  onSubmit,
  isSubmitting,
  onCancel,
  submitLabel,
  submittingLabel,
  submitIcon,
  children,
}: WizardContainerProps<TStepId>) {
  const shouldReduceMotion = useReducedMotion();

  return (
    <div className="flex h-full min-w-0 flex-col">
      <WizardStepIndicator
        steps={steps}
        currentStepIndex={currentStepIndex}
        currentStepId={currentStepId}
        onStepClick={onStepClick}
      />
      <ScrollArea className="min-h-0 flex-1">
        <div className="mx-auto max-w-4xl p-4 sm:p-6">
          <AnimatePresence mode="wait">
            <motion.div
              key={currentStepId}
              initial={shouldReduceMotion ? false : { opacity: 0, x: 20 }}
              animate={{ opacity: 1, x: 0 }}
              exit={shouldReduceMotion ? { opacity: 1, x: 0 } : { opacity: 0, x: -20 }}
              transition={{ duration: shouldReduceMotion ? 0 : 0.2 }}
            >
              {children}
            </motion.div>
          </AnimatePresence>
        </div>
      </ScrollArea>
      <WizardFooter
        isFirstStep={isFirstStep}
        isLastStep={isLastStep}
        onPrevious={onPrevious}
        onNext={onNext}
        onSubmit={onSubmit}
        isSubmitting={isSubmitting}
        onCancel={onCancel}
        submitLabel={submitLabel}
        submittingLabel={submittingLabel}
        submitIcon={submitIcon}
      />
    </div>
  );
}
