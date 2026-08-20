"use client";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { Textarea } from "@/components/ui/textarea";

import { AIOfferWriter } from "./ai-offer-writer";
import type { OfferFormData } from "./offer-builder-wizard";

interface BasicsStepProps {
  formData: OfferFormData;
  onFieldChange: (updates: Partial<OfferFormData>) => void;
  workspaceId: string;
}

export function BasicsStep({ formData, onFieldChange, workspaceId }: BasicsStepProps) {
  return (
    <div className="space-y-6">
      <div className="flex flex-col items-start gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0 space-y-1">
          <h4 className="font-medium">Basic Information</h4>
          <p className="text-sm text-muted-foreground">
            Define your offer or generate content with AI
          </p>
        </div>
        <AIOfferWriter
          workspaceId={workspaceId}
          onApply={(data) => {
            onFieldChange({
              headline: data.headline ?? formData.headline,
              subheadline: data.subheadline ?? formData.subheadline,
              value_stack_items: data.value_stack_items ?? formData.value_stack_items,
              guarantee_type: data.guarantee_type ?? formData.guarantee_type,
              guarantee_days: data.guarantee_days ?? formData.guarantee_days,
              guarantee_text: data.guarantee_text ?? formData.guarantee_text,
              urgency_type: data.urgency_type ?? formData.urgency_type,
              urgency_text: data.urgency_text ?? formData.urgency_text,
              scarcity_count: data.scarcity_count ?? formData.scarcity_count,
              cta_text: data.cta_text ?? formData.cta_text,
              cta_subtext: data.cta_subtext ?? formData.cta_subtext,
            });
          }}
        />
      </div>

      <Separator />

      <div className="space-y-2">
        <Label htmlFor="name">Offer Name *</Label>
        <Input
          id="name"
          placeholder="e.g., Ultimate Growth Package"
          value={formData.name}
          onChange={(e) => onFieldChange({ name: e.target.value })}
        />
      </div>

      <div className="space-y-2">
        <Label htmlFor="headline">Headline</Label>
        <Input
          id="headline"
          placeholder="e.g., Get 10X Results Without 10X The Work"
          value={formData.headline}
          onChange={(e) => onFieldChange({ headline: e.target.value })}
        />
        <p className="text-xs text-muted-foreground">A compelling headline that grabs attention</p>
      </div>

      <div className="space-y-2">
        <Label htmlFor="subheadline">Subheadline</Label>
        <Textarea
          id="subheadline"
          placeholder="Supporting text that expands on your headline..."
          value={formData.subheadline}
          onChange={(e) => onFieldChange({ subheadline: e.target.value })}
          rows={2}
        />
      </div>

      <div className="space-y-2">
        <Label htmlFor="description">Description</Label>
        <Textarea
          id="description"
          placeholder="Detailed description of what's included..."
          value={formData.description}
          onChange={(e) => onFieldChange({ description: e.target.value })}
          rows={3}
        />
      </div>
    </div>
  );
}
