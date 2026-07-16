"use client";

/**
 * Seasonal Christmas Lights hub — a dedicated, visually distinct home for the
 * holiday-lighting workflow. It routes to the three real seasonal surfaces
 * (design/render, quote builder, pricing) and previews the distinct option
 * icons customers see on a quote, so the whole seasonal flow is one obvious tab.
 */
import {
  ArrowRight,
  Ruler,
  Settings2,
  Sparkles,
  TreePine,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";

import { AppSidebar } from "@/components/layout/app-sidebar";
import { Card, CardContent } from "@/components/ui/card";
import {
  seasonalIconForCategory,
  tintSurface,
} from "@/lib/estimator/seasonal-icons";

interface HubAction {
  title: string;
  description: string;
  href: string;
  Icon: LucideIcon;
}

const HUB_ACTIONS: HubAction[] = [
  {
    title: "Design & Night Render",
    description:
      "Trace roofline and place decor on a customer photo, then generate a realistic after-dark preview.",
    href: "/estimator",
    Icon: Sparkles,
  },
  {
    title: "Build a Quote",
    description:
      "Pick a Good / Better / Best package, measure the roofline once, and add trees, wreaths and garland.",
    href: "/sales-wizard",
    Icon: Ruler,
  },
  {
    title: "Seasonal Pricing & Packages",
    description:
      "Tune per-foot roofline rates, decor prices and the Good / Better / Best package tiers for this workspace.",
    href: "/settings?tab=pricing",
    Icon: Settings2,
  },
];

/** Decor categories, in the order they read on a quote, for the icon legend. */
const LEGEND_CATEGORIES = [
  "roofline",
  "wreaths",
  "trees",
  "bushes",
  "garland",
  "mini_lights",
] as const;

export default function ChristmasLightsRoute() {
  return (
    <AppSidebar>
      <div className="app-scrollbar h-full overflow-y-auto">
        <div className="mx-auto w-full max-w-5xl px-4 py-6 sm:px-6 sm:py-8">
          <header className="relative overflow-hidden rounded-2xl border bg-gradient-to-br from-emerald-50 via-background to-rose-50 p-6 sm:p-8 dark:from-emerald-950/40 dark:via-background dark:to-rose-950/25">
            <div className="flex items-start gap-4">
              <span
                className="flex size-12 shrink-0 items-center justify-center rounded-xl border border-emerald-500/30 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
                aria-hidden="true"
              >
                <TreePine className="size-6" />
              </span>
              <div className="min-w-0">
                <h1 className="text-2xl font-semibold tracking-tight">
                  Christmas Lights
                </h1>
                <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
                  Your seasonal command center. Design a lit-up render, build a
                  package quote, and set holiday pricing, all in one place.
                </p>
              </div>
            </div>
          </header>

          <section className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {HUB_ACTIONS.map(({ title, description, href, Icon }) => (
              <Link
                key={href}
                href={href}
                className="group rounded-xl outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
              >
                <Card className="h-full transition-colors group-hover:border-emerald-500/50 group-hover:bg-accent/40">
                  <CardContent className="flex h-full flex-col gap-3 p-5">
                    <span
                      className="flex size-10 items-center justify-center rounded-lg border border-emerald-500/25 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
                      aria-hidden="true"
                    >
                      <Icon className="size-5" />
                    </span>
                    <div className="flex-1">
                      <h2 className="font-medium">{title}</h2>
                      <p className="mt-1 text-sm text-muted-foreground">
                        {description}
                      </p>
                    </div>
                    <span className="inline-flex items-center gap-1 text-sm font-medium text-emerald-600 dark:text-emerald-400">
                      Open
                      <ArrowRight className="size-4 transition-transform group-hover:translate-x-0.5" />
                    </span>
                  </CardContent>
                </Card>
              </Link>
            ))}
          </section>

          <section className="mt-8">
            <h2 className="text-sm font-semibold uppercase tracking-widest text-muted-foreground">
              How options appear on a quote
            </h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Each product type carries a distinct icon so customers can tell a
              wreath from a tree or a roofline run at a glance.
            </p>
            <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-3">
              {LEGEND_CATEGORIES.map((key) => {
                const { Icon, tint, label } = seasonalIconForCategory(key);
                return (
                  <div
                    key={key}
                    className="flex items-center gap-2.5 rounded-lg border bg-card px-3 py-2.5"
                  >
                    <span
                      className="flex size-8 shrink-0 items-center justify-center rounded-lg border"
                      style={{ color: tint, background: tintSurface(tint) }}
                      aria-hidden="true"
                    >
                      <Icon className="size-4" />
                    </span>
                    <span className="min-w-0 text-sm leading-tight">{label}</span>
                  </div>
                );
              })}
            </div>
          </section>
        </div>
      </div>
    </AppSidebar>
  );
}
