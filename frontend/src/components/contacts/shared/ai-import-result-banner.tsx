"use client";

import Link from "next/link";
import { AlertCircle, CheckCircle2, XCircle } from "lucide-react";

import type { AIImportLeadsResponse } from "@/lib/api/find-leads-ai";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

interface AIImportResultBannerProps {
  result: AIImportLeadsResponse;
  showDetails: boolean;
  onToggleDetails: () => void;
}

export function AIImportResultBanner({
  result,
  showDetails,
  onToggleDetails,
}: AIImportResultBannerProps) {
  return (
    <Card
      className={
        result.imported > 0 ? "border-success/20 bg-success/10" : "border-warning/20 bg-warning/10"
      }
    >
      <CardContent className="p-4">
        <div className="flex items-center gap-4">
          {result.imported > 0 ? (
            <CheckCircle2 className="h-8 w-8 text-success" />
          ) : (
            <AlertCircle className="h-8 w-8 text-warning" />
          )}
          <div className="flex-1">
            <p className="font-medium">
              {result.imported > 0
                ? `Successfully imported ${result.imported} leads`
                : "No leads imported"}
            </p>
            <div className="flex gap-4 text-sm text-muted-foreground flex-wrap">
              {result.rejected_low_score > 0 && (
                <span className="flex items-center gap-1">
                  <XCircle className="h-3 w-3" />
                  {result.rejected_low_score} rejected below quality threshold
                </span>
              )}
              {result.enrichment_failed > 0 && (
                <span>{result.enrichment_failed} enrichment failed</span>
              )}
              {result.skipped_duplicates > 0 && (
                <span>{result.skipped_duplicates} duplicates skipped</span>
              )}
              {result.skipped_no_phone > 0 && (
                <span>{result.skipped_no_phone} skipped (no phone)</span>
              )}
            </div>
          </div>
          {result.imported > 0 && (
            <Button variant="outline" size="sm" asChild>
              <Link href="/contacts">View Contacts</Link>
            </Button>
          )}
        </div>
      </CardContent>
      {result.lead_details && result.lead_details.length > 0 && (
        <div className="border-t px-4 pb-4">
          <Button
            variant="ghost"
            size="sm"
            className="w-full mt-2 text-xs"
            onClick={onToggleDetails}
          >
            {showDetails ? "Hide" : "Show"} details ({result.lead_details.length} leads)
          </Button>
          {showDetails && (
            <div className="mt-2 max-h-64 overflow-y-auto space-y-1">
              {result.lead_details.map((detail, i) => (
                <div
                  key={i}
                  className={cn(
                    "flex items-center justify-between text-xs px-2 py-1.5 rounded",
                    detail.status === "imported" && "bg-success/10 text-success",
                    detail.status === "rejected_low_score" && "bg-warning/10 text-warning",
                    detail.status === "enrichment_failed" && "bg-destructive/10 text-destructive",
                    detail.status === "skipped_duplicate" && "bg-muted text-muted-foreground",
                    detail.status === "skipped_no_phone" && "bg-muted text-muted-foreground",
                  )}
                >
                  <div className="flex items-center gap-2 min-w-0">
                    {detail.status === "imported" && <CheckCircle2 className="h-3 w-3 shrink-0" />}
                    {detail.status === "rejected_low_score" && (
                      <XCircle className="h-3 w-3 shrink-0" />
                    )}
                    {detail.status === "enrichment_failed" && (
                      <AlertCircle className="h-3 w-3 shrink-0" />
                    )}
                    <span className="truncate font-medium">{detail.name}</span>
                    {detail.decision_maker_name && (
                      <span className="text-muted-foreground truncate">
                        ({detail.decision_maker_title || "Owner"}: {detail.decision_maker_name})
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    {detail.revenue_tier && (
                      <Badge variant="outline" className="text-[10px] px-1 py-0">
                        {detail.revenue_tier}
                      </Badge>
                    )}
                    {detail.lead_score != null && (
                      <Badge
                        variant="outline"
                        className={cn(
                          "text-[10px] px-1 py-0 font-semibold",
                          detail.lead_score >= 100
                            ? "text-success bg-success/10 border-success/20"
                            : detail.lead_score >= 80
                              ? "text-info bg-info/10 border-info/20"
                              : "text-warning bg-warning/10 border-warning/20",
                        )}
                      >
                        Score: {detail.lead_score}
                      </Badge>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </Card>
  );
}
