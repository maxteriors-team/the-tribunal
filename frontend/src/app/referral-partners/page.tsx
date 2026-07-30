import { AppSidebar } from "@/components/layout/app-sidebar";
import { ReferralPartnersPage } from "@/components/referral-partners/referral-partners-page";

export default function ReferralPartnersRoute() {
  return (
    <AppSidebar>
      <div className="flex h-full flex-col overflow-hidden">
        <div className="p-6 pb-3">
          <h1 className="text-2xl font-semibold tracking-tight">
            Referral Partners
          </h1>
          <p className="max-w-3xl text-sm text-muted-foreground">
            The realtors, insurance agents, trades, and networking contacts who
            send you work. Referrals are credited by name, so you can see which
            partners actually produce and call the ones who have gone quiet.
          </p>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-6 pb-6">
          <ReferralPartnersPage />
        </div>
      </div>
    </AppSidebar>
  );
}
