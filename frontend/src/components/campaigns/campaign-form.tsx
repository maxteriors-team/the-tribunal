"use client";

import {
  ArrowLeft,
  ArrowRight,
  CalendarClock,
  Layers3,
  Mail,
  MessageSquare,
  Phone,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

interface AvailableCampaignOption {
  label: string;
  description: string;
  icon: LucideIcon;
  href: string;
  unavailable?: false;
}

interface UnavailableCampaignOption {
  label: string;
  description: string;
  icon: LucideIcon;
  unavailable: true;
  href?: never;
}

type CampaignOption = AvailableCampaignOption | UnavailableCampaignOption;

const campaignOptions: readonly CampaignOption[] = [
  {
    label: "SMS Campaign",
    description: "Send a text campaign with contact selection, offers, AI replies, and scheduling.",
    icon: MessageSquare,
    href: "/campaigns/sms/new",
  },
  {
    label: "Email Campaign",
    description: "Create an email, choose recipients, then save a draft or send it now.",
    icon: Mail,
    href: "/campaigns/email/new",
  },
  {
    label: "Voice Campaign",
    description: "Run AI-powered calls with an optional SMS fallback for missed connections.",
    icon: Phone,
    href: "/campaigns/voice/new",
  },
  {
    label: "Pre-Booking Campaign",
    description: "Sell next season's work with an offer, deposit, and dedicated booking flow.",
    icon: CalendarClock,
    href: "/campaigns/pre-booking/new",
  },
  {
    label: "Multi-Channel Campaign",
    description:
      "A persisted workflow spanning SMS, email, and voice is not available yet. Create one campaign per channel for now.",
    icon: Layers3,
    unavailable: true,
  },
];

const optionClassName =
  "relative flex min-h-48 flex-col rounded-xl border bg-card p-5 text-left shadow-sm transition-colors";

export function CampaignForm() {
  return (
    <div className="mx-auto max-w-5xl space-y-6 p-6">
      <div className="flex items-center gap-4">
        <Button variant="ghost" size="icon" asChild>
          <Link href="/campaigns" aria-label="Back to campaigns">
            <ArrowLeft className="size-4" />
          </Link>
        </Button>
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Create Campaign</h1>
          <p className="text-muted-foreground">
            Choose a workflow, then enter and save its details in the channel-specific wizard.
          </p>
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Choose a campaign workflow</CardTitle>
          <CardDescription>
            Every available option opens the real builder. This page does not collect temporary
            campaign data.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {campaignOptions.map((option) => {
              const Icon = option.icon;

              if (option.unavailable) {
                return (
                  <div
                    key={option.label}
                    aria-disabled="true"
                    className={`${optionClassName} cursor-not-allowed border-dashed bg-muted/40 text-muted-foreground`}
                  >
                    <Badge variant="secondary" className="absolute right-4 top-4">
                      Coming soon
                    </Badge>
                    <Icon className="mb-4 size-7" aria-hidden="true" />
                    <h2 className="pr-24 font-semibold text-foreground">{option.label}</h2>
                    <p className="mt-2 text-sm leading-relaxed">{option.description}</p>
                    <span className="mt-auto pt-5 text-sm font-medium">Unavailable</span>
                  </div>
                );
              }

              return (
                <Link
                  key={option.label}
                  href={option.href}
                  className={`${optionClassName} group hover:border-primary/60 hover:bg-primary/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2`}
                >
                  <Icon className="mb-4 size-7 text-primary" aria-hidden="true" />
                  <h2 className="font-semibold">{option.label}</h2>
                  <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
                    {option.description}
                  </p>
                  <span className="mt-auto flex items-center gap-2 pt-5 text-sm font-medium text-primary">
                    Open builder
                    <ArrowRight
                      className="size-4 transition-transform group-hover:translate-x-1"
                      aria-hidden="true"
                    />
                  </span>
                </Link>
              );
            })}
          </div>
        </CardContent>
      </Card>

      <div className="flex justify-end">
        <Button variant="outline" asChild>
          <Link href="/campaigns">Cancel</Link>
        </Button>
      </div>
    </div>
  );
}
