"use client";

import {
  Tag,
  Percent,
  DollarSign,
  Gift,
  Check,
  Plus,
  Calendar,
  Layers,
  Eye,
  FileText,
} from "lucide-react";
import { motion } from "motion/react";
import { useMemo, useState } from "react";

import { OfferPreview } from "@/components/offers/offer-preview";
import { GenericResourceSelector } from "@/components/shared/generic-resource-selector";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { formatDate } from "@/lib/utils/date";
import { formatNumber } from "@/lib/utils/number";
import type { Offer, DiscountType, LeadMagnet } from "@/types";

interface OfferSelectorProps {
  offers: Offer[];
  selectedId?: string;
  onSelect: (offerId: string | undefined) => void;
  onCreateOffer?: (offer: Partial<Offer>) => Promise<void>;
  /** Map of offer ID to its lead magnets for preview */
  offerLeadMagnets?: Record<string, LeadMagnet[]>;
}

const discountTypeIcons: Record<DiscountType, React.ReactNode> = {
  percentage: <Percent className="size-4" />,
  fixed: <DollarSign className="size-4" />,
  free_service: <Gift className="size-4" />,
};

const NO_OFFER_ID = "__none__";

type OfferRow =
  | { kind: "none"; id: typeof NO_OFFER_ID }
  | { kind: "offer"; id: string; offer: Offer };

const emptyNewOffer: Partial<Offer> = {
  name: "",
  description: "",
  discount_type: "percentage",
  discount_value: 0,
  terms: "",
  is_active: true,
};

function formatDiscount(offer: Offer): string {
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

export function OfferSelector({
  offers,
  selectedId,
  onSelect,
  onCreateOffer,
  offerLeadMagnets = {},
}: OfferSelectorProps) {
  const [showCreateDialog, setShowCreateDialog] = useState(false);
  const [previewOffer, setPreviewOffer] = useState<Offer | null>(null);
  const [newOffer, setNewOffer] = useState<Partial<Offer>>(emptyNewOffer);
  const [isCreating, setIsCreating] = useState(false);

  const activeOffers = useMemo(() => offers.filter((o) => o.is_active), [offers]);

  const rows = useMemo<OfferRow[]>(
    () => [
      { kind: "none", id: NO_OFFER_ID },
      ...activeOffers.map<OfferRow>((offer) => ({
        kind: "offer",
        id: offer.id,
        offer,
      })),
    ],
    [activeOffers],
  );

  const selectedRowIds: string[] = [selectedId ?? NO_OFFER_ID];

  const handleSelectionChange = (ids: (string | number)[]) => {
    const next = ids[0];
    if (next === undefined || next === NO_OFFER_ID) {
      onSelect(undefined);
      return;
    }
    onSelect(String(next));
  };

  const calculateTotalValue = (offer: Offer) => {
    const valueStackTotal = (offer.value_stack_items || [])
      .filter((item) => item.included)
      .reduce((sum, item) => sum + (item.value || 0), 0);
    const leadMagnets = offerLeadMagnets[offer.id] || offer.lead_magnets || [];
    const leadMagnetTotal = leadMagnets.reduce((sum, lm) => sum + (lm.estimated_value || 0), 0);
    return offer.total_value || valueStackTotal + leadMagnetTotal;
  };

  const handleCreate = async () => {
    if (!onCreateOffer || !newOffer.name) return;
    setIsCreating(true);
    try {
      await onCreateOffer(newOffer);
      setShowCreateDialog(false);
      setNewOffer(emptyNewOffer);
    } finally {
      setIsCreating(false);
    }
  };

  const header = (
    <div className="flex items-center justify-between">
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Tag className="size-4" />
        <span>Pair an offer with your campaign ({activeOffers.length} available)</span>
      </div>

      {onCreateOffer && (
        <Dialog open={showCreateDialog} onOpenChange={setShowCreateDialog}>
          <DialogTrigger asChild>
            <Button variant="outline" size="sm">
              <Plus className="size-4 mr-1" />
              Create Offer
            </Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Create New Offer</DialogTitle>
            </DialogHeader>
            <div className="space-y-4 py-4">
              <div className="space-y-2">
                <Label htmlFor="offer-name">Offer Name</Label>
                <Input
                  id="offer-name"
                  placeholder="e.g., Summer Sale 20% Off"
                  value={newOffer.name}
                  onChange={(e) => setNewOffer({ ...newOffer, name: e.target.value })}
                />
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label htmlFor="campaign-offer-discount-type">Discount Type</Label>
                  <Select
                    value={newOffer.discount_type}
                    onValueChange={(v) =>
                      setNewOffer({ ...newOffer, discount_type: v as DiscountType })
                    }
                  >
                    <SelectTrigger id="campaign-offer-discount-type">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="percentage">Percentage</SelectItem>
                      <SelectItem value="fixed">Fixed Amount</SelectItem>
                      <SelectItem value="free_service">Free Service</SelectItem>
                    </SelectContent>
                  </Select>
                </div>

                <div className="space-y-2">
                  <Label htmlFor="discount-value">
                    {newOffer.discount_type === "percentage" ? "Percentage" : "Amount ($)"}
                  </Label>
                  <Input
                    id="discount-value"
                    type="number"
                    min="0"
                    value={newOffer.discount_value}
                    onChange={(e) =>
                      setNewOffer({
                        ...newOffer,
                        discount_value: parseFloat(e.target.value) || 0,
                      })
                    }
                    disabled={newOffer.discount_type === "free_service"}
                  />
                </div>
              </div>

              <div className="space-y-2">
                <Label htmlFor="offer-description">Description</Label>
                <Textarea
                  id="offer-description"
                  placeholder="Brief description of the offer..."
                  value={newOffer.description}
                  onChange={(e) => setNewOffer({ ...newOffer, description: e.target.value })}
                  rows={2}
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="offer-terms">Terms & Conditions</Label>
                <Textarea
                  id="offer-terms"
                  placeholder="e.g., Valid for new customers only..."
                  value={newOffer.terms}
                  onChange={(e) => setNewOffer({ ...newOffer, terms: e.target.value })}
                  rows={2}
                />
              </div>

              <Button
                onClick={handleCreate}
                disabled={!newOffer.name || isCreating}
                className="w-full"
              >
                {isCreating ? "Creating..." : "Create Offer"}
              </Button>
            </div>
          </DialogContent>
        </Dialog>
      )}
    </div>
  );

  const noOffersHint = activeOffers.length === 0 && (
    <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
      <Tag className="size-12 mb-2 opacity-50" />
      <p>No offers available</p>
      {onCreateOffer && (
        <Button variant="link" onClick={() => setShowCreateDialog(true)} className="mt-1">
          Create your first offer
        </Button>
      )}
    </div>
  );

  const footer = (
    <>
      {noOffersHint}
      {selectedId && (
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          className="p-3 bg-success/10 rounded-lg border border-success/20 text-sm"
        >
          <p className="text-success">Use these placeholders in your message:</p>
          <code className="text-xs bg-muted px-1 py-0.5 rounded mt-1 inline-block">
            {"{offer_name}"} {"{offer_discount}"} {"{offer_terms}"}
          </code>
        </motion.div>
      )}

      <Dialog open={!!previewOffer} onOpenChange={() => setPreviewOffer(null)}>
        <DialogContent className="max-w-2xl max-h-[80vh] overflow-auto">
          <DialogHeader>
            <DialogTitle>Offer Preview</DialogTitle>
          </DialogHeader>
          {previewOffer && (
            <OfferPreview
              offer={previewOffer}
              leadMagnets={offerLeadMagnets[previewOffer.id] || previewOffer.lead_magnets || []}
            />
          )}
        </DialogContent>
      </Dialog>
    </>
  );

  const renderRow = (row: OfferRow, isSelected: boolean) => {
    const baseClass = `relative p-4 rounded-lg border-2 transition-colors ${
      isSelected ? "border-primary bg-primary/5" : "border-border hover:border-primary/50"
    }`;
    const checkBadge = isSelected ? (
      <div className="absolute top-3 right-3">
        <div className="size-5 rounded-full bg-primary flex items-center justify-center">
          <Check className="size-3 text-primary-foreground" />
        </div>
      </div>
    ) : null;

    if (row.kind === "none") {
      return (
        <div className={baseClass}>
          {checkBadge}
          <div className="flex items-center gap-3">
            <div className="size-10 rounded-full bg-muted flex items-center justify-center">
              <Tag className="size-5 text-muted-foreground" />
            </div>
            <div>
              <div className="font-medium">No Offer</div>
              <div className="text-sm text-muted-foreground">
                Send campaign without a special offer
              </div>
            </div>
          </div>
        </div>
      );
    }

    const { offer } = row;
    const totalValue = calculateTotalValue(offer);
    const leadMagnets = offerLeadMagnets[offer.id] || offer.lead_magnets || [];
    const valueStackCount = (offer.value_stack_items || []).filter((item) => item.included).length;

    return (
      <div className={baseClass}>
        {checkBadge}
        <div className="flex items-start gap-3">
          <div className="size-10 rounded-full bg-gradient-to-br from-success/20 to-success/5 flex items-center justify-center text-success">
            {discountTypeIcons[offer.discount_type]}
          </div>

          <div className="flex-1 min-w-0 pr-6">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="font-medium">{offer.name}</span>
              <Badge variant="secondary" className="bg-success/10 text-success">
                {formatDiscount(offer)}
              </Badge>
              {totalValue > 0 && (
                <Badge variant="outline" className="text-success border-success/20">
                  <DollarSign className="size-3 mr-0.5" />
                  {formatNumber(totalValue)} value
                </Badge>
              )}
              {valueStackCount > 0 && (
                <Badge variant="outline" className="gap-1">
                  <Layers className="size-3" />
                  {valueStackCount} items
                </Badge>
              )}
              {leadMagnets.length > 0 && (
                <Badge variant="outline" className="gap-1 text-info border-info/20">
                  <FileText className="size-3" />
                  {leadMagnets.length} bonus{leadMagnets.length > 1 ? "es" : ""}
                </Badge>
              )}
            </div>

            {offer.headline && (
              <p className="text-sm font-medium text-muted-foreground mt-1 line-clamp-1">
                {offer.headline}
              </p>
            )}

            {offer.description && !offer.headline && (
              <p className="text-sm text-muted-foreground mt-1 line-clamp-1">{offer.description}</p>
            )}

            <div className="flex items-center gap-2 mt-2">
              {(offer.valid_from || offer.valid_until) && (
                <div className="flex items-center gap-1 text-xs text-muted-foreground">
                  <Calendar className="size-3" />
                  {offer.valid_from && <span>From {formatDate(offer.valid_from)}</span>}
                  {offer.valid_until && <span>to {formatDate(offer.valid_until)}</span>}
                </div>
              )}

              {(offer.value_stack_items?.length || leadMagnets.length > 0 || offer.headline) && (
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-6 px-2 text-xs"
                  onClick={(e) => {
                    e.stopPropagation();
                    setPreviewOffer(offer);
                  }}
                >
                  <Eye className="size-3 mr-1" />
                  Preview
                </Button>
              )}
            </div>

            {offer.terms && !offer.headline && (
              <div className="mt-2 text-xs text-muted-foreground italic line-clamp-1">
                {offer.terms}
              </div>
            )}
          </div>
        </div>
      </div>
    );
  };

  return (
    <GenericResourceSelector<OfferRow>
      items={rows}
      getItemId={(row) => row.id}
      selectedIds={selectedRowIds}
      onSelectionChange={handleSelectionChange}
      multiple={false}
      allowDeselect={false}
      renderItem={renderRow}
      header={header}
      footer={footer}
      height={300}
    />
  );
}
