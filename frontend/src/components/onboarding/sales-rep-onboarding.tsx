"use client";

import {
  BadgeCheck,
  CalendarDays,
  CheckCircle2,
  CircleUserRound,
  Clock3,
  ExternalLink,
  ListChecks,
  Loader2,
  MessageSquareText,
  Rocket,
  UserRound,
} from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { GoogleCalendarCard } from "@/components/settings/google-calendar-card";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { WizardContainer } from "@/components/wizard/wizard-container";
import { useIsMounted } from "@/hooks/useMounted";
import { useWizard, type WizardStepDef } from "@/hooks/useWizard";
import {
  markAutoRedirectedToSalesRepOnboarding,
  markSalesRepOnboardingCompleted,
} from "@/lib/sales-rep-onboarding-status";
import { useAuth } from "@/providers/auth-provider";
import { useWorkspace } from "@/providers/workspace-provider";

type SalesOnboardingStep = "welcome" | "profile" | "calendar" | "workflow" | "ready";

const SALES_ONBOARDING_STEPS: readonly WizardStepDef<SalesOnboardingStep>[] = [
  { id: "welcome", label: "Welcome", icon: Rocket },
  { id: "profile", label: "Profile", icon: CircleUserRound },
  { id: "calendar", label: "Calendar", icon: CalendarDays },
  { id: "workflow", label: "Daily flow", icon: ListChecks },
  { id: "ready", label: "Ready", icon: BadgeCheck },
];

const VALID_STEPS = new Set<SalesOnboardingStep>(SALES_ONBOARDING_STEPS.map((step) => step.id));

function SalesOnboardingLoading() {
  return (
    <div className="flex min-h-svh items-center justify-center bg-background" role="status">
      <Loader2 className="size-6 animate-spin text-muted-foreground" aria-hidden="true" />
      <span className="sr-only">Loading sales rep setup</span>
    </div>
  );
}

function WelcomeStep({ firstName, workspaceName }: { firstName: string; workspaceName: string }) {
  const rhythm = [
    {
      title: "Start in Today",
      description:
        "Review new replies, due follow-ups, and appointments before opening other pages.",
    },
    {
      title: "Work your assigned opportunities",
      description: "Keep the stage current and leave a clear next task after every customer touch.",
    },
    {
      title: "Close the loop",
      description:
        "Call or text from the contact record, then confirm the next appointment or follow-up.",
    },
  ];

  return (
    <section aria-labelledby="sales-welcome-title" className="space-y-7">
      <div className="max-w-2xl">
        <h1 id="sales-welcome-title" className="text-2xl font-bold tracking-tight sm:text-3xl">
          Welcome to {workspaceName}, {firstName}
        </h1>
        <p className="mt-3 text-muted-foreground">
          This walkthrough gets your identity, calendar, and daily sales rhythm ready before your
          first live lead.
        </p>
      </div>

      <div>
        <h2 className="text-base font-semibold">Your daily rhythm</h2>
        <ol className="mt-3 divide-y rounded-lg border" aria-label="Daily sales rhythm">
          {rhythm.map((item, index) => (
            <li key={item.title} className="grid grid-cols-[2rem_1fr] gap-3 p-4 sm:p-5">
              <span
                className="flex size-8 items-center justify-center rounded-full border text-sm font-semibold"
                aria-hidden="true"
              >
                {index + 1}
              </span>
              <div>
                <h3 className="font-medium">{item.title}</h3>
                <p className="mt-1 text-sm text-muted-foreground">{item.description}</p>
              </div>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}

function ProfileStep({ fullName, email }: { fullName: string | null; email: string }) {
  return (
    <section aria-labelledby="sales-profile-title" className="space-y-6">
      <div className="max-w-2xl">
        <h1 id="sales-profile-title" className="text-2xl font-bold tracking-tight">
          Make your activity recognizable
        </h1>
        <p className="mt-2 text-muted-foreground">
          Your name appears on assigned work and team activity. Add a mobile number and confirm your
          timezone so handoffs reach the right person at the right time.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Your account</CardTitle>
          <CardDescription>Review these details before working a customer.</CardDescription>
        </CardHeader>
        <CardContent>
          <dl className="divide-y rounded-lg border">
            <div className="grid gap-1 p-4 sm:grid-cols-[9rem_1fr] sm:items-center">
              <dt className="text-sm font-medium text-muted-foreground">Name</dt>
              <dd className="min-w-0 break-words font-medium">
                {fullName || "Add your full name"}
              </dd>
            </div>
            <div className="grid gap-1 p-4 sm:grid-cols-[9rem_1fr] sm:items-center">
              <dt className="text-sm font-medium text-muted-foreground">Email</dt>
              <dd className="min-w-0 break-all">{email}</dd>
            </div>
          </dl>
        </CardContent>
        <CardFooter className="flex flex-wrap gap-2">
          <Button asChild variant="outline">
            <Link href="/settings?tab=profile" target="_blank" rel="noreferrer">
              <UserRound className="mr-2 size-4" aria-hidden="true" />
              Review profile
              <ExternalLink className="ml-2 size-3.5" aria-hidden="true" />
              <span className="sr-only"> (opens in a new tab)</span>
            </Link>
          </Button>
          <Button asChild variant="ghost">
            <Link href="/settings?tab=notifications" target="_blank" rel="noreferrer">
              Set notifications
              <ExternalLink className="ml-2 size-3.5" aria-hidden="true" />
              <span className="sr-only"> (opens in a new tab)</span>
            </Link>
          </Button>
        </CardFooter>
      </Card>

      <p className="text-sm text-muted-foreground">
        The setup reminder stays visible in the app until you finish this walkthrough.
      </p>
    </section>
  );
}

function CalendarStep() {
  return (
    <section aria-labelledby="sales-calendar-title" className="space-y-6">
      <div className="max-w-2xl">
        <h1 id="sales-calendar-title" className="text-2xl font-bold tracking-tight">
          Connect the calendar that owns your appointments
        </h1>
        <p className="mt-2 text-muted-foreground">
          A shared or booking link is not enough for sync. Connect your Google account so Tribunal
          can check conflicts and create confirmed appointments on your calendar.
        </p>
      </div>

      <GoogleCalendarCard returnPath="/sales-onboarding?step=calendar" />

      <div className="rounded-lg border border-l-4 border-l-primary p-4">
        <h2 className="font-medium">Your manager finishes booking access</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          After you connect, ask your manager to enable Booking Calendar and confirm your working
          hours in Team settings.
        </p>
      </div>
    </section>
  );
}

function WorkflowStep() {
  const path = [
    {
      icon: Clock3,
      title: "Today",
      description: "Pick the next due reply, task, or meeting instead of scanning every record.",
    },
    {
      icon: MessageSquareText,
      title: "Contact",
      description:
        "Read the conversation history before calling or texting from the customer record.",
    },
    {
      icon: ListChecks,
      title: "Opportunity",
      description: "Update the stage and leave the next follow-up task before moving on.",
    },
    {
      icon: CalendarDays,
      title: "Calendar",
      description: "Confirm the appointment time and make sure it appears on your Google Calendar.",
    },
  ];

  return (
    <section aria-labelledby="sales-workflow-title" className="space-y-6">
      <div className="max-w-2xl">
        <h1 id="sales-workflow-title" className="text-2xl font-bold tracking-tight">
          Run the first-lead path
        </h1>
        <p className="mt-2 text-muted-foreground">
          Use this same order for every assigned lead. It keeps the customer conversation and the
          team handoff in one clean record.
        </p>
      </div>

      <ol className="overflow-hidden rounded-lg border" aria-label="First lead workflow">
        {path.map((item, index) => {
          const Icon = item.icon;
          return (
            <li
              key={item.title}
              className="grid grid-cols-[2.5rem_1fr] gap-3 border-b p-4 last:border-b-0 sm:grid-cols-[3rem_1fr] sm:p-5"
            >
              <div className="flex flex-col items-center gap-2" aria-hidden="true">
                <Icon className="mt-0.5 size-5 text-primary" />
                <span className="text-xs font-semibold text-muted-foreground">{index + 1}</span>
              </div>
              <div>
                <h2 className="font-semibold">{item.title}</h2>
                <p className="mt-1 text-sm text-muted-foreground">{item.description}</p>
              </div>
            </li>
          );
        })}
      </ol>

      <div className="rounded-lg border p-4 text-sm">
        <p className="font-medium">Practice with a manager-created test lead first.</p>
        <p className="mt-1 text-muted-foreground">
          Do not use a live customer to test calling, texting, or calendar setup.
        </p>
      </div>
    </section>
  );
}

function ReadyStep() {
  const checks = [
    "Your full name, mobile number, and timezone are correct.",
    "Your Google Calendar is connected, or your manager approved a temporary skip.",
    "Your manager enabled booking and assigned a test lead.",
    "A test call or text and test appointment reached the expected places.",
  ];

  return (
    <section aria-labelledby="sales-ready-title" className="space-y-6">
      <div className="max-w-2xl">
        <h1 id="sales-ready-title" className="text-2xl font-bold tracking-tight">
          Ready for your first assigned lead
        </h1>
        <p className="mt-2 text-muted-foreground">
          Confirm these four items with your manager. Finishing removes the setup reminder and sends
          you to Today.
        </p>
      </div>

      <ul className="divide-y rounded-lg border" aria-label="Sales rep readiness checklist">
        {checks.map((check) => (
          <li key={check} className="flex gap-3 p-4 sm:p-5">
            <CheckCircle2 className="mt-0.5 size-5 shrink-0 text-primary" aria-hidden="true" />
            <span>{check}</span>
          </li>
        ))}
      </ul>

      <p className="text-sm text-muted-foreground">
        If a test fails, stop and tell your manager before contacting live customers.
      </p>
    </section>
  );
}

export function SalesRepOnboarding() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const mounted = useIsMounted();
  const { user, isLoading: authLoading } = useAuth();
  const { currentWorkspace, currentWorkspaceId, isPending: workspacePending } = useWorkspace();
  const [isFinishing, setIsFinishing] = useState(false);
  const restoredStep = useRef(false);

  const wizard = useWizard<SalesOnboardingStep, Record<string, never>>({
    steps: SALES_ONBOARDING_STEPS,
    initialFormData: {},
    validateOnNavigate: false,
  });

  const requestedStep = searchParams.get("step");

  useEffect(() => {
    if (restoredStep.current || !requestedStep) return;
    restoredStep.current = true;
    if (VALID_STEPS.has(requestedStep as SalesOnboardingStep)) {
      wizard.goToStep(requestedStep as SalesOnboardingStep);
    }
  }, [requestedStep, wizard]);

  const isReady = mounted && !authLoading && !workspacePending;
  const isSalesRep = currentWorkspace?.role === "sales_rep";

  useEffect(() => {
    if (!isReady) return;
    if (!user || !currentWorkspace || !currentWorkspaceId || !isSalesRep) {
      router.replace("/today");
      return;
    }
    markAutoRedirectedToSalesRepOnboarding(user.id, currentWorkspaceId);
  }, [currentWorkspace, currentWorkspaceId, isReady, isSalesRep, router, user]);

  if (!isReady || !user || !currentWorkspace || !currentWorkspaceId || !isSalesRep) {
    return <SalesOnboardingLoading />;
  }

  const firstName = user.full_name?.trim().split(/\s+/)[0] || "there";

  const goToStep = (step: SalesOnboardingStep) => {
    wizard.goToStep(step);
    router.replace(`/sales-onboarding?step=${step}`, { scroll: false });
  };

  const goPrevious = () => {
    const step = SALES_ONBOARDING_STEPS[wizard.currentStepIndex - 1];
    if (step) goToStep(step.id);
  };

  const goNext = () => {
    const step = SALES_ONBOARDING_STEPS[wizard.currentStepIndex + 1];
    if (step) goToStep(step.id);
  };

  const skipForNow = () => {
    markAutoRedirectedToSalesRepOnboarding(user.id, currentWorkspaceId);
    router.replace("/today");
  };

  const finish = () => {
    setIsFinishing(true);
    markSalesRepOnboardingCompleted(user.id, currentWorkspaceId);
    toast.success("Sales rep setup complete");
    router.replace("/today");
  };

  const stepContent: Record<SalesOnboardingStep, React.ReactNode> = {
    welcome: (
      <WelcomeStep
        firstName={firstName}
        workspaceName={currentWorkspace.workspace.name || "your workspace"}
      />
    ),
    profile: <ProfileStep fullName={user.full_name} email={user.email} />,
    calendar: <CalendarStep />,
    workflow: <WorkflowStep />,
    ready: <ReadyStep />,
  };

  return (
    <main className="min-h-svh bg-background px-4 py-4 sm:px-6 sm:py-8">
      <div className="mx-auto max-w-4xl">
        <div className="mb-3 flex min-h-9 items-center justify-between gap-4">
          <p className="truncate text-sm font-medium text-muted-foreground">
            {currentWorkspace.workspace.name} sales setup
          </p>
          <Button variant="ghost" size="sm" onClick={skipForNow}>
            Skip for now
          </Button>
        </div>

        <div className="h-[calc(100svh-5.75rem)] min-h-[580px] max-h-[760px] overflow-hidden rounded-xl border bg-card shadow-sm">
          <WizardContainer
            steps={SALES_ONBOARDING_STEPS}
            currentStepId={wizard.currentStepId}
            currentStepIndex={wizard.currentStepIndex}
            onStepClick={goToStep}
            isFirstStep={wizard.isFirstStep}
            isLastStep={wizard.isLastStep}
            onPrevious={goPrevious}
            onNext={goNext}
            onSubmit={finish}
            isSubmitting={isFinishing}
            submitLabel="Finish setup"
            submittingLabel="Finishing..."
            submitIcon={CheckCircle2}
          >
            {stepContent[wizard.currentStepId]}
          </WizardContainer>
        </div>
      </div>
    </main>
  );
}
