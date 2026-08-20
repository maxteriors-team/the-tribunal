"use client";

import { MessageSquare, Tag } from "lucide-react";
import { motion } from "motion/react";

import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { insertPlaceholderAtCursor } from "@/lib/utils/placeholder";
import type { Offer } from "@/types";

import { OfferSelector } from "../offer-selector";
import type { WizardStep } from "../wizard-types";

export interface MessageStepFields {
  initial_message: string;
  offer_id?: string;
  follow_up_enabled: boolean;
  follow_up_delay_hours: number;
  follow_up_message: string;
  max_follow_ups: number;
}

/**
 * SMS-specific "Message" step: composes the initial outbound message,
 * optional offer attachment, and optional follow-up cadence.
 */
export function makeMessageStep<TStepId extends string, TFormData extends MessageStepFields>(opts: {
  id: TStepId;
  offers: Offer[];
  onCreateOffer?: (offer: Partial<Offer>) => Promise<void>;
}): WizardStep<TStepId, TFormData> {
  return {
    id: opts.id,
    label: "Message",
    icon: MessageSquare,
    validate: (data) =>
      !data.initial_message.trim() ? { initial_message: "Message is required" } : {},
    render: ({ formData, errors, updateField }) => {
      const setField = <K extends keyof MessageStepFields>(key: K, value: MessageStepFields[K]) =>
        updateField(
          key as unknown as keyof TFormData,
          value as unknown as TFormData[keyof TFormData],
        );

      const insertPlaceholder = (placeholder: string) =>
        insertPlaceholderAtCursor("initial-message", placeholder, formData.initial_message, (v) =>
          setField("initial_message", v),
        );

      return (
        <div className="space-y-6">
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <Label htmlFor="initial-message">Initial Message *</Label>
              <div className="flex items-center gap-1">
                <span className="text-xs text-muted-foreground mr-2">Insert:</span>
                {[
                  { label: "First Name", value: "{first_name}" },
                  { label: "Last Name", value: "{last_name}" },
                  { label: "Company", value: "{company_name}" },
                ].map((p) => (
                  <Button
                    key={p.value}
                    variant="outline"
                    size="sm"
                    className="text-xs h-7"
                    onClick={() => insertPlaceholder(p.value)}
                  >
                    {p.label}
                  </Button>
                ))}
              </div>
            </div>
            <Textarea
              id="initial-message"
              placeholder="Hi {first_name}, we have an amazing offer for you..."
              value={formData.initial_message}
              onChange={(e) => setField("initial_message", e.target.value)}
              rows={4}
              className={errors.initial_message ? "border-destructive" : ""}
            />
            {errors.initial_message && (
              <p className="text-sm text-destructive">{errors.initial_message}</p>
            )}
            <p className="text-xs text-muted-foreground">
              {formData.initial_message.length}/160 characters (standard SMS)
            </p>
          </div>

          <Separator />

          <div className="space-y-4">
            <h4 className="font-medium flex items-center gap-2">
              <Tag className="size-4" />
              Attach an Offer (Optional)
            </h4>
            <OfferSelector
              offers={opts.offers}
              selectedId={formData.offer_id}
              onSelect={(id) => setField("offer_id", id)}
              onCreateOffer={opts.onCreateOffer}
            />
          </div>

          <Separator />

          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <h4 className="font-medium">Follow-up Messages</h4>
                <p className="text-sm text-muted-foreground">
                  Automatically send follow-ups if no response
                </p>
              </div>
              <Switch
                aria-label="Follow-up messages"
                checked={formData.follow_up_enabled}
                onCheckedChange={(v) => setField("follow_up_enabled", v)}
              />
            </div>

            {formData.follow_up_enabled && (
              <motion.div
                initial={{ opacity: 0, height: 0 }}
                animate={{ opacity: 1, height: "auto" }}
                exit={{ opacity: 0, height: 0 }}
                className="space-y-4 pl-4 border-l-2 border-muted"
              >
                <div className="grid grid-cols-2 gap-4">
                  <div className="space-y-2">
                    <Label htmlFor="sms-follow-up-delay">Delay Before Follow-up</Label>
                    <Select
                      value={String(formData.follow_up_delay_hours)}
                      onValueChange={(v) => setField("follow_up_delay_hours", parseInt(v))}
                    >
                      <SelectTrigger id="sms-follow-up-delay">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="12">12 hours</SelectItem>
                        <SelectItem value="24">24 hours</SelectItem>
                        <SelectItem value="48">48 hours</SelectItem>
                        <SelectItem value="72">72 hours</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="sms-max-follow-ups">Max Follow-ups</Label>
                    <Select
                      value={String(formData.max_follow_ups)}
                      onValueChange={(v) => setField("max_follow_ups", parseInt(v))}
                    >
                      <SelectTrigger id="sms-max-follow-ups">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="1">1</SelectItem>
                        <SelectItem value="2">2</SelectItem>
                        <SelectItem value="3">3</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                </div>

                <div className="space-y-2">
                  <Label htmlFor="follow-up-message">Follow-up Message</Label>
                  <Textarea
                    id="follow-up-message"
                    placeholder="Just following up on my previous message..."
                    value={formData.follow_up_message}
                    onChange={(e) => setField("follow_up_message", e.target.value)}
                    rows={3}
                  />
                </div>
              </motion.div>
            )}
          </div>
        </div>
      );
    },
  };
}
