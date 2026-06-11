"use client";

import { AlertTriangle, ArrowRight, CheckCircle2, XCircle } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { formatNumber } from "@/lib/utils/number";

export interface OnboardingLaunchSummary {
  source: "csv" | "fub";
  imported: number;
  skipped: number;
  failed: number;
  /** Pre-launch estimate from the leads step, used to flag a large divergence. */
  estimated: number | null;
}

interface LaunchResultViewProps {
  summary: OnboardingLaunchSummary;
  onGoToDashboard: () => void;
}

export function LaunchResultView({
  summary,
  onGoToDashboard,
}: LaunchResultViewProps) {
  const { source, imported, skipped, failed, estimated } = summary;
  const hasFailures = failed > 0;
  const importedNone = imported === 0;

  // Only surface a reconciliation note when the parsed estimate is meaningfully
  // off from what the API actually processed (e.g. malformed CSV rows). The
  // estimate is a naive newline count, so small drift is expected and noisy.
  const totalProcessed = imported + skipped + failed;
  const estimateDiverges =
    source === "csv" &&
    estimated !== null &&
    totalProcessed > 0 &&
    Math.abs(estimated - totalProcessed) / Math.max(estimated, totalProcessed) >
      0.1;

  return (
    <div className="space-y-6 p-8">
      <div className="flex flex-col items-center text-center gap-3">
        <div
          className={`flex items-center justify-center w-14 h-14 rounded-full ${
            importedNone
              ? "bg-warning/10 text-warning"
              : "bg-success/10 text-success"
          }`}
        >
          {importedNone ? (
            <AlertTriangle className="w-7 h-7" />
          ) : (
            <CheckCircle2 className="w-7 h-7" />
          )}
        </div>
        <div>
          <h2 className="text-2xl font-bold">
            {importedNone ? "No leads were imported" : "Campaign launched"}
          </h2>
          <p className="text-muted-foreground mt-1">
            {importedNone
              ? "Review the results below before continuing."
              : `${formatNumber(imported)} lead${
                  imported !== 1 ? "s" : ""
                } are now being contacted.`}
          </p>
        </div>
      </div>

      <Card className={hasFailures ? "border-warning/30" : undefined}>
        <CardContent className="p-5 space-y-3">
          <div className="grid grid-cols-3 gap-3 text-center">
            <div>
              <p className="text-2xl font-bold text-success">
                {formatNumber(imported)}
              </p>
              <p className="text-xs text-muted-foreground">Imported</p>
            </div>
            <div>
              <p className="text-2xl font-bold">{formatNumber(skipped)}</p>
              <p className="text-xs text-muted-foreground">
                Skipped (duplicates)
              </p>
            </div>
            <div>
              <p
                className={`text-2xl font-bold ${
                  hasFailures ? "text-destructive" : ""
                }`}
              >
                {formatNumber(failed)}
              </p>
              <p className="text-xs text-muted-foreground">Failed</p>
            </div>
          </div>

          {hasFailures && (
            <div className="flex items-start gap-2 rounded-md bg-destructive/10 p-3 text-sm text-destructive">
              <XCircle className="size-4 shrink-0 mt-0.5" />
              <span>
                {formatNumber(failed)} row{failed !== 1 ? "s" : ""} could not be
                imported (missing or invalid name/phone). Fix those rows in your
                CSV and re-upload from Contacts to add them.
              </span>
            </div>
          )}

          {estimateDiverges && (
            <p className="text-xs text-muted-foreground">
              Heads up: your file looked like ~{formatNumber(estimated ?? 0)}{" "}
              rows, but {formatNumber(totalProcessed)} were actually processed.
            </p>
          )}
        </CardContent>
      </Card>

      <Button className="w-full" size="lg" onClick={onGoToDashboard}>
        Go to dashboard
        <ArrowRight className="size-4 ml-2" />
      </Button>
    </div>
  );
}
