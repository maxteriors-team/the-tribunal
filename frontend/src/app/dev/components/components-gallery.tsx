"use client";

import { Mail, Sparkles } from "lucide-react";
import { type ReactNode } from "react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  PageEmptyState,
  PageErrorState,
  PageLoadingState,
} from "@/components/ui/page-state";
import { Progress } from "@/components/ui/progress";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";

interface SectionProps {
  id: string;
  title: string;
  importPath: string;
  description?: string;
  children: ReactNode;
}

function Section({ id, title, importPath, description, children }: SectionProps) {
  return (
    <section
      id={id}
      className="scroll-mt-24 rounded-xl border border-border bg-card/40 p-6 shadow-sm"
    >
      <header className="mb-4 space-y-1">
        <div className="flex flex-wrap items-baseline gap-3">
          <h2 className="text-lg font-semibold tracking-tight">{title}</h2>
          <code className="rounded bg-muted px-2 py-0.5 text-xs text-muted-foreground">
            {importPath}
          </code>
        </div>
        {description ? (
          <p className="text-sm text-muted-foreground">{description}</p>
        ) : null}
      </header>
      <div className="space-y-6">{children}</div>
    </section>
  );
}

interface ExampleProps {
  label: string;
  children: ReactNode;
}

function Example({ label, children }: ExampleProps) {
  return (
    <div className="space-y-2">
      <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
        {label}
      </p>
      <div className="rounded-lg border border-dashed border-border bg-background p-4">
        {children}
      </div>
    </div>
  );
}

const SECTIONS = [
  { id: "page-state", title: "Page State (canonical)" },
  { id: "button", title: "Button" },
  { id: "badge", title: "Badge" },
  { id: "alert", title: "Alert" },
  { id: "card", title: "Card" },
  { id: "form-controls", title: "Form Controls" },
  { id: "skeleton-progress", title: "Skeleton & Progress" },
  { id: "tabs", title: "Tabs" },
  { id: "tooltip", title: "Tooltip" },
] as const;

export function ComponentsGallery() {
  return (
    <div className="mx-auto max-w-5xl px-6 py-10">
      <header className="mb-8 space-y-3">
        <Badge variant="outline">dev only · not deployed</Badge>
        <h1 className="text-3xl font-bold tracking-tight">UI Component Gallery</h1>
        <p className="max-w-2xl text-sm text-muted-foreground">
          Living style guide for the shared primitives under{" "}
          <code className="rounded bg-muted px-1 py-0.5">@/components/ui/*</code>.
          Reach for these <strong>before</strong> rolling a new loading spinner,
          empty state, or button variant. The page-state primitives at the top
          are the canonical loading / error / empty surfaces for every page —
          use them in <code className="rounded bg-muted px-1 py-0.5">loading.tsx</code>,{" "}
          <code className="rounded bg-muted px-1 py-0.5">error.tsx</code>, and
          any list view that can be empty.
        </p>
        <nav aria-label="Sections" className="flex flex-wrap gap-2 pt-2">
          {SECTIONS.map((s) => (
            <a
              key={s.id}
              href={`#${s.id}`}
              className="rounded-md border border-border bg-card/40 px-2.5 py-1 text-xs font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
            >
              {s.title}
            </a>
          ))}
        </nav>
      </header>

      <div className="space-y-8">
        <Section
          id="page-state"
          title="Page State (canonical)"
          importPath='@/components/ui/page-state'
          description="Use these for every page-level loading, error, and empty surface so the app renders consistent states. PageLoadingState belongs in loading.tsx, PageErrorState in error.tsx (pair with Sentry capture), PageEmptyState in any list whose query returned zero rows."
        >
          <Example label="PageLoadingState">
            <PageLoadingState message="Loading contacts…" />
          </Example>
          <Example label="PageErrorState">
            <PageErrorState
              message="We couldn't load contacts. Please try again."
              onRetry={() => undefined}
            />
          </Example>
          <Example label="PageEmptyState">
            <PageEmptyState
              title="No contacts yet"
              description="Import a CSV or create a contact to get started."
              icon={<Sparkles className="size-8" />}
              action={<Button size="sm">Add contact</Button>}
            />
          </Example>
        </Section>

        <Section
          id="button"
          title="Button"
          importPath='@/components/ui/button'
          description="Variants: default · secondary · destructive · outline · ghost · link. Sizes: sm · default · lg · icon."
        >
          <Example label="Variants">
            <div className="flex flex-wrap gap-2">
              <Button>Default</Button>
              <Button variant="secondary">Secondary</Button>
              <Button variant="destructive">Destructive</Button>
              <Button variant="outline">Outline</Button>
              <Button variant="ghost">Ghost</Button>
              <Button variant="link">Link</Button>
            </div>
          </Example>
          <Example label="Sizes">
            <div className="flex flex-wrap items-center gap-2">
              <Button size="sm">Small</Button>
              <Button>Default</Button>
              <Button size="lg">Large</Button>
              <Button size="icon" aria-label="Mail">
                <Mail />
              </Button>
            </div>
          </Example>
          <Example label="Disabled">
            <Button disabled>Disabled</Button>
          </Example>
        </Section>

        <Section
          id="badge"
          title="Badge"
          importPath='@/components/ui/badge'
        >
          <Example label="Variants">
            <div className="flex flex-wrap gap-2">
              <Badge>Default</Badge>
              <Badge variant="secondary">Secondary</Badge>
              <Badge variant="destructive">Destructive</Badge>
              <Badge variant="outline">Outline</Badge>
            </div>
          </Example>
        </Section>

        <Section
          id="alert"
          title="Alert"
          importPath='@/components/ui/alert'
          description="In-flow notice. For page-level errors, prefer PageErrorState instead."
        >
          <Example label="Default">
            <Alert>
              <Sparkles className="size-4" />
              <AlertTitle>Heads up</AlertTitle>
              <AlertDescription>
                You can use this for in-flow notices that don&apos;t replace the page.
              </AlertDescription>
            </Alert>
          </Example>
          <Example label="Destructive">
            <Alert variant="destructive">
              <AlertTitle>Something went wrong</AlertTitle>
              <AlertDescription>
                Your last action could not be completed.
              </AlertDescription>
            </Alert>
          </Example>
        </Section>

        <Section
          id="card"
          title="Card"
          importPath='@/components/ui/card'
        >
          <Example label="Composed">
            <Card className="max-w-sm">
              <CardHeader>
                <CardTitle>Card title</CardTitle>
                <CardDescription>A short supporting line.</CardDescription>
              </CardHeader>
              <CardContent>
                <p className="text-sm">
                  Card body content goes here. Use <code>CardContent</code> for the main slot.
                </p>
              </CardContent>
              <CardFooter className="border-t">
                <Button size="sm">Action</Button>
              </CardFooter>
            </Card>
          </Example>
        </Section>

        <Section
          id="form-controls"
          title="Form Controls"
          importPath='@/components/ui/{input,textarea,label,checkbox,switch,separator}'
        >
          <Example label="Input + Label">
            <div className="grid max-w-sm gap-2">
              <Label htmlFor="dev-email">Email</Label>
              <Input id="dev-email" type="email" placeholder="you@example.com" />
            </div>
          </Example>
          <Example label="Textarea">
            <Textarea placeholder="Write a longer note…" className="max-w-sm" />
          </Example>
          <Example label="Checkbox + Switch">
            <div className="flex items-center gap-6">
              <Label className="flex items-center gap-2">
                <Checkbox defaultChecked /> Subscribe
              </Label>
              <Label className="flex items-center gap-2">
                <Switch defaultChecked /> Notifications
              </Label>
            </div>
          </Example>
          <Example label="Separator">
            <div className="space-y-2 text-sm">
              <p>Above</p>
              <Separator />
              <p>Below</p>
            </div>
          </Example>
        </Section>

        <Section
          id="skeleton-progress"
          title="Skeleton & Progress"
          importPath='@/components/ui/{skeleton,progress}'
          description="Use Skeleton inline for granular per-row placeholders. For full page loading, prefer PageLoadingState above."
        >
          <Example label="Skeleton">
            <div className="space-y-2">
              <Skeleton className="h-4 w-1/3" />
              <Skeleton className="h-4 w-2/3" />
              <Skeleton className="h-4 w-1/2" />
            </div>
          </Example>
          <Example label="Progress">
            <Progress value={62} />
          </Example>
        </Section>

        <Section
          id="tabs"
          title="Tabs"
          importPath='@/components/ui/tabs'
        >
          <Example label="Default">
            <Tabs defaultValue="overview" className="max-w-md">
              <TabsList>
                <TabsTrigger value="overview">Overview</TabsTrigger>
                <TabsTrigger value="activity">Activity</TabsTrigger>
                <TabsTrigger value="settings">Settings</TabsTrigger>
              </TabsList>
              <TabsContent value="overview" className="pt-3 text-sm">
                Overview panel content.
              </TabsContent>
              <TabsContent value="activity" className="pt-3 text-sm">
                Activity panel content.
              </TabsContent>
              <TabsContent value="settings" className="pt-3 text-sm">
                Settings panel content.
              </TabsContent>
            </Tabs>
          </Example>
        </Section>

        <Section
          id="tooltip"
          title="Tooltip"
          importPath='@/components/ui/tooltip'
        >
          <Example label="On hover">
            <Tooltip>
              <TooltipTrigger asChild>
                <Button variant="outline">Hover me</Button>
              </TooltipTrigger>
              <TooltipContent>Helpful hint text</TooltipContent>
            </Tooltip>
          </Example>
        </Section>
      </div>
    </div>
  );
}
