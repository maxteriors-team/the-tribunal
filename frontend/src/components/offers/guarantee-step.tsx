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
import { Textarea } from "@/components/ui/textarea";
import type { GuaranteeType } from "@/types";

import type { OfferFormData } from "./offer-builder-wizard";

interface GuaranteeStepProps {
  formData: OfferFormData;
  onFieldChange: (updates: Partial<OfferFormData>) => void;
}

export function GuaranteeStep({ formData, onFieldChange }: GuaranteeStepProps) {
  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <Label htmlFor="offer-guarantee-type">Guarantee Type</Label>
        <Select
          value={formData.guarantee_type}
          onValueChange={(v) => onFieldChange({ guarantee_type: v as GuaranteeType })}
        >
          <SelectTrigger id="offer-guarantee-type">
            <SelectValue placeholder="Select a guarantee type" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="money_back">Money-Back Guarantee</SelectItem>
            <SelectItem value="satisfaction">Satisfaction Guarantee</SelectItem>
            <SelectItem value="results">Results Guarantee</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {formData.guarantee_type && (
        <>
          <div className="space-y-2">
            <Label htmlFor="guarantee_days">Guarantee Period (Days)</Label>
            <Input
              id="guarantee_days"
              type="number"
              min="0"
              value={formData.guarantee_days || ""}
              onChange={(e) =>
                onFieldChange({
                  guarantee_days: parseInt(e.target.value) || 0,
                })
              }
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="guarantee_text">Custom Guarantee Text</Label>
            <Textarea
              id="guarantee_text"
              placeholder="e.g., If you don't see results in 30 days, we'll refund every penny..."
              value={formData.guarantee_text}
              onChange={(e) => onFieldChange({ guarantee_text: e.target.value })}
              rows={3}
            />
          </div>
        </>
      )}
    </div>
  );
}
