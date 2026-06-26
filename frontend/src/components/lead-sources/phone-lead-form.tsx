"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import {
  CampaignPicker,
  LeadSourcePicker,
} from "@/components/lead-sources/source-pickers";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  contactsApi,
  type CreateContactRequest,
} from "@/lib/api/contacts";
import { queryKeys } from "@/lib/query-keys";
import { getApiErrorMessage } from "@/lib/utils/errors";
import type { Contact } from "@/types";

interface PhoneLeadFormProps {
  workspaceId: string;
  onCreated?: (contact: Contact) => void;
}

/**
 * Manually log a phone/radio lead. Captures the contact and stamps the chosen
 * Phone/Radio lead source as both first- and latest-touch attribution so the
 * lead counts toward that channel's ROI.
 */
export function PhoneLeadForm({ workspaceId, onCreated }: PhoneLeadFormProps) {
  const queryClient = useQueryClient();
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [phone, setPhone] = useState("");
  const [leadSourceId, setLeadSourceId] = useState<string>();
  const [campaignId, setCampaignId] = useState<string>();
  const [notes, setNotes] = useState("");

  const canSubmit =
    firstName.trim() !== "" && phone.trim() !== "" && !!leadSourceId;

  const createMutation = useMutation({
    mutationFn: (data: CreateContactRequest) =>
      contactsApi.create(workspaceId, data),
    onSuccess: (contact) => {
      queryClient.invalidateQueries({
        queryKey: queryKeys.contacts.all(workspaceId),
      });
      queryClient.invalidateQueries({
        queryKey: queryKeys.leadSources.unattributed(workspaceId),
      });
      toast.success("Phone lead added");
      setFirstName("");
      setLastName("");
      setPhone("");
      setCampaignId(undefined);
      setNotes("");
      onCreated?.(contact);
    },
    onError: (err: unknown) =>
      toast.error(getApiErrorMessage(err, "Failed to add phone lead")),
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!canSubmit || !leadSourceId) return;
    createMutation.mutate({
      first_name: firstName.trim(),
      last_name: lastName.trim() || undefined,
      phone_number: phone.trim(),
      source: "phone",
      notes: notes.trim() || undefined,
      first_touch_lead_source_id: leadSourceId,
      latest_touch_lead_source_id: leadSourceId,
      first_touch_lead_source_campaign_id: campaignId,
      latest_touch_lead_source_campaign_id: campaignId,
      // Operator-logged calls are an exact, hand-verified attribution.
      attribution_confidence: 1,
    });
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-4" aria-label="Phone lead">
      <div className="grid grid-cols-2 gap-3">
        <div className="space-y-2">
          <Label htmlFor="phone-lead-first">First name</Label>
          <Input
            id="phone-lead-first"
            value={firstName}
            onChange={(e) => setFirstName(e.target.value)}
            required
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="phone-lead-last">Last name (optional)</Label>
          <Input
            id="phone-lead-last"
            value={lastName}
            onChange={(e) => setLastName(e.target.value)}
          />
        </div>
      </div>

      <div className="space-y-2">
        <Label htmlFor="phone-lead-phone">Phone number</Label>
        <Input
          id="phone-lead-phone"
          type="tel"
          placeholder="(555) 123-4567"
          value={phone}
          onChange={(e) => setPhone(e.target.value)}
          required
        />
      </div>

      <div className="space-y-2">
        <Label htmlFor="phone-lead-source">Phone / Radio source</Label>
        <LeadSourcePicker
          id="phone-lead-source"
          workspaceId={workspaceId}
          value={leadSourceId}
          onChange={(id) => {
            setLeadSourceId(id);
            setCampaignId(undefined);
          }}
          sourceType="phone_radio"
          placeholder="Which ad or station?"
        />
      </div>

      <div className="space-y-2">
        <Label htmlFor="phone-lead-campaign">Campaign (optional)</Label>
        <CampaignPicker
          id="phone-lead-campaign"
          workspaceId={workspaceId}
          leadSourceId={leadSourceId}
          value={campaignId}
          onChange={setCampaignId}
        />
      </div>

      <div className="space-y-2">
        <Label htmlFor="phone-lead-notes">Notes (optional)</Label>
        <Textarea
          id="phone-lead-notes"
          rows={2}
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
        />
      </div>

      <Button type="submit" disabled={!canSubmit || createMutation.isPending}>
        {createMutation.isPending && <Loader2 className="mr-2 size-4 animate-spin" />}
        Add phone lead
      </Button>
    </form>
  );
}
