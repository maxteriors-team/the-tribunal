"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { motion } from "motion/react";
import {
  Plus,
  Tag,
  Percent,
  DollarSign,
  Gift,
  MoreHorizontal,
  Edit,
  Trash2,
  Copy,
  Eye,
  Layers,
} from "lucide-react";

import { AppSidebar } from "@/components/layout/app-sidebar";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { PageEmptyState } from "@/components/ui/page-state";
import { Skeleton } from "@/components/ui/skeleton";

import { offersApi } from "@/lib/api/offers";
import { useWorkspaceId } from "@/hooks/use-workspace-id";
import { queryKeys } from "@/lib/query-keys";
import type { Offer, DiscountType } from "@/types";
import { formatNumber } from "@/lib/utils/number";

const discountTypeIcons: Record<DiscountType, React.ReactNode> = {
  percentage: <Percent className="size-4" />,
  fixed: <DollarSign className="size-4" />,
  free_service: <Gift className="size-4" />,
};

function formatDiscount(offer: Offer) {
  switch (offer.discount_type) {
    case "percentage":
      return `${offer.discount_value}% off`;
    case "fixed":
      return `$${offer.discount_value} off`;
    case "free_service":
      return "Free";
    default:
      return "";
  }
}

export default function OffersPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const workspaceId = useWorkspaceId();

  const [deleteOfferId, setDeleteOfferId] = useState<string | null>(null);

  const { data, isPending } = useQuery({
    queryKey: queryKeys.offers.bare(workspaceId ?? ""),
    queryFn: () => offersApi.list(workspaceId!),
    enabled: !!workspaceId,
  });

  const deleteMutation = useMutation({
    mutationFn: (offerId: string) => offersApi.delete(workspaceId!, offerId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.offers.bare(workspaceId ?? "") });
      setDeleteOfferId(null);
    },
  });

  const duplicateMutation = useMutation({
    mutationFn: (offer: Offer) =>
      offersApi.create(workspaceId!, {
        name: `${offer.name} (Copy)`,
        description: offer.description,
        discount_type: offer.discount_type,
        discount_value: offer.discount_value,
        terms: offer.terms,
        valid_from: offer.valid_from,
        valid_until: offer.valid_until,
        is_active: false,
        headline: offer.headline,
        subheadline: offer.subheadline,
        regular_price: offer.regular_price,
        offer_price: offer.offer_price,
        savings_amount: offer.savings_amount,
        guarantee_type: offer.guarantee_type,
        guarantee_days: offer.guarantee_days,
        guarantee_text: offer.guarantee_text,
        urgency_type: offer.urgency_type,
        urgency_text: offer.urgency_text,
        scarcity_count: offer.scarcity_count,
        value_stack_items: offer.value_stack_items,
        cta_text: offer.cta_text,
        cta_subtext: offer.cta_subtext,
        is_public: offer.is_public,
        public_slug: offer.public_slug,
        require_email: offer.require_email,
        require_phone: offer.require_phone,
        require_name: offer.require_name,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.offers.bare(workspaceId ?? "") });
    },
  });

  const offers = data?.items || [];
  const activeOffers = offers.filter((o) => o.is_active);

  return (
    <AppSidebar>
      <div className="p-6 space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold">Offers</h1>
            <p className="text-muted-foreground">
              Create irresistible offers with value stacking
            </p>
          </div>
          <Button onClick={() => router.push("/offers/new")}>
            <Plus className="size-4 mr-2" />
            Create Offer
          </Button>
        </div>

        {/* Stats */}
        <div className="grid grid-cols-3 gap-4">
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">
                Total Offers
              </CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-2xl font-bold">{offers.length}</p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">
                Active Offers
              </CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-2xl font-bold text-success">
                {activeOffers.length}
              </p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">
                With Lead Magnets
              </CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-2xl font-bold text-info">
                {offers.filter((o) => o.lead_magnets && o.lead_magnets.length > 0).length}
              </p>
            </CardContent>
          </Card>
        </div>

        {/* Offers List */}
        {isPending ? (
          <div className="space-y-4">
            {[1, 2, 3].map((i) => (
              <Skeleton key={i} className="h-32 w-full" />
            ))}
          </div>
        ) : offers.length === 0 ? (
          <Card>
            <CardContent className="py-4">
              <PageEmptyState
                title="No offers yet"
                description="Create your first irresistible offer with value stacking"
                icon={<Tag className="size-12" />}
                action={
                  <Button onClick={() => router.push("/offers/new")}>
                    <Plus className="size-4 mr-2" />
                    Create Your First Offer
                  </Button>
                }
              />
            </CardContent>
          </Card>
        ) : (
          <div className="space-y-4">
            {offers.map((offer) => (
              <motion.div
                key={offer.id}
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
              >
                <Card className={!offer.is_active ? "opacity-60" : ""}>
                  <CardContent className="p-6">
                    <div className="flex items-start justify-between">
                      <div className="flex items-start gap-4">
                        <div className="size-12 rounded-full bg-gradient-to-br from-success/20 to-success/5 flex items-center justify-center text-success">
                          {discountTypeIcons[offer.discount_type]}
                        </div>
                        <div>
                          <div className="flex items-center gap-2 flex-wrap">
                            <h3 className="font-semibold text-lg">{offer.name}</h3>
                            <Badge
                              variant="secondary"
                              className="bg-success/10 text-success"
                            >
                              {formatDiscount(offer)}
                            </Badge>
                            {!offer.is_active && (
                              <Badge variant="secondary">Inactive</Badge>
                            )}
                            {offer.value_stack_items && offer.value_stack_items.length > 0 && (
                              <Badge variant="outline" className="gap-1">
                                <Layers className="size-3" />
                                {offer.value_stack_items.length} items
                              </Badge>
                            )}
                            {offer.lead_magnets && offer.lead_magnets.length > 0 && (
                              <Badge variant="outline" className="gap-1 text-info border-info/20">
                                <Gift className="size-3" />
                                {offer.lead_magnets.length} bonuses
                              </Badge>
                            )}
                          </div>
                          {offer.headline && (
                            <p className="font-medium text-muted-foreground mt-1">
                              {offer.headline}
                            </p>
                          )}
                          {offer.description && (
                            <p className="text-sm text-muted-foreground mt-1 line-clamp-2">
                              {offer.description}
                            </p>
                          )}
                          {offer.total_value && offer.total_value > 0 && (
                            <p className="text-sm text-success mt-2">
                              Total Value: ${formatNumber(offer.total_value)}
                              {offer.offer_price && (
                                <span className="text-muted-foreground">
                                  {" "}
                                  • Your Price: ${formatNumber(offer.offer_price)}
                                </span>
                              )}
                            </p>
                          )}
                        </div>
                      </div>

                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <Button variant="ghost" size="icon" aria-label="Offer actions">
                            <MoreHorizontal className="size-4" />
                          </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end">
                          <DropdownMenuItem
                            onClick={() =>
                              router.push(`/offers/${offer.id}`)
                            }
                          >
                            <Edit className="size-4 mr-2" />
                            Edit
                          </DropdownMenuItem>
                          <DropdownMenuItem
                            onClick={() => router.push(`/offers/${offer.id}`)}
                          >
                            <Eye className="size-4 mr-2" />
                            Preview
                          </DropdownMenuItem>
                          <DropdownMenuItem
                            onClick={() => duplicateMutation.mutate(offer)}
                          >
                            <Copy className="size-4 mr-2" />
                            Duplicate
                          </DropdownMenuItem>
                          <DropdownMenuItem
                            className="text-destructive"
                            onClick={() => setDeleteOfferId(offer.id)}
                          >
                            <Trash2 className="size-4 mr-2" />
                            Delete
                          </DropdownMenuItem>
                        </DropdownMenuContent>
                      </DropdownMenu>
                    </div>
                  </CardContent>
                </Card>
              </motion.div>
            ))}
          </div>
        )}
      </div>

      {/* Delete Confirmation */}
      <AlertDialog
        open={!!deleteOfferId}
        onOpenChange={() => setDeleteOfferId(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete Offer</AlertDialogTitle>
            <AlertDialogDescription>
              Are you sure you want to delete this offer? This action cannot be
              undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => deleteOfferId && deleteMutation.mutate(deleteOfferId)}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </AppSidebar>
  );
}
