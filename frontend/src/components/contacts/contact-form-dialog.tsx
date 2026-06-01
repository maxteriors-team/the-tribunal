"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

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
import {
  contactsApi,
  type CreateContactRequest,
  type UpdateContactRequest,
} from "@/lib/api/contacts";
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

  const createContactMutation = useMutation({
    mutationFn: (data: CreateContactRequest) => {
      if (!workspaceId) throw new Error("Workspace not loaded");
      return contactsApi.create(workspaceId, data);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.contacts.bare(workspaceId ?? "") });
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
          queryKey: contactQueryKeys.get(workspaceId ?? "", contact.id),
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

      if (mode === "create") {
        const request: CreateContactRequest = {
          first_name: data.first_name,
          last_name: data.last_name || undefined,
          email: data.email || undefined,
          phone_number: data.phone_number,
          company_name: data.company_name || undefined,
          status: data.status as ContactStatus,
          tags: tagsArray,
          notes: data.notes || undefined,
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
        name="tags"
        render={({ field }) => (
          <FormItem>
            <FormLabel>Tags</FormLabel>
            <FormControl>
              <Input placeholder="vip, priority, follow-up" {...field} />
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
                <Input placeholder="123 Main St" {...field} />
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
