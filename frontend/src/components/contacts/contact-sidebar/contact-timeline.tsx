import { formatDate, formatRelative } from "@/lib/utils/date";
import { Clock, AlertTriangle, Flame } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import type { Contact, TimelineItem } from "@/types";

function engagementTier(score: number): "hot" | "warm" | "cold" {
  if (score >= 70) return "hot";
  if (score >= 30) return "warm";
  return "cold";
}

const TIER_CLASSES: Record<"hot" | "warm" | "cold", string> = {
  hot: "bg-emerald-500/15 text-emerald-600 border-emerald-500/30",
  warm: "bg-amber-500/15 text-amber-600 border-amber-500/30",
  cold: "bg-muted text-muted-foreground border-border",
};

type Sentiment = "positive" | "neutral" | "negative";

const SENTIMENT_LABELS: Record<Sentiment, string> = {
  positive: "Positive",
  neutral: "Neutral",
  negative: "Negative",
};

const SENTIMENT_CLASSES: Record<Sentiment, string> = {
  positive: "text-success",
  neutral: "text-muted-foreground",
  negative: "text-destructive",
};

interface ContactTimelineProps {
  contact: Contact;
  timeline: TimelineItem[];
}

export function ContactTimeline({ contact, timeline }: ContactTimelineProps) {
  const callCount = timeline.filter((t) => t.type === "call").length;
  const messageCount = timeline.filter((t) => t.type === "sms").length;
  const bookingCount = timeline.filter((t) => t.booking_outcome === "success").length;
  const lastActivity = timeline[timeline.length - 1];
  const engagementScore = contact.engagement_score ?? 0;
  const tier = engagementTier(engagementScore);

  const recentSentimentCalls = timeline
    .filter((t) => t.type === "call" && t.signals?.sentiment)
    .slice(-4);
  const sentimentSummary = (() => {
    if (recentSentimentCalls.length === 0) return null;
    const counts: Record<Sentiment, number> = { positive: 0, neutral: 0, negative: 0 };
    for (const call of recentSentimentCalls) {
      const s = call.signals?.sentiment as Sentiment | undefined;
      if (s) counts[s] += 1;
    }
    const [dominant, count] = (
      Object.entries(counts) as Array<[Sentiment, number]>
    ).sort((a, b) => b[1] - a[1])[0];
    return { sentiment: dominant, count, total: recentSentimentCalls.length };
  })();

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between px-2">
        <h3 className="text-sm font-medium text-muted-foreground">Activity</h3>
        <Badge variant="outline" className={`${TIER_CLASSES[tier]} text-xs gap-1`}>
          <Flame className="h-3 w-3" />
          Engagement {engagementScore}
        </Badge>
      </div>
      {contact.last_engaged_at && (
        <div className="flex items-center gap-2 px-2 text-xs text-muted-foreground">
          <Clock className="h-3 w-3" />
          <span>
            Last engaged{" "}
            {formatRelative(contact.last_engaged_at)}
          </span>
        </div>
      )}
      <div className="grid grid-cols-3 gap-3 px-2">
        <div className="bg-muted/50 rounded-lg p-3 text-center">
          <p className="text-2xl font-semibold">{callCount}</p>
          <p className="text-xs text-muted-foreground">Calls</p>
        </div>
        <div className="bg-muted/50 rounded-lg p-3 text-center">
          <p className="text-2xl font-semibold">{messageCount}</p>
          <p className="text-xs text-muted-foreground">Messages</p>
        </div>
        <div className="bg-muted/50 rounded-lg p-3 text-center">
          <p className="text-2xl font-semibold text-success">{bookingCount}</p>
          <p className="text-xs text-muted-foreground">Booked</p>
        </div>
      </div>
      {lastActivity && (
        <div className="flex items-center gap-2 px-2 text-xs text-muted-foreground">
          <Clock className="h-3 w-3" />
          <span>
            Last activity: {formatDate(lastActivity.timestamp, { pattern: "MMM d, h:mm a" })}
          </span>
        </div>
      )}
      {sentimentSummary && (
        <div className="flex items-center gap-2 px-2 text-xs">
          <span className="text-muted-foreground">Recent sentiment:</span>
          <span className={SENTIMENT_CLASSES[sentimentSummary.sentiment]}>
            {SENTIMENT_LABELS[sentimentSummary.sentiment]} ({sentimentSummary.count}/
            {sentimentSummary.total} calls)
          </span>
        </div>
      )}
      {(!!contact.noshow_count || contact.last_appointment_status) && (
        <div className="flex items-center gap-2 px-2 flex-wrap">
          {!!contact.noshow_count && contact.noshow_count > 0 && (
            <div className="flex items-center gap-1.5 text-xs text-warning">
              <AlertTriangle className="h-3 w-3" />
              <span>
                {contact.noshow_count} no-show{contact.noshow_count !== 1 ? "s" : ""}
              </span>
            </div>
          )}
          {contact.last_appointment_status && (
            <Badge
              variant={
                contact.last_appointment_status === "no_show"
                  ? "destructive"
                  : contact.last_appointment_status === "completed"
                    ? "default"
                    : "secondary"
              }
              className="text-xs"
            >
              Last: {contact.last_appointment_status.replace(/_/g, " ")}
            </Badge>
          )}
        </div>
      )}
    </div>
  );
}
