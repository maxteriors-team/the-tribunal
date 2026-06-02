"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { use } from "react";

import { AppSidebar } from "@/components/layout/app-sidebar";
import { OfferBuilderWizard } from "@/components/offers/offer-builder-wizard";
import { Button } from "@/components/ui/button";
import { PageErrorState, PageLoadingState } from "@/components/ui/page-state";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import { offersApi } from "@/lib/api/offers";
import { queryKeys } from "@/lib/query-keys";

interface EditOfferPageProps {
  params: Promise<{ id: string }>;
}

export default function EditOfferPage({ params }: EditOfferPageProps) {
  const { id: offerId } = use(params);
  const router = useRouter();
  const workspaceId = useWorkspaceId();

  const {
    data: offer,
    isPending,
    error,
  } = useQuery({
    queryKey: queryKeys.offers.detail(workspaceId ?? "", offerId),
    queryFn: () => offersApi.getWithLeadMagnets(workspaceId!, offerId),
    enabled: !!workspaceId,
  });

  if (isPending) {
    return (
      <AppSidebar>
        <PageLoadingState className="py-16" />
      </AppSidebar>
    );
  }

  if (error || !offer) {
    return (
      <AppSidebar>
        <div className="space-y-6 p-6">
          <Button variant="ghost" asChild>
            <Link href="/offers">
              <ArrowLeft className="mr-2 h-4 w-4" />
              Back to Offers
            </Link>
          </Button>
          <PageErrorState
            message={error instanceof Error ? error.message : "Failed to load offer details"}
            onRetry={() => router.push("/offers")}
            retryLabel="Return to Offers"
          />
        </div>
      </AppSidebar>
    );
  }

  return (
    <AppSidebar>
      <div className="p-6 max-w-4xl mx-auto">
        <div className="mb-6">
          <Button variant="ghost" size="sm" asChild className="mb-2">
            <Link href="/offers">
              <ArrowLeft className="mr-2 h-4 w-4" />
              Back to Offers
            </Link>
          </Button>
          <h1 className="text-2xl font-bold">Edit Offer</h1>
          <p className="text-muted-foreground">
            Update your offer details and value stack
          </p>
        </div>
        <OfferBuilderWizard
          workspaceId={workspaceId!}
          existingOffer={offer}
        />
      </div>
    </AppSidebar>
  );
}
