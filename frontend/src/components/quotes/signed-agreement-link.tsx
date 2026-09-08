"use client";

import { FileCheck2 } from "lucide-react";

import type { SignedAgreementSummary } from "@/types/quote";

type SignedAgreementLinkProps = {
  workspaceId: string;
  quoteId: string;
  agreement: SignedAgreementSummary;
};

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatGeneratedAt(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

/**
 * Download link for the stored signed agreement PDF.
 *
 * A plain anchor rather than a fetch-and-blob: the endpoint is authenticated by
 * the same httpOnly cookies the browser attaches to any same-origin request, so
 * the link works without JavaScript ever holding the bytes or the token.
 *
 * The endpoint is on the authenticated router only. This document is not
 * reachable through the customer's public proposal link, which is exactly the
 * point of having a copy inside the CRM.
 */
export function SignedAgreementLink({
  workspaceId,
  quoteId,
  agreement,
}: SignedAgreementLinkProps) {
  return (
    <div className="space-y-1 border-t pt-3">
      <a
        href={`/api/v1/workspaces/${workspaceId}/quotes/${quoteId}/signed-agreement/download`}
        className="flex items-center gap-2 text-sm font-medium hover:underline"
        // The response is served as an attachment, so this opens a download
        // rather than a tab; target/rel keep it from replacing the dialog.
        target="_blank"
        rel="noopener noreferrer"
      >
        <FileCheck2 className="h-4 w-4 shrink-0" />
        Signed agreement
      </a>
      <p className="text-xs text-muted-foreground">
        Signed {formatGeneratedAt(agreement.generated_at)} ·{" "}
        {formatBytes(agreement.byte_size)}
      </p>
    </div>
  );
}
