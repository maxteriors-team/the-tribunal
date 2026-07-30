"use client";

import { use } from "react";

import { AppSidebar } from "@/components/layout/app-sidebar";
import { ReferralPartnerDetail } from "@/components/referral-partners/referral-partner-detail";

interface ReferralPartnerRouteProps {
  params: Promise<{ partnerId: string }>;
}

export default function ReferralPartnerRoute({
  params,
}: ReferralPartnerRouteProps) {
  const { partnerId } = use(params);

  return (
    <AppSidebar>
      <div className="flex h-full flex-col overflow-hidden">
        <div className="min-h-0 flex-1 overflow-y-auto p-6">
          <ReferralPartnerDetail partnerId={partnerId} />
        </div>
      </div>
    </AppSidebar>
  );
}
