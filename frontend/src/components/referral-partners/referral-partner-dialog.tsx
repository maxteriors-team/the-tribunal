"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { useEffect } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import * as z from "zod";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Form,
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import {
  referralPartnersApi,
  type ReferralPartner,
  type ReferralPartnerType,
} from "@/lib/api/referral-partners";
import { queryKeys } from "@/lib/query-keys";
import { getApiErrorMessage } from "@/lib/utils/errors";

import { PARTNER_TYPE_OPTIONS } from "./partner-metrics";

const PARTNER_TYPE_VALUES = PARTNER_TYPE_OPTIONS.map((option) => option.value);

const schema = z.object({
  name: z.string().trim().min(1, { error: "Name is required" }),
  company: z.string(),
  partner_type: z.enum(PARTNER_TYPE_VALUES as [ReferralPartnerType, ...ReferralPartnerType[]]),
  // Optional, but must be a real address when supplied: the API rejects
  // anything else and a silent 422 reads as "save did nothing".
  email: z.union([z.literal(""), z.email({ error: "Enter a valid email" })]),
  phone: z.string(),
  notes: z.string(),
  is_active: z.boolean(),
});

type FormValues = z.infer<typeof schema>;

const DEFAULT_VALUES: FormValues = {
  name: "",
  company: "",
  partner_type: "realtor",
  email: "",
  phone: "",
  notes: "",
  is_active: true,
};

interface ReferralPartnerDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** When present the dialog edits this partner; otherwise it creates one. */
  partner?: ReferralPartner | null;
}

export function ReferralPartnerDialog({
  open,
  onOpenChange,
  partner,
}: ReferralPartnerDialogProps) {
  const workspaceId = useWorkspaceId();
  const queryClient = useQueryClient();
  const isEdit = Boolean(partner);

  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: DEFAULT_VALUES,
  });

  useEffect(() => {
    if (!open) return;
    form.reset(
      partner
        ? {
            name: partner.name,
            company: partner.company ?? "",
            partner_type: partner.partner_type,
            email: partner.email ?? "",
            phone: partner.phone ?? "",
            notes: partner.notes ?? "",
            is_active: partner.is_active,
          }
        : DEFAULT_VALUES,
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, partner]);

  const saveMutation = useMutation({
    mutationFn: async (values: FormValues): Promise<ReferralPartner> => {
      if (!workspaceId) throw new Error("No workspace selected");
      const payload = {
        name: values.name.trim(),
        company: values.company.trim() || null,
        partner_type: values.partner_type,
        email: values.email.trim() || null,
        phone: values.phone.trim() || null,
        notes: values.notes.trim() || null,
        is_active: values.is_active,
      };
      return partner
        ? referralPartnersApi.update(workspaceId, partner.id, payload)
        : referralPartnersApi.create(workspaceId, payload);
    },
    onSuccess: (saved) => {
      toast.success(isEdit ? `Updated ${saved.name}` : `Added ${saved.name}`);
      if (workspaceId) {
        void queryClient.invalidateQueries({
          queryKey: queryKeys.referralPartners.all(workspaceId),
        });
      }
      onOpenChange(false);
    },
    onError: (err: unknown) =>
      toast.error(getApiErrorMessage(err, "Failed to save referral partner")),
  });

  const handleOpenChange = (next: boolean) => {
    if (!next && saveMutation.isPending) return;
    onOpenChange(next);
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="flex max-h-[90vh] flex-col overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>
            {isEdit ? "Edit referral partner" : "New referral partner"}
          </DialogTitle>
          <DialogDescription>
            Track who sends you work by name, so you can see which partners
            actually produce and which have gone quiet.
          </DialogDescription>
        </DialogHeader>

        <Form {...form}>
          <form
            onSubmit={form.handleSubmit((values) => saveMutation.mutate(values))}
            className="space-y-4"
          >
            <FormField
              control={form.control}
              name="name"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Name</FormLabel>
                  <FormControl>
                    <Input placeholder="e.g. Dana Ruiz" {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <div className="grid gap-3 sm:grid-cols-2">
              <FormField
                control={form.control}
                name="company"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Company (optional)</FormLabel>
                    <FormControl>
                      <Input placeholder="e.g. Keller Williams" {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <FormField
                control={form.control}
                name="partner_type"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Relationship</FormLabel>
                    <Select onValueChange={field.onChange} value={field.value}>
                      <FormControl>
                        <SelectTrigger className="w-full">
                          <SelectValue />
                        </SelectTrigger>
                      </FormControl>
                      <SelectContent>
                        {PARTNER_TYPE_OPTIONS.map((option) => (
                          <SelectItem key={option.value} value={option.value}>
                            {option.label}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <FormMessage />
                  </FormItem>
                )}
              />
            </div>

            <div className="grid gap-3 sm:grid-cols-2">
              <FormField
                control={form.control}
                name="phone"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Phone (optional)</FormLabel>
                    <FormControl>
                      <Input
                        type="tel"
                        inputMode="tel"
                        placeholder="+1 (555) 123-4567"
                        {...field}
                      />
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
                    <FormLabel>Email (optional)</FormLabel>
                    <FormControl>
                      <Input
                        type="email"
                        placeholder="dana@example.com"
                        {...field}
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
            </div>

            <FormField
              control={form.control}
              name="notes"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Notes (optional)</FormLabel>
                  <FormControl>
                    <Textarea
                      placeholder="How you met, what they send, how they like to be contacted..."
                      className="min-h-[70px]"
                      {...field}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="is_active"
              render={({ field }) => (
                <FormItem className="flex items-center gap-2 space-y-0">
                  <FormControl>
                    <Switch
                      checked={field.value}
                      onCheckedChange={field.onChange}
                      aria-label="Active partner"
                    />
                  </FormControl>
                  <div>
                    <FormLabel className="!mt-0">Active</FormLabel>
                    <FormDescription>
                      Inactive partners stay on the scoreboard with their history
                      but drop out of the picker on new leads.
                    </FormDescription>
                  </div>
                </FormItem>
              )}
            />

            <DialogFooter className="gap-2">
              <Button
                type="button"
                variant="outline"
                onClick={() => handleOpenChange(false)}
                disabled={saveMutation.isPending}
              >
                Cancel
              </Button>
              <Button type="submit" disabled={saveMutation.isPending}>
                {saveMutation.isPending && (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                )}
                {isEdit ? "Save changes" : "Add partner"}
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  );
}
