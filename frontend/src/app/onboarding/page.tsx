"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { Calendar, Rocket, Upload } from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
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
import {
  LaunchResultView,
  type OnboardingLaunchSummary,
} from "./_steps/launch-result";
import { LeadsStep } from "./_steps/leads-step";
import {
  OnboardingExtrasProvider,
  useOnboardingExtras,
} from "./_steps/onboarding-context";
import { ReviewStep } from "./_steps/review-step";

const STEPS = [
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
    useState<OnboardingStepId>("calcom");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [launchSummary, setLaunchSummary] =
    useState<OnboardingLaunchSummary | null>(null);
  // Onboarding (agent + credentials + best-effort phone purchase) is idempotent
  // only on the client side via this ref, so a retry after the no-phone warning
  // doesn't create a second agent.
  const onboardedRef = useRef(false);
  const phoneProvisionedRef = useRef(false);
  const [showPhoneWarning, setShowPhoneWarning] = useState(false);

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
   * a non-form invariant (csv upload) we check by hand.
   */
  const canLeaveStep = useCallback(
    async (stepId: OnboardingStepId): Promise<boolean> => {
      const fields = STEP_FIELDS[stepId];
      if (fields.length > 0) {
        const ok = await form.trigger(fields);
        if (!ok) return false;
      }
      if (stepId === "leads") {
        if (!extras.csvFile) {
          extras.setLeadsError("Upload a CSV file of your customers.");
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
    if (!extras.csvFile) {
      toast.error("Please import leads first.");
      return;
    }

    const values = form.getValues();
    setIsSubmitting(true);
    try {
      if (!onboardedRef.current) {
        const { event_type_id } = await parseCalcomUrl(
          values.calcom_booking_url,
          values.calcom_api_key
        );

        const onboardResult = await onboard({
          calcom_api_key: values.calcom_api_key,
          calcom_event_type_id: event_type_id,
          area_code: values.area_code || undefined,
        });
        onboardedRef.current = true;
        phoneProvisionedRef.current = onboardResult.phone_provisioned;

        // The onboard call created the workspace's first agent, so refresh the
        // setup probe immediately — otherwise the cold-start card/nav linger on
        // the cached "zero agents" result (finding RF-002).
        await queryClient.invalidateQueries({
          queryKey: queryKeys.agents.all(currentWorkspaceId),
        });
      }

      // A CSV launch sends SMS, so it can't start without an SMS-capable number.
      // Telnyx auto-purchase is best-effort and silently returns none when the
      // key is missing or the area code has no inventory, so surface that here
      // with a fix path instead of dying at the campaign call with a cryptic
      // "No active SMS-enabled phone number found" error (finding RF-008). On a
      // retry (warning already shown) we attempt the launch so a number added
      // in Settings is picked up; the catch below re-surfaces if it's still
      // missing.
      if (extras.csvFile && !phoneProvisionedRef.current && !showPhoneWarning) {
        setShowPhoneWarning(true);
        toast.error(
          "We couldn't get you an SMS number automatically — add one to start texting."
        );
        return;
      }

      const result = await createCampaignFromCsv(
        currentWorkspaceId,
        extras.csvFile,
        {
          skipDuplicates: true,
          areaCode: values.area_code || undefined,
        }
      );
      const summary: OnboardingLaunchSummary = {
        source: "csv",
        imported: result.contacts_imported,
        skipped: result.contacts_skipped,
        failed: result.contacts_failed,
        estimated: extras.csvRowCount,
      };

      // Show the real import result instead of a blind "all good" toast +
      // redirect, so silent data loss (e.g. failed rows) is visible (RF-007).
      const toastDetail = [
        `${summary.imported} imported`,
        summary.skipped > 0 ? `${summary.skipped} skipped` : null,
        summary.failed > 0 ? `${summary.failed} failed` : null,
      ]
        .filter(Boolean)
        .join(" · ");
      if (summary.failed > 0 || summary.imported === 0) {
        toast.warning(`Campaign launched — ${toastDetail}`);
      } else {
        toast.success(`Campaign launched — ${toastDetail}`);
      }
      setShowPhoneWarning(false);
      setLaunchSummary(summary);
    } catch (err) {
      const message = getApiErrorMessage(
        err,
        "Launch failed. Please try again."
      );
      // Backend hard-fails the CSV launch when no SMS number exists; translate
      // that into the same actionable warning rather than a cryptic toast.
      if (/SMS-enabled phone number/i.test(message)) {
        phoneProvisionedRef.current = false;
        setShowPhoneWarning(true);
        toast.error(
          "We couldn't get you an SMS number automatically — add one to start texting."
        );
      } else {
        toast.error(message);
      }
    } finally {
      setIsSubmitting(false);
    }
  }, [
    currentWorkspaceId,
    extras.csvFile,
    extras.csvRowCount,
    form,
    queryClient,
    showPhoneWarning,
  ]);

  const goToDashboard = useCallback(() => {
    router.push("/dashboard");
  }, [router]);

  if (launchSummary) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center bg-background px-4 py-12">
        <div className="w-full max-w-2xl border rounded-xl overflow-hidden shadow-xl bg-card flex flex-col">
          <LaunchResultView
            summary={launchSummary}
            onGoToDashboard={goToDashboard}
          />
        </div>
      </div>
    );
  }

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
            {currentStepId === "calcom" && <CalcomStep />}
            {currentStepId === "leads" && <LeadsStep />}
            {currentStepId === "review" && (
              <ReviewStep showPhoneWarning={showPhoneWarning} />
            )}
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
