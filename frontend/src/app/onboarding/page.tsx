"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { Calendar, Database, Rocket, Upload } from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { FormProvider, useForm } from "react-hook-form";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { WizardContainer } from "@/components/wizard/wizard-container";
import type { WizardStepDef } from "@/hooks/useWizard";
import {
  createCampaignFromCsv,
  onboard,
  parseCalcomUrl,
} from "@/lib/api/realtor";
import { markAutoRedirectedToOnboarding } from "@/lib/onboarding-status";
import { queryKeys } from "@/lib/query-keys";
import { getApiErrorMessage } from "@/lib/utils/errors";
import { useWorkspace } from "@/providers/workspace-provider";

import {
  ONBOARDING_DEFAULTS,
  STEP_FIELDS,
  onboardingSchema,
  type OnboardingFormValues,
  type OnboardingStepId,
} from "./_state";
import { CalcomStep } from "./_steps/calcom-step";
import { FubStep } from "./_steps/fub-step";
import { LeadsStep } from "./_steps/leads-step";
import {
  OnboardingExtrasProvider,
  useOnboardingExtras,
} from "./_steps/onboarding-context";
import { ReviewStep } from "./_steps/review-step";

const STEPS = [
  { id: "fub", label: "Connect CRM", icon: Database },
  { id: "calcom", label: "Calendar", icon: Calendar },
  { id: "leads", label: "Import Leads", icon: Upload },
  { id: "review", label: "Review & Launch", icon: Rocket },
] as const satisfies readonly WizardStepDef<OnboardingStepId>[];

function OnboardingFlow() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const { currentWorkspaceId } = useWorkspace();
  const extras = useOnboardingExtras();

  const form = useForm<OnboardingFormValues>({
    resolver: zodResolver(onboardingSchema),
    defaultValues: ONBOARDING_DEFAULTS,
    mode: "onTouched",
  });

  const [currentStepId, setCurrentStepId] =
    useState<OnboardingStepId>("fub");
  const [isSubmitting, setIsSubmitting] = useState(false);

  // Landing here (whether auto-redirected for a fresh workspace or arriving by
  // choice) counts as the one-time first-run nudge, so the app shell never
  // force-redirects back into the wizard and traps a user who wants to skip.
  useEffect(() => {
    if (currentWorkspaceId) {
      markAutoRedirectedToOnboarding(currentWorkspaceId);
    }
  }, [currentWorkspaceId]);

  const handleSkip = useCallback(() => {
    if (currentWorkspaceId) {
      markAutoRedirectedToOnboarding(currentWorkspaceId);
    }
    router.push("/today");
  }, [currentWorkspaceId, router]);

  const currentStepIndex = useMemo(
    () => STEPS.findIndex((s) => s.id === currentStepId),
    [currentStepId]
  );
  const isFirstStep = currentStepIndex === 0;
  const isLastStep = currentStepIndex === STEPS.length - 1;

  /**
   * Validate the step the user is about to leave. Returns true when the
   * user may advance. Form fields go through RHF/zod; the leads step has
   * a non-form invariant (csv OR fub import) we check by hand.
   */
  const canLeaveStep = useCallback(
    async (stepId: OnboardingStepId): Promise<boolean> => {
      const fields = STEP_FIELDS[stepId];
      if (fields.length > 0) {
        const ok = await form.trigger(fields);
        if (!ok) return false;
      }
      if (stepId === "leads") {
        if (!extras.csvFile && extras.fubImportCount === null) {
          extras.setLeadsError(
            "Import leads from Follow Up Boss or upload a CSV file."
          );
          return false;
        }
        extras.setLeadsError(null);
      }
      return true;
    },
    [form, extras]
  );

  const goToStep = useCallback(
    async (stepId: OnboardingStepId) => {
      const targetIndex = STEPS.findIndex((s) => s.id === stepId);
      if (targetIndex > currentStepIndex) {
        if (!(await canLeaveStep(currentStepId))) return;
      }
      setCurrentStepId(stepId);
    },
    [currentStepId, currentStepIndex, canLeaveStep]
  );

  const goNext = useCallback(async () => {
    if (!(await canLeaveStep(currentStepId))) return;
    const next = STEPS[currentStepIndex + 1];
    if (next) setCurrentStepId(next.id);
  }, [currentStepId, currentStepIndex, canLeaveStep]);

  const goPrevious = useCallback(() => {
    const prev = STEPS[currentStepIndex - 1];
    if (prev) setCurrentStepId(prev.id);
  }, [currentStepIndex]);

  const handleLaunch = useCallback(async () => {
    if (!currentWorkspaceId) {
      toast.error("No workspace found. Please log in again.");
      return;
    }
    if (!extras.csvFile && extras.fubImportCount === null) {
      toast.error("Please import leads first.");
      return;
    }

    const values = form.getValues();
    setIsSubmitting(true);
    try {
      const { event_type_id } = await parseCalcomUrl(
        values.calcom_booking_url,
        values.calcom_api_key
      );

      await onboard({
        calcom_api_key: values.calcom_api_key,
        calcom_event_type_id: event_type_id,
      });

      if (extras.csvFile) {
        await createCampaignFromCsv(currentWorkspaceId, extras.csvFile, {
          skipDuplicates: true,
          areaCode: values.area_code || undefined,
        });
      }

      // The onboard call created the workspace's first agent, so refresh the
      // setup probe immediately — otherwise the cold-start card/nav linger on
      // the cached "zero agents" result (finding RF-002).
      await queryClient.invalidateQueries({
        queryKey: queryKeys.agents.all(currentWorkspaceId),
      });

      toast.success("Campaign launched! Your leads are being contacted.");
      router.push("/dashboard");
    } catch (err) {
      toast.error(getApiErrorMessage(err, "Launch failed. Please try again."));
    } finally {
      setIsSubmitting(false);
    }
  }, [
    currentWorkspaceId,
    extras.csvFile,
    extras.fubImportCount,
    form,
    queryClient,
    router,
  ]);

  return (
    <FormProvider {...form}>
      <div className="flex min-h-screen flex-col items-center justify-center bg-background px-4 py-12">
        <div className="mb-3 flex w-full max-w-2xl justify-end">
          <Button variant="ghost" size="sm" onClick={handleSkip}>
            Skip for now
          </Button>
        </div>
        <div className="w-full max-w-2xl border rounded-xl overflow-hidden shadow-xl bg-card min-h-[640px] flex flex-col">
          <WizardContainer
            steps={STEPS}
            currentStepId={currentStepId}
            currentStepIndex={currentStepIndex}
            onStepClick={goToStep}
            isFirstStep={isFirstStep}
            isLastStep={isLastStep}
            onPrevious={goPrevious}
            onNext={goNext}
            onSubmit={handleLaunch}
            isSubmitting={isSubmitting}
            submitLabel="Launch Campaign"
            submittingLabel="Launching..."
            submitIcon={Rocket}
          >
            {currentStepId === "fub" && <FubStep />}
            {currentStepId === "calcom" && <CalcomStep />}
            {currentStepId === "leads" && <LeadsStep />}
            {currentStepId === "review" && <ReviewStep />}
          </WizardContainer>
        </div>
      </div>
    </FormProvider>
  );
}

export default function OnboardingPage() {
  return (
    <OnboardingExtrasProvider>
      <OnboardingFlow />
    </OnboardingExtrasProvider>
  );
}
