"use client";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import type { DiscountType } from "@/types";

import type { OfferFormData } from "./offer-builder-wizard";

interface PricingStepProps {
  formData: OfferFormData;
  onFieldChange: (updates: Partial<OfferFormData>) => void;
}

export function PricingStep({ formData, onFieldChange }: PricingStepProps) {
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-4">
        <div className="space-y-2">
          <Label htmlFor="offer-discount-type">Discount Type</Label>
          <Select
            value={formData.discount_type}
            onValueChange={(v) => onFieldChange({ discount_type: v as DiscountType })}
          >
            <SelectTrigger id="offer-discount-type">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="percentage">Percentage Off</SelectItem>
              <SelectItem value="fixed">Fixed Amount Off</SelectItem>
              <SelectItem value="free_service">Free Service</SelectItem>
            </SelectContent>
          </Select>
        </div>

        <div className="space-y-2">
          <Label htmlFor="discount_value">
            {formData.discount_type === "percentage" ? "Discount %" : "Discount Amount ($)"}
          </Label>
          <Input
            id="discount_value"
            type="number"
            min="0"
            value={formData.discount_value || ""}
            onChange={(e) =>
              onFieldChange({
                discount_value: parseFloat(e.target.value) || 0,
              })
            }
            disabled={formData.discount_type === "free_service"}
          />
        </div>
      </div>

      <Separator />

      <div className="grid grid-cols-2 gap-4">
        <div className="space-y-2">
          <Label htmlFor="regular_price">Regular Price ($)</Label>
          <Input
            id="regular_price"
            type="number"
            min="0"
            placeholder="e.g., 997"
            value={formData.regular_price || ""}
            onChange={(e) =>
              onFieldChange({
                regular_price: parseFloat(e.target.value) || 0,
              })
            }
          />
          <p className="text-xs text-muted-foreground">Anchor price (crossed out)</p>
        </div>

        <div className="space-y-2">
          <Label htmlFor="offer_price">Your Price ($)</Label>
          <Input
            id="offer_price"
            type="number"
            min="0"
            placeholder="e.g., 497"
            value={formData.offer_price || ""}
            onChange={(e) =>
              onFieldChange({
                offer_price: parseFloat(e.target.value) || 0,
              })
            }
          />
          <p className="text-xs text-muted-foreground">What they actually pay</p>
        </div>
      </div>

      <div className="space-y-2">
        <Label htmlFor="savings">Savings Amount ($)</Label>
        <Input
          id="savings"
          type="number"
          min="0"
          placeholder="Auto-calculated or custom"
          value={
            formData.savings_amount ||
            (formData.regular_price > 0 && formData.offer_price > 0
              ? formData.regular_price - formData.offer_price
              : "")
          }
          onChange={(e) =>
            onFieldChange({
              savings_amount: parseFloat(e.target.value) || 0,
            })
          }
        />
      </div>
    </div>
  );
}
