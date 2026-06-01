"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import * as z from "zod";

import {
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
  FormDescription,
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
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import {
  invitationsApi,
  type CreateInvitationRequest,
} from "@/lib/api/invitations";
import { useFormDialog } from "@/lib/forms/use-form-dialog";
import { queryKeys } from "@/lib/query-keys";

const inviteFormSchema = z.object({
  email: z.email({ error: "Please enter a valid email address" }),
  role: z.enum(["admin", "member"]),
  message: z.string().max(500, { error: "Message must be 500 characters or less" }).optional(),
});

type InviteFormValues = z.infer<typeof inviteFormSchema>;

const defaultValues: InviteFormValues = {
  email: "",
  role: "member",
  message: "",
};

interface InviteMemberDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function InviteMemberDialog({ open, onOpenChange }: InviteMemberDialogProps) {
  const workspaceId = useWorkspaceId();
  const queryClient = useQueryClient();

  const createInvitationMutation = useMutation({
    mutationFn: (data: CreateInvitationRequest) => invitationsApi.create(workspaceId!, data),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: queryKeys.invitations.bare(workspaceId ?? ""),
      });
      queryClient.invalidateQueries({
        queryKey: queryKeys.settings.team(workspaceId ?? ""),
      });
      toast.success("Invitation sent successfully!");
    },
  });

  const dialog = useFormDialog<InviteFormValues>({
    open,
    onOpenChange,
    schema: inviteFormSchema,
    defaultValues,
    errorFallback: "Failed to send invitation. Please try again.",
    // Map known collision messages to a field error; otherwise toast.
    onTopLevelError: (message) => {
      if (message.includes("already a member")) {
        dialog.form.setError("email", { message: "This user is already a member" });
        return;
      }
      if (message.includes("already been sent")) {
        dialog.form.setError("email", {
          message: "An invitation has already been sent to this email",
        });
        return;
      }
      toast.error("Failed to send invitation. Please try again.");
    },
    onSubmit: async (data) => {
      if (!workspaceId) return;
      await createInvitationMutation.mutateAsync({
        email: data.email,
        role: data.role,
        message: data.message || undefined,
      });
      onOpenChange(false);
    },
  });

  const { form } = dialog;

  return (
    <FormDialog
      dialog={dialog}
      open={open}
      title="Invite Team Member"
      description="Send an email invitation to join your workspace."
      submitLabel="Send Invitation"
      submitBusyLabel="Sending..."
      className="sm:max-w-[450px]"
    >
      <FormField
        control={form.control}
        name="email"
        render={({ field }) => (
          <FormItem>
            <FormLabel>Email Address *</FormLabel>
            <FormControl>
              <Input type="email" placeholder="colleague@example.com" {...field} />
            </FormControl>
            <FormMessage />
          </FormItem>
        )}
      />

      <FormField
        control={form.control}
        name="role"
        render={({ field }) => (
          <FormItem>
            <FormLabel>Role *</FormLabel>
            <Select onValueChange={field.onChange} defaultValue={field.value}>
              <FormControl>
                <SelectTrigger>
                  <SelectValue placeholder="Select a role" />
                </SelectTrigger>
              </FormControl>
              <SelectContent>
                <SelectItem value="member">
                  <div>
                    <div className="font-medium">Member</div>
                    <div className="text-xs text-muted-foreground">
                      Can view and manage contacts, campaigns
                    </div>
                  </div>
                </SelectItem>
                <SelectItem value="admin">
                  <div>
                    <div className="font-medium">Admin</div>
                    <div className="text-xs text-muted-foreground">
                      Full access including team management
                    </div>
                  </div>
                </SelectItem>
              </SelectContent>
            </Select>
            <FormMessage />
          </FormItem>
        )}
      />

      <FormField
        control={form.control}
        name="message"
        render={({ field }) => (
          <FormItem>
            <FormLabel>Personal Message</FormLabel>
            <FormControl>
              <Textarea
                placeholder="Add a personal note to your invitation..."
                className="min-h-[80px]"
                {...field}
              />
            </FormControl>
            <FormDescription>
              Optional message to include in the invitation email
            </FormDescription>
            <FormMessage />
          </FormItem>
        )}
      />
    </FormDialog>
  );
}
