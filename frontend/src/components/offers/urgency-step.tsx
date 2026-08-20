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
import { Textarea } from "@/components/ui/textarea";
import type { UrgencyType } from "@/types";

import type { OfferFormData } from "./offer-builder-wizard";

interface UrgencyStepProps {
  formData: OfferFormData;
  onFieldChange: (updates: Partial<OfferFormData>) => void;
}

export function UrgencyStep({ formData, onFieldChange }: UrgencyStepProps) {
  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <Label htmlFor="offer-urgency-type">Urgency Type</Label>
        <Select
          value={formData.urgency_type}
          onValueChange={(v) => onFieldChange({ urgency_type: v as UrgencyType })}
        >
          <SelectTrigger id="offer-urgency-type">
            <SelectValue placeholder="Select urgency type (optional)" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="limited_time">Limited Time Offer</SelectItem>
            <SelectItem value="limited_quantity">Limited Quantity</SelectItem>
            <SelectItem value="expiring">Expiring Soon</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {formData.urgency_type && (
        <>
          <div className="space-y-2">
            <Label htmlFor="urgency_text">Urgency Message</Label>
            <Input
              id="urgency_text"
              placeholder="e.g., Offer ends Friday at midnight!"
              value={formData.urgency_text}
              onChange={(e) => onFieldChange({ urgency_text: e.target.value })}
            />
          </div>

          {formData.urgency_type === "limited_quantity" && (
            <div className="space-y-2">
              <Label htmlFor="scarcity_count">Spots Available</Label>
              <Input
                id="scarcity_count"
                type="number"
                min="0"
                placeholder="e.g., 10"
                value={formData.scarcity_count || ""}
                onChange={(e) =>
                  onFieldChange({
                    scarcity_count: parseInt(e.target.value) || 0,
                  })
                }
              />
            </div>
          )}
        </>
      )}

      <Separator />

      <div className="space-y-2">
        <Label htmlFor="cta_text">Call to Action Button Text</Label>
        <Input
          id="cta_text"
          placeholder="e.g., Get Started Now"
          value={formData.cta_text}
          onChange={(e) => onFieldChange({ cta_text: e.target.value })}
        />
      </div>

      <div className="space-y-2">
        <Label htmlFor="cta_subtext">CTA Subtext</Label>
        <Input
          id="cta_subtext"
          placeholder="e.g., Risk-free - Cancel anytime"
          value={formData.cta_subtext}
          onChange={(e) => onFieldChange({ cta_subtext: e.target.value })}
        />
      </div>

      <div className="space-y-2">
        <Label htmlFor="terms">Terms & Conditions</Label>
        <Textarea
          id="terms"
          placeholder="Any terms, restrictions, or fine print..."
          value={formData.terms}
          onChange={(e) => onFieldChange({ terms: e.target.value })}
          rows={2}
        />
      </div>
    </div>
  );
}
