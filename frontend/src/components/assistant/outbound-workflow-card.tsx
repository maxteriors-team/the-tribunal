"use client";

import {
  BellRing,
  Bot,
  Check,
  CheckCircle2,
  Clock,
  Gift,
  Megaphone,
  MessageSquareText,
  Rocket,
  ShieldCheck,
  Users,
  X,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Separator } from "@/components/ui/separator";
import { cn } from "@/lib/utils";
import { formatRelative } from "@/lib/utils/date";
import { formatNumber } from "@/lib/utils/number";
import type { PendingAction } from "@/types/pending-action";

interface WorkflowMessagePreview {
  channel: string;
  label: string;
  body: string;
}

interface WorkflowMetric {
  label: string;
  value: string;
  tone?: "default" | "success" | "warning";
}

interface OutboundWorkflowDetails {
  title: string;
  summary: string;
  segmentName?: string;
  segmentCount?: number;
  segmentDescription?: string;
  offerName?: string;
  offerSummary?: string;
  messagePreviews: WorkflowMessagePreview[];
  approvalLabel?: string;
  approvalStatus?: string;
  campaignName?: string;
  launchStatus?: string;
  launchProgress?: number;
  responderAgentName?: string;
  responderAgentRole?: string;
  handoffTitle?: string;
  handoffDescription?: string;
  metrics: WorkflowMetric[];
}

interface OutboundWorkflowCardProps {
  action?: PendingAction;
  payload?: Record<string, unknown>;
  context?: Record<string, unknown>;
  onApprove?: () => void;
  onReject?: () => void;
  isApproving?: boolean;
  isRejecting?: boolean;
  className?: string;
}

const WORKFLOW_ACTION_TYPES = new Set([
  "outbound_workflow",
  "launch_campaign",
  "campaign_launch",
  "enroll_campaign",
  "send_campaign",
  "send_sms_campaign",
  "warm_lead_handoff",
]);

export function isOutboundWorkflowAction(action: PendingAction) {
  return (
    WORKFLOW_ACTION_TYPES.has(action.action_type) ||
    hasWorkflowSignals(action.action_payload) ||
    hasWorkflowSignals(action.context)
  );
}

export function OutboundWorkflowCard({
  action,
  payload = action?.action_payload ?? {},
  context = action?.context ?? {},
  onApprove,
  onReject,
  isApproving = false,
  isRejecting = false,
  className,
}: OutboundWorkflowCardProps) {
  const details = getWorkflowDetails({ action, payload, context });
  const canReview = action?.status === "pending" && onApprove && onReject;

  return (
    <Card className={cn("overflow-hidden border-primary/20 bg-card", className)}>
      <CardHeader className="space-y-3 border-b bg-muted/30 p-4">
        <div className="flex items-start justify-between gap-3">
          <div className="space-y-1">
            <CardTitle className="flex items-center gap-2 text-base">
              <Megaphone className="size-4 text-primary" />
              {details.title}
            </CardTitle>
            <p className="text-sm text-muted-foreground">{details.summary}</p>
          </div>
          <div className="flex shrink-0 flex-wrap justify-end gap-1.5">
            {details.approvalStatus ? (
              <Badge variant="outline" className="capitalize">
                {details.approvalStatus.replaceAll("_", " ")}
              </Badge>
            ) : null}
            {details.launchStatus ? (
              <Badge className={getLaunchStatusClassName(details.launchStatus)}>
                {details.launchStatus.replaceAll("_", " ")}
              </Badge>
            ) : null}
          </div>
        </div>

        {details.metrics.length > 0 ? (
          <div className="grid gap-2 sm:grid-cols-3">
            {details.metrics.map((metric) => (
              <div key={metric.label} className="rounded-lg border bg-background/70 p-2">
                <p className="text-[11px] uppercase tracking-wide text-muted-foreground">
                  {metric.label}
                </p>
                <p
                  className={cn(
                    "text-sm font-semibold",
                    metric.tone === "success" && "text-green-600",
                    metric.tone === "warning" && "text-amber-600",
                  )}
                >
                  {metric.value}
                </p>
              </div>
            ))}
          </div>
        ) : null}
      </CardHeader>

      <CardContent className="space-y-4 p-4">
        <div className="grid gap-3 md:grid-cols-2">
          <WorkflowSection
            icon={<Users className="size-4" />}
            label="Segment preview"
            title={details.segmentName ?? "Audience segment"}
            description={details.segmentDescription}
            meta={
              typeof details.segmentCount === "number"
                ? `${formatNumber(details.segmentCount)} contacts matched`
                : undefined
            }
          />
          <WorkflowSection
            icon={<Gift className="size-4" />}
            label="Offer selection"
            title={details.offerName ?? "No offer attached"}
            description={details.offerSummary}
          />
        </div>

        {details.messagePreviews.length > 0 ? (
          <div className="space-y-2">
            <div className="flex items-center gap-2 text-sm font-medium">
              <MessageSquareText className="size-4 text-muted-foreground" />
              Message previews
            </div>
            <div className="grid gap-2">
              {details.messagePreviews.map((message) => (
                <div key={`${message.channel}-${message.label}`} className="rounded-lg border bg-muted/20 p-3">
                  <div className="mb-2 flex items-center justify-between gap-2">
                    <Badge variant="secondary" className="capitalize">
                      {message.channel.replaceAll("_", " ")}
                    </Badge>
                    <span className="text-xs text-muted-foreground">{message.label}</span>
                  </div>
                  <p className="whitespace-pre-wrap text-sm leading-relaxed">{message.body}</p>
                </div>
              ))}
            </div>
          </div>
        ) : null}

        <div className="grid gap-3 md:grid-cols-3">
          <WorkflowSection
            icon={<ShieldCheck className="size-4" />}
            label="Approval action"
            title={details.approvalLabel ?? "Ready for human review"}
            description={action?.expires_at ? `Expires ${formatRelative(action.expires_at)}` : undefined}
          />
          <WorkflowSection
            icon={<Rocket className="size-4" />}
            label="Campaign launch"
            title={details.campaignName ?? "Outbound campaign"}
            description={details.launchStatus ? `Status: ${details.launchStatus.replaceAll("_", " ")}` : undefined}
          >
            {typeof details.launchProgress === "number" ? (
              <Progress value={details.launchProgress} className="mt-2 h-2" />
            ) : null}
          </WorkflowSection>
          <WorkflowSection
            icon={<Bot className="size-4" />}
            label="Assigned responder"
            title={details.responderAgentName ?? "CRM assistant"}
            description={details.responderAgentRole ?? "Handles replies and qualification"}
          />
        </div>

        {(details.handoffTitle || details.handoffDescription) && (
          <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-amber-950 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-100">
            <div className="flex items-start gap-2">
              <BellRing className="mt-0.5 size-4 shrink-0" />
              <div>
                <p className="text-sm font-medium">{details.handoffTitle ?? "Warm-lead handoff"}</p>
                {details.handoffDescription ? (
                  <p className="mt-1 text-sm opacity-80">{details.handoffDescription}</p>
                ) : null}
              </div>
            </div>
          </div>
        )}

        {canReview ? (
          <>
            <Separator />
            <div className="flex flex-col gap-2 sm:flex-row sm:justify-end">
              <Button
                size="sm"
                onClick={onApprove}
                disabled={isApproving || isRejecting}
                className="bg-green-600 hover:bg-green-700"
              >
                {isApproving ? <Clock className="mr-1 size-3.5 animate-spin" /> : <Check className="mr-1 size-3.5" />}
                Approve launch
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={onReject}
                disabled={isApproving || isRejecting}
                className="text-destructive"
              >
                {isRejecting ? <Clock className="mr-1 size-3.5 animate-spin" /> : <X className="mr-1 size-3.5" />}
                Request changes
              </Button>
            </div>
          </>
        ) : action?.status && action.status !== "pending" ? (
          <div className="flex items-center gap-2 rounded-lg bg-muted p-3 text-sm text-muted-foreground">
            <CheckCircle2 className="size-4" />
            Review status: {action.status.replaceAll("_", " ")}
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}

function WorkflowSection({
  icon,
  label,
  title,
  description,
  meta,
  children,
}: {
  icon: React.ReactNode;
  label: string;
  title: string;
  description?: string;
  meta?: string;
  children?: React.ReactNode;
}) {
  return (
    <div className="rounded-lg border bg-background/60 p-3">
      <div className="mb-2 flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
        {icon}
        {label}
      </div>
      <p className="text-sm font-medium">{title}</p>
      {description ? <p className="mt-1 text-sm text-muted-foreground">{description}</p> : null}
      {meta ? <p className="mt-2 text-xs text-muted-foreground">{meta}</p> : null}
      {children}
    </div>
  );
}

function getWorkflowDetails({
  action,
  payload,
  context,
}: {
  action?: PendingAction;
  payload: Record<string, unknown>;
  context: Record<string, unknown>;
}): OutboundWorkflowDetails {
  const segment = getRecord(payload.segment) ?? getRecord(context.segment) ?? getRecord(payload.segment_preview);
  const offer = getRecord(payload.offer) ?? getRecord(context.offer) ?? getRecord(payload.selected_offer);
  const campaign = getRecord(payload.campaign) ?? getRecord(context.campaign);
  const responder =
    getRecord(payload.responder_agent) ??
    getRecord(payload.assigned_responder_agent) ??
    getRecord(context.responder_agent) ??
    getRecord(context.agent);
  const handoff = getRecord(payload.warm_lead_handoff) ?? getRecord(context.warm_lead_handoff) ?? getRecord(payload.handoff);

  const messagePreviews = getMessagePreviews(payload, context);
  const launchStatus = getString(payload.launch_status) ?? getString(campaign?.status) ?? getString(action?.execution_result?.status);
  const launchProgress = getNumber(payload.launch_progress) ?? getNumber(campaign?.progress);
  const segmentCount = getNumber(segment?.contact_count) ?? getNumber(segment?.count) ?? getNumber(payload.contact_count);

  return {
    title: getString(payload.title) ?? getString(campaign?.name) ?? action?.description ?? "Outbound workflow ready",
    summary:
      getString(payload.summary) ??
      getString(context.summary) ??
      "Review the audience, offer, messages, responder assignment, and handoff plan before launch.",
    segmentName: getString(segment?.name) ?? getString(payload.segment_name),
    segmentCount,
    segmentDescription: getString(segment?.description) ?? getString(payload.segment_description),
    offerName: getString(offer?.name) ?? getString(payload.offer_name),
    offerSummary: getString(offer?.headline) ?? getString(offer?.description) ?? getString(payload.offer_summary),
    messagePreviews,
    approvalLabel: getString(payload.approval_label) ?? getString(context.approval_label),
    approvalStatus: action?.status ?? getString(payload.approval_status),
    campaignName: getString(campaign?.name) ?? getString(payload.campaign_name),
    launchStatus,
    launchProgress,
    responderAgentName: getString(responder?.name) ?? getString(payload.responder_agent_name),
    responderAgentRole: getString(responder?.role) ?? getString(responder?.description) ?? getString(payload.responder_agent_role),
    handoffTitle: getString(handoff?.title) ?? getString(payload.handoff_title) ?? "Warm-lead handoff notification",
    handoffDescription:
      getString(handoff?.description) ??
      getString(handoff?.message) ??
      getString(payload.handoff_description) ??
      getString(context.handoff_description),
    metrics: getWorkflowMetrics(payload, context, segmentCount),
  };
}

function getWorkflowMetrics(
  payload: Record<string, unknown>,
  context: Record<string, unknown>,
  segmentCount?: number,
): WorkflowMetric[] {
  const metrics = getArray(payload.metrics)
    .map((metric) => getRecord(metric))
    .filter((metric): metric is Record<string, unknown> => Boolean(metric))
    .map((metric) => ({
      label: getString(metric.label) ?? "Metric",
      value: getString(metric.value) ?? String(getNumber(metric.value) ?? "—"),
      tone: getMetricTone(metric.tone),
    }));

  if (metrics.length > 0) return metrics;

  const estimatedReplies = getNumber(payload.estimated_replies) ?? getNumber(context.estimated_replies);
  const expectedAppointments = getNumber(payload.expected_appointments) ?? getNumber(context.expected_appointments);

  return [
    typeof segmentCount === "number" ? { label: "Audience", value: formatNumber(segmentCount) } : null,
    typeof estimatedReplies === "number" ? { label: "Est. replies", value: formatNumber(estimatedReplies), tone: "success" } : null,
    typeof expectedAppointments === "number"
      ? { label: "Est. appointments", value: formatNumber(expectedAppointments), tone: "success" }
      : null,
  ].filter((metric): metric is WorkflowMetric => Boolean(metric));
}

function getMessagePreviews(
  payload: Record<string, unknown>,
  context: Record<string, unknown>,
): WorkflowMessagePreview[] {
  const previewSource = getArray(payload.message_previews).length > 0
    ? getArray(payload.message_previews)
    : getArray(context.message_previews);

  const previews = previewSource
    .map((item, index) => {
      if (typeof item === "string") {
        return { channel: "sms", label: `Preview ${index + 1}`, body: item };
      }

      const record = getRecord(item);
      if (!record) return null;
      const body = getString(record.body) ?? getString(record.content) ?? getString(record.message);
      if (!body) return null;

      return {
        channel: getString(record.channel) ?? "sms",
        label: getString(record.label) ?? getString(record.name) ?? `Preview ${index + 1}`,
        body,
      };
    })
    .filter((preview): preview is WorkflowMessagePreview => Boolean(preview));

  const initialMessage = getString(payload.initial_message) ?? getString(payload.message) ?? getString(context.initial_message);
  const followUpMessage = getString(payload.follow_up_message) ?? getString(context.follow_up_message);

  if (previews.length > 0) return previews;

  return [
    initialMessage ? { channel: "sms", label: "Initial outreach", body: initialMessage } : null,
    followUpMessage ? { channel: "sms", label: "Follow-up", body: followUpMessage } : null,
  ].filter((preview): preview is WorkflowMessagePreview => Boolean(preview));
}

function hasWorkflowSignals(source: Record<string, unknown>) {
  return Boolean(
    source.segment ||
      source.segment_preview ||
      source.offer ||
      source.selected_offer ||
      source.message_previews ||
      source.launch_status ||
      source.responder_agent ||
      source.assigned_responder_agent ||
      source.warm_lead_handoff ||
      source.handoff,
  );
}

function getLaunchStatusClassName(status: string) {
  const normalized = status.toLowerCase();
  if (["running", "launched", "active", "sent"].includes(normalized)) return "bg-green-600";
  if (["scheduled", "queued", "pending"].includes(normalized)) return "bg-blue-600";
  if (["failed", "blocked"].includes(normalized)) return "bg-destructive";
  return "bg-muted text-muted-foreground";
}

function getMetricTone(value: unknown): WorkflowMetric["tone"] {
  if (value === "success" || value === "warning" || value === "default") return value;
  return undefined;
}

function getRecord(value: unknown): Record<string, unknown> | undefined {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    return value as Record<string, unknown>;
  }
  return undefined;
}

function getArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function getString(value: unknown): string | undefined {
  return typeof value === "string" && value.trim().length > 0 ? value : undefined;
}

function getNumber(value: unknown): number | undefined {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim().length > 0) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : undefined;
  }
  return undefined;
}
