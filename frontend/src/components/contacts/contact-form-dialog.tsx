"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { LeadSourceField } from "@/components/lead-sources/lead-source-field";
import { ReferralPartnerPicker } from "@/components/referral-partners/referral-partner-picker";
import { AddressAutocompleteInput } from "@/components/shared/address-autocomplete-input";
import { ContactTagsField } from "@/components/tags/contact-tags-field";
import {
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { FormDialog } from "@/components/ui/form-dialog";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { contactQueryKeys } from "@/hooks/useContacts";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import type { AddressParts } from "@/lib/api/addresses";
import {
  contactsApi,
  type ManualContactCreatePayload,
  type UpdateContactRequest,
} from "@/lib/api/contacts";
import { leadSourcesApi } from "@/lib/api/lead-sources";
import { useContactStore } from "@/lib/contact-store";
import { useFormDialog } from "@/lib/forms/use-form-dialog";
import { messages } from "@/lib/messages";
import { queryKeys } from "@/lib/query-keys";
import {
  contactFormSchema,
  emptyContactFormValues,
  type ContactFormValues,
} from "@/lib/schemas/contact";
import type { Contact, ContactStatus } from "@/types";

type ContactFormDialogProps =
  | {
      mode: "create";
      contact?: undefined;
      open: boolean;
      onOpenChange: (open: boolean) => void;
    }
  | {
      mode: "edit";
      contact: Contact;
      open: boolean;
      onOpenChange: (open: boolean) => void;
    };

function contactToFormValues(contact: Contact): ContactFormValues {
  const tagsString = Array.isArray(contact.tags)
    ? contact.tags.join(", ")
    : typeof contact.tags === "string"
      ? contact.tags
      : "";

  return {
    first_name: contact.first_name || "",
    last_name: contact.last_name || "",
    email: contact.email || "",
    phone_number: contact.phone_number || "",
    company_name: contact.company_name || "",
    status: contact.status || "new",
    tags: tagsString,
    notes: contact.notes || "",
    lead_source_id: contact.first_touch_lead_source_id || "",
    referral_partner_id: contact.referral_partner_id || "",
    birthday: contact.important_dates?.birthday || "",
    anniversary: contact.important_dates?.anniversary || "",
    address_line1: contact.address_line1 || "",
    address_line2: contact.address_line2 || "",
    address_city: contact.address_city || "",
    address_state: contact.address_state || "",
    address_zip: contact.address_zip || "",
  };
}

export function ContactFormDialog(props: ContactFormDialogProps) {
  const { mode, open, onOpenChange } = props;
  const contact = mode === "edit" ? props.contact : undefined;

  const queryClient = useQueryClient();
  const { setSelectedContact } = useContactStore();
  const workspaceId = useWorkspaceId();

  const { data: captureSettings } = useQuery({
    queryKey: queryKeys.leadSources.captureSettings(workspaceId ?? ""),
    queryFn: () => leadSourcesApi.getCaptureSettings(workspaceId!),
    enabled: mode === "create" && !!workspaceId,
  });

  // Same query the LeadSourcePicker runs, so React Query serves both from one
  // fetch. Resolving the channel from the stored id (rather than remembering it
  // from the last onChange) keeps the partner field correct after a form reset.
  // Fetched in edit mode too: attribution is often only learned after the first
  // conversation, so it has to be correctable without recreating the contact.
  const { data: leadSources } = useQuery({
    queryKey: queryKeys.leadSources.all(workspaceId ?? ""),
    queryFn: () => leadSourcesApi.list(workspaceId!),
    enabled: !!workspaceId,
  });

  const createContactMutation = useMutation({
    mutationFn: (data: ManualContactCreatePayload) => {
      if (!workspaceId) throw new Error("Workspace not loaded");
      return contactsApi.manualCreate(workspaceId, data);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.contacts.all(workspaceId ?? "") });
      toast.success(messages.contacts.created);
    },
  });

  const updateContactMutation = useMutation({
    mutationFn: (data: UpdateContactRequest) => {
      if (!workspaceId) throw new Error("Workspace not loaded");
      if (!contact) throw new Error("Contact not provided");
      return contactsApi.update(workspaceId, contact.id, data);
    },
    onSuccess: (updatedContact) => {
      queryClient.invalidateQueries({ queryKey: contactQueryKeys.all(workspaceId ?? "") });
      if (contact) {
        queryClient.invalidateQueries({
          queryKey: contactQueryKeys.detail(workspaceId ?? "", contact.id),
        });
      }
      setSelectedContact(updatedContact);
      toast.success(messages.contacts.updated);
    },
  });

  const dialog = useFormDialog<ContactFormValues>({
    open,
    onOpenChange,
    schema: contactFormSchema,
    // For "edit", this changes when a different contact is selected — the hook
    // re-syncs the form while the dialog is open.
    defaultValues: contact ? contactToFormValues(contact) : emptyContactFormValues,
    errorFallback: mode === "create" ? messages.contacts.createFailed : messages.contacts.updateFailed,
    onTopLevelError: (message) => toast.error(message),
    onSubmit: async (data) => {
      const tagsArray = data.tags
        ? data.tags.split(",").map((tag) => tag.trim()).filter(Boolean)
        : undefined;

      // Resolve the channel from the submitted id rather than from render
      // state, so the payload can never disagree with what was selected.
      const submittedSourceIsReferral =
        leadSources?.find((source) => source.id === data.lead_source_id)
          ?.source_type === "referral_partner";

      if (mode === "create") {
        if (
          captureSettings?.require_lead_source_on_manual_create &&
          !data.lead_source_id
        ) {
          toast.error("Select how this contact heard about the business");
          return;
        }

        const request: ManualContactCreatePayload = {
          first_name: data.first_name,
          last_name: data.last_name || undefined,
          email: data.email || undefined,
          phone_number: data.phone_number,
          company_name: data.company_name || undefined,
          status: data.status as ContactStatus,
          tags: tagsArray,
          notes: data.notes || undefined,
          lead_source_id: data.lead_source_id || undefined,
          // Only sent for a referral-partner channel. Switching the channel away
          // from referrals must not leave a stale partner credited with the lead.
          referral_partner_id: submittedSourceIsReferral
            ? data.referral_partner_id || undefined
            : undefined,
          address_line1: data.address_line1 || undefined,
          address_line2: data.address_line2 || undefined,
          address_city: data.address_city || undefined,
          address_state: data.address_state || undefined,
          address_zip: data.address_zip || undefined,
        };
        await createContactMutation.mutateAsync(request);
        onOpenChange(false);
        return;
      }

      // Preserve existing custom important_dates entries while updating birthday/anniversary.
      const importantDates = {
        ...(contact?.important_dates ?? {}),
        birthday: data.birthday || undefined,
        anniversary: data.anniversary || undefined,
      };
      const hasImportantDates =
        importantDates.birthday ||
        importantDates.anniversary ||
        (importantDates.custom && importantDates.custom.length > 0);

      const request: UpdateContactRequest = {
        first_name: data.first_name,
        last_name: data.last_name || undefined,
        email: data.email || undefined,
        phone_number: data.phone_number,
        company_name: data.company_name || undefined,
        status: data.status as ContactStatus,
        tags: tagsArray,
        notes: data.notes || undefined,
        important_dates: hasImportantDates ? importantDates : null,
        // null (not undefined) so clearing the picker actually unsets the
        // source -- the API drops unset keys, which would silently keep it.
        first_touch_lead_source_id: data.lead_source_id || null,
        referral_partner_id: submittedSourceIsReferral
          ? data.referral_partner_id || null
          : null,
        address_line1: data.address_line1 || undefined,
        address_line2: data.address_line2 || undefined,
        address_city: data.address_city || undefined,
        address_state: data.address_state || undefined,
        address_zip: data.address_zip || undefined,
      };
      await updateContactMutation.mutateAsync(request);
      onOpenChange(false);
    },
  });

  const { form } = dialog;

  // The partner field only earns its space when the chosen channel is actually a
  // referral; asking "who referred them?" under a Google Ads source is noise.
  const selectedLeadSourceId = form.watch("lead_source_id");
  const isReferralPartnerSource =
    leadSources?.find((source) => source.id === selectedLeadSourceId)
      ?.source_type === "referral_partner";

  // The "require a source" policy is a *capture* rule for new contacts. Applying
  // it on edit would lock an operator out of saving any older contact that has
  // no source recorded -- the exact records they open the form to fix.
  const isSourceRequired =
    mode === "create" && !!captureSettings?.require_lead_source_on_manual_create;

  // Filling the rest of the address from one pick is the point of the lookup:
  // city/state/ZIP typed by hand are where duplicate addresses come from. Blank
  // fields from the provider are skipped so a pick can never wipe something the
  // operator already typed (an apartment number, say).
  const applyPickedAddress = (parts: AddressParts) => {
    const patch: Partial<Record<keyof ContactFormValues, string>> = {
      address_line1: parts.address_line1,
      address_line2: parts.address_line2,
      address_city: parts.address_city,
      address_state: parts.address_state,
      address_zip: parts.address_zip,
    };
    for (const [name, value] of Object.entries(patch)) {
      if (!value) continue;
      form.setValue(name as keyof ContactFormValues, value, {
        shouldDirty: true,
        shouldValidate: true,
      });
    }
  };

  const title = mode === "create" ? "Add New Contact" : "Edit Contact";
  const description =
    mode === "create"
      ? "Enter the contact details below. Required fields are marked with *."
      : "Update the contact details below. Required fields are marked with *.";
  const submitIdleLabel = mode === "create" ? "Create Contact" : "Save Changes";
  const submitBusyLabel = mode === "create" ? "Creating..." : "Saving...";

  return (
    <FormDialog
      dialog={dialog}
      open={open}
      title={title}
      description={description}
      submitLabel={submitIdleLabel}
      submitBusyLabel={submitBusyLabel}
      className="sm:max-w-[500px]"
    >
      <div className="grid grid-cols-2 gap-4">
        <FormField
          control={form.control}
          name="first_name"
          render={({ field }) => (
            <FormItem>
              <FormLabel>First Name *</FormLabel>
              <FormControl>
                <Input placeholder="John" {...field} />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />

        <FormField
          control={form.control}
          name="last_name"
          render={({ field }) => (
            <FormItem>
              <FormLabel>Last Name</FormLabel>
              <FormControl>
                <Input placeholder="Doe" {...field} />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />
      </div>

      <FormField
        control={form.control}
        name="phone_number"
        render={({ field }) => (
          <FormItem>
            <FormLabel>Phone Number *</FormLabel>
            <FormControl>
              <Input placeholder="+1 (555) 123-4567" {...field} />
            </FormControl>
            <FormMessage />
          </FormItem>
        )}
      />

      <FormField
        control={form.control}
        name="email"
        render={({ field }) => (
          <FormItem>
            <FormLabel>Email</FormLabel>
            <FormControl>
              <Input type="email" placeholder="john@example.com" {...field} />
            </FormControl>
            <FormMessage />
          </FormItem>
        )}
      />

      <FormField
        control={form.control}
        name="company_name"
        render={({ field }) => (
          <FormItem>
            <FormLabel>Company</FormLabel>
            <FormControl>
              <Input placeholder="Acme Inc." {...field} />
            </FormControl>
            <FormMessage />
          </FormItem>
        )}
      />

      <FormField
        control={form.control}
        name="status"
        render={({ field }) => (
          <FormItem>
            <FormLabel>Status</FormLabel>
            <Select onValueChange={field.onChange} value={field.value}>
              <FormControl>
                <SelectTrigger>
                  <SelectValue placeholder="Select status" />
                </SelectTrigger>
              </FormControl>
              <SelectContent>
                <SelectItem value="new">New</SelectItem>
                <SelectItem value="contacted">Contacted</SelectItem>
                <SelectItem value="qualified">Qualified</SelectItem>
                <SelectItem value="converted">Converted</SelectItem>
                <SelectItem value="lost">Lost</SelectItem>
              </SelectContent>
            </Select>
            <FormMessage />
          </FormItem>
        )}
      />

      <FormField
        control={form.control}
        name="lead_source_id"
        render={({ field }) => (
          <FormItem>
            <FormLabel>
              How did you hear about us?
              {isSourceRequired ? " *" : ""}
            </FormLabel>
            <FormControl>
              <LeadSourceField
                workspaceId={workspaceId ?? ""}
                value={field.value || undefined}
                onChange={(leadSourceId) => field.onChange(leadSourceId)}
                onClear={() => field.onChange("")}
                allowClear={!isSourceRequired}
                aria-label="How did you hear about us?"
              />
            </FormControl>
            <FormMessage />
          </FormItem>
        )}
      />

      {isReferralPartnerSource && (
        <FormField
          control={form.control}
          name="referral_partner_id"
          render={({ field }) => (
            <FormItem>
              <FormLabel>Which partner referred them?</FormLabel>
              <FormControl>
                <ReferralPartnerPicker
                  workspaceId={workspaceId ?? ""}
                  value={field.value || undefined}
                  onChange={(partnerId) => field.onChange(partnerId)}
                  onClear={() => field.onChange("")}
                  aria-label="Which partner referred them?"
                />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />
      )}

      <FormField
        control={form.control}
        name="tags"
        render={({ field }) => (
          <FormItem>
            <FormLabel>Tags</FormLabel>
            <FormControl>
              <ContactTagsField
                workspaceId={workspaceId ?? ""}
                value={field.value ?? ""}
                onChange={field.onChange}
              />
            </FormControl>
            <FormMessage />
          </FormItem>
        )}
      />

      {mode === "edit" && (
        <div className="grid grid-cols-2 gap-4">
          <FormField
            control={form.control}
            name="birthday"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Birthday</FormLabel>
                <FormControl>
                  <Input type="date" {...field} />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />

          <FormField
            control={form.control}
            name="anniversary"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Anniversary</FormLabel>
                <FormControl>
                  <Input type="date" {...field} />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
        </div>
      )}

      <div className="space-y-3 rounded-lg border p-3">
        <p className="text-sm font-medium">Mailing Address</p>
        <FormField
          control={form.control}
          name="address_line1"
          render={({ field }) => (
            <FormItem>
              <FormLabel>Address Line 1</FormLabel>
              <FormControl>
                <AddressAutocompleteInput
                  workspaceId={workspaceId ?? ""}
                  value={field.value ?? ""}
                  onValueChange={field.onChange}
                  onAddressPicked={applyPickedAddress}
                />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />
        <FormField
          control={form.control}
          name="address_line2"
          render={({ field }) => (
            <FormItem>
              <FormLabel>Address Line 2</FormLabel>
              <FormControl>
                <Input placeholder="Apt 4B" {...field} />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />
        <div className="grid grid-cols-2 gap-4">
          <FormField
            control={form.control}
            name="address_city"
            render={({ field }) => (
              <FormItem>
                <FormLabel>City</FormLabel>
                <FormControl>
                  <Input placeholder="New York" {...field} />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
          <FormField
            control={form.control}
            name="address_state"
            render={({ field }) => (
              <FormItem>
                <FormLabel>State</FormLabel>
                <FormControl>
                  <Input placeholder="NY" {...field} />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
        </div>
        <div className="grid grid-cols-2 gap-4">
          <FormField
            control={form.control}
            name="address_zip"
            render={({ field }) => (
              <FormItem>
                <FormLabel>ZIP Code</FormLabel>
                <FormControl>
                  <Input placeholder="10001" {...field} />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
        </div>
      </div>

      <FormField
        control={form.control}
        name="notes"
        render={({ field }) => (
          <FormItem>
            <FormLabel>Notes</FormLabel>
            <FormControl>
              <Textarea
                placeholder="Additional notes about this contact..."
                className="min-h-[80px]"
                {...field}
              />
            </FormControl>
            <FormMessage />
          </FormItem>
        )}
      />
    </FormDialog>
  );
}
