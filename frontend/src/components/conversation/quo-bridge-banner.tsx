import { ExternalLink, MessagesSquare } from "lucide-react";

import { Button } from "@/components/ui/button";
import { getValidatedQuoLink } from "@/lib/api/quo-links";

interface QuoBridgeBannerProps {
  replyUrl: string | null;
}

export function QuoBridgeBanner({ replyUrl }: QuoBridgeBannerProps) {
  const validatedReplyUrl = getValidatedQuoLink({
    source_provider: "quo",
    external_url: replyUrl,
  });

  return (
    <section aria-labelledby="quo-bridge-title" className="shrink-0 border-t bg-muted/40 px-4 py-3">
      <div className="mx-auto flex max-w-3xl flex-col gap-3 rounded-lg border bg-background p-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex min-w-0 gap-3">
          <MessagesSquare
            className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground"
            aria-hidden="true"
          />
          <div>
            <h3 id="quo-bridge-title" className="text-sm font-medium">
              This Quo thread is read-only in Tribunal
            </h3>
            <p className="mt-0.5 text-xs text-muted-foreground">
              Messages and calls are mirrored here. Reply in Quo to keep using this thread&apos;s
              number and provider.
            </p>
          </div>
        </div>
        {validatedReplyUrl ? (
          <Button size="sm" asChild className="shrink-0">
            <a href={validatedReplyUrl} target="_blank" rel="noopener noreferrer">
              Reply in Quo
              <ExternalLink className="ml-1.5 h-3.5 w-3.5" aria-hidden="true" />
              <span className="sr-only"> (opens in a new tab)</span>
            </a>
          </Button>
        ) : (
          <Button size="sm" disabled className="shrink-0" title="Waiting for a Quo sync link">
            Reply in Quo unavailable
          </Button>
        )}
      </div>
    </section>
  );
}
