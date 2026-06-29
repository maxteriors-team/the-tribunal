import { InvoicesList } from "@/components/invoices/invoices-list";
import { AppSidebar } from "@/components/layout/app-sidebar";

export default function InvoicesRoute() {
  return (
    <AppSidebar>
      <div className="flex h-full flex-col overflow-hidden">
        <div className="p-6 pb-3">
          <h1 className="text-2xl font-semibold tracking-tight">Invoices</h1>
          <p className="text-sm text-muted-foreground">
            Bill customers, collect payment, and track what&apos;s outstanding.
          </p>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-6 pb-6">
          <InvoicesList />
        </div>
      </div>
    </AppSidebar>
  );
}
