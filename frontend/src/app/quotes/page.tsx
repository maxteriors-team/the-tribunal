import { Calculator, Ruler } from "lucide-react";
import Link from "next/link";

import { AppSidebar } from "@/components/layout/app-sidebar";
import { QuotesList } from "@/components/quotes/quotes-list";
import { Button } from "@/components/ui/button";

export default function QuotesRoute() {
  return (
    <AppSidebar>
      <div className="flex h-full flex-col overflow-hidden">
        <div className="flex flex-col gap-4 p-6 pb-3 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">
              Quotes &amp; Estimates
            </h1>
            <p className="text-sm text-muted-foreground">
              Build a quote, design lights on a photo, then send, approve, and
              convert wins into jobs and invoices — all in one place.
            </p>
          </div>
          <div className="flex shrink-0 flex-wrap gap-2">
            <Button asChild size="sm">
              <Link href="/sales-wizard">
                <Calculator className="h-4 w-4" />
                Build a quote
              </Link>
            </Button>
            <Button asChild size="sm" variant="outline">
              <Link href="/estimator">
                <Ruler className="h-4 w-4" />
                Design on a photo
              </Link>
            </Button>
          </div>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-6 pb-6">
          <QuotesList />
        </div>
      </div>
    </AppSidebar>
  );
}
