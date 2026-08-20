import { ArrowLeft, ArrowRight, Loader2, Send } from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { Button } from "@/components/ui/button";

interface WizardFooterProps {
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
}

export function WizardFooter({
  isFirstStep,
  isLastStep,
  onPrevious,
  onNext,
  onSubmit,
  isSubmitting = false,
  onCancel,
  submitLabel = "Submit",
  submittingLabel = "Creating...",
  submitIcon: SubmitIcon = Send,
}: WizardFooterProps) {
  return (
    <div className="flex flex-wrap items-center gap-2 border-t bg-background px-4 py-4 sm:px-6">
      <div className="mr-auto">
        {onCancel && (
          <Button variant="ghost" onClick={onCancel}>
            Cancel
          </Button>
        )}
      </div>
      <div className="ml-auto flex flex-wrap items-center justify-end gap-2">
        {!isFirstStep && (
          <Button className="shrink-0" variant="outline" onClick={onPrevious}>
            <ArrowLeft className="size-4 mr-2" />
            Previous
          </Button>
        )}
        {!isLastStep ? (
          <Button className="shrink-0" onClick={onNext}>
            Next
            <ArrowRight className="size-4 ml-2" />
          </Button>
        ) : (
          <Button className="shrink-0" onClick={onSubmit} disabled={isSubmitting}>
            {isSubmitting ? (
              <>
                <Loader2 className="size-4 mr-2 animate-spin" />
                {submittingLabel}
              </>
            ) : (
              <>
                <SubmitIcon className="size-4 mr-2" />
                {submitLabel}
              </>
            )}
          </Button>
        )}
      </div>
    </div>
  );
}
