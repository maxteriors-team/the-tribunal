import { AppSidebar } from "@/components/layout/app-sidebar";
import { QuotesList } from "@/components/quotes/quotes-list";

export default function QuotesRoute() {
  return (
    <AppSidebar>
      <div className="flex h-full flex-col overflow-hidden">
        <div className="p-6 pb-3">
          <h1 className="text-2xl font-semibold tracking-tight">Quotes</h1>
          <p className="text-sm text-muted-foreground">
            Send estimates, approve them, and convert wins into jobs and invoices.
          </p>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-6 pb-6">
          <QuotesList />
        </div>
      </div>
    </AppSidebar>
  );
}
