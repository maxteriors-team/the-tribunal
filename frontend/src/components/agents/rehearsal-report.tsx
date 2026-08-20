"use client";

import {
  CalendarCheck,
  CalendarX,
  CheckCircle2,
  Lightbulb,
  ShieldCheck,
  Smile,
  TriangleAlert,
  XCircle,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Separator } from "@/components/ui/separator";
import type { RehearsalRun } from "@/types/roleplay";

function scoreColor(value: number | null | undefined): string {
  if (value === null || value === undefined) return "text-muted-foreground";
  if (value >= 75) return "text-emerald-600";
  if (value >= 50) return "text-amber-600";
  return "text-red-600";
}

function ScoreStat({
  label,
  value,
  icon,
}: {
  label: string;
  value: number | null;
  icon: React.ReactNode;
}) {
  const display = value === null ? "—" : Math.round(value);
  return (
    <Card>
      <CardContent className="flex flex-col gap-2 p-4">
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          {icon}
          {label}
        </div>
        <div className={`text-2xl font-semibold ${scoreColor(value)}`}>
          {display}
          {value !== null ? <span className="text-base">/100</span> : null}
        </div>
        {value !== null ? <Progress value={value} aria-label={`${label} score`} /> : null}
      </CardContent>
    </Card>
  );
}

function FeedbackList({
  title,
  items,
  icon,
  tone,
}: {
  title: string;
  items: string[];
  icon: React.ReactNode;
  tone: "good" | "warn" | "info";
}) {
  if (items.length === 0) return null;
  const toneClass =
    tone === "good" ? "text-emerald-600" : tone === "warn" ? "text-amber-600" : "text-sky-600";
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className={`flex items-center gap-2 text-base ${toneClass}`}>
          {icon}
          {title}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <ul className="space-y-2 text-sm">
          {items.map((item, i) => (
            <li key={i} className="flex gap-2">
              <span className={toneClass}>•</span>
              <span>{item}</span>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}

export function RehearsalReport({ run }: { run: RehearsalRun }) {
  const breakdown = run.scores?.objection_breakdown ?? [];
  const toneLabel = run.scores?.tone_label;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold">
            {run.agent_name ?? "Agent"} vs {run.persona_name ?? "Prospect"}
          </h2>
          <p className="text-sm text-muted-foreground">
            {run.rehearsee === "human" ? "Human rep" : "AI agent"} rehearsal ·{" "}
            {run.channel.toUpperCase()}
          </p>
        </div>
        <div className="text-right">
          <div className="text-xs uppercase text-muted-foreground">Overall score</div>
          <div className={`text-4xl font-bold ${scoreColor(run.overall_score)}`}>
            {run.overall_score === null ? "—" : Math.round(run.overall_score)}
          </div>
        </div>
      </div>

      {run.summary ? (
        <Card>
          <CardContent className="p-4 text-sm">{run.summary}</CardContent>
        </Card>
      ) : null}

      <div className="grid gap-4 sm:grid-cols-3">
        <ScoreStat
          label="Objection coverage"
          value={run.objection_coverage}
          icon={<ShieldCheck className="size-4" />}
        />
        <ScoreStat
          label={`Tone${toneLabel ? ` · ${toneLabel}` : ""}`}
          value={run.tone_score}
          icon={<Smile className="size-4" />}
        />
        <Card>
          <CardContent className="flex flex-col gap-2 p-4">
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              {run.booking_attempted ? (
                <CalendarCheck className="size-4" />
              ) : (
                <CalendarX className="size-4" />
              )}
              Attempted booking
            </div>
            <div className="text-2xl font-semibold">
              {run.booking_attempted === null ? (
                "—"
              ) : run.booking_attempted ? (
                <span className="text-emerald-600">Yes</span>
              ) : (
                <span className="text-red-600">No</span>
              )}
            </div>
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        <FeedbackList
          title="Strengths"
          items={run.strengths}
          icon={<CheckCircle2 className="size-4" />}
          tone="good"
        />
        <FeedbackList
          title="Gaps"
          items={run.gaps}
          icon={<TriangleAlert className="size-4" />}
          tone="warn"
        />
        <FeedbackList
          title="Suggested improvements"
          items={run.suggestions}
          icon={<Lightbulb className="size-4" />}
          tone="info"
        />
      </div>

      {breakdown.length > 0 ? (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">Objection handling</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {breakdown.map((item, i) => (
              <div key={i} className="flex items-start gap-3 text-sm">
                {item.addressed ? (
                  <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-emerald-600" />
                ) : (
                  <XCircle className="mt-0.5 size-4 shrink-0 text-red-600" />
                )}
                <div>
                  <div className="font-medium">{item.objection}</div>
                  {item.note ? <div className="text-muted-foreground">{item.note}</div> : null}
                </div>
              </div>
            ))}
          </CardContent>
        </Card>
      ) : null}

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">Transcript</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {run.transcript.map((turn, i) => {
            const isProspect = turn.role === "prospect";
            return (
              <div key={i} className={`flex ${isProspect ? "justify-start" : "justify-end"}`}>
                <div
                  className={`max-w-[80%] rounded-lg px-3 py-2 text-sm ${
                    isProspect ? "bg-muted" : "bg-primary text-primary-foreground"
                  }`}
                >
                  <div className="mb-1 text-xs opacity-70">
                    {isProspect ? (run.persona_name ?? "Prospect") : "Rep"}
                  </div>
                  {turn.content}
                </div>
              </div>
            );
          })}
        </CardContent>
      </Card>

      {run.status === "failed" && run.error ? (
        <Card className="border-red-300">
          <CardContent className="flex items-center gap-2 p-4 text-sm text-red-600">
            <Badge variant="destructive">Failed</Badge>
            {run.error}
          </CardContent>
        </Card>
      ) : null}

      <Separator />
    </div>
  );
}
