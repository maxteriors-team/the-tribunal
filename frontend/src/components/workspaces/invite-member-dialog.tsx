"use client";

import { useState } from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import * as z from "zod";
import { Loader2 } from "lucide-react";

import {
  invitationsApi,
  type CreateInvitationRequest,
} from "@/lib/api/invitations";
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
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
  FormDescription,
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useWorkspaceId } from "@/hooks/use-workspace-id";

import { queryKeys } from "@/lib/query-keys";
const inviteFormSchema = z.object({
  email: z.email({ error: "Please enter a valid email address" }),
  role: z.enum(["admin", "member"]),
  message: z.string().max(500, { error: "Message must be 500 characters or less" }).optional(),
});

type InviteFormValues = z.infer<typeof inviteFormSchema>;

interface InviteMemberDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function InviteMemberDialog({ open, onOpenChange }: InviteMemberDialogProps) {
  const workspaceId = useWorkspaceId();
  const queryClient = useQueryClient();
  const [isSubmitting, setIsSubmitting] = useState(false);

  const form = useForm<InviteFormValues>({
    resolver: zodResolver(inviteFormSchema),
    defaultValues: {
      email: "",
      role: "member",
      message: "",
    },
  });

  const createInvitationMutation = useMutation({
    mutationFn: (data: CreateInvitationRequest) =>
      invitationsApi.create(workspaceId!, data),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: queryKeys.invitations.bare(workspaceId ?? ""),
      });
      queryClient.invalidateQueries({
        queryKey: queryKeys.settings.team(workspaceId ?? ""),
      });
      toast.success("Invitation sent successfully!");
      form.reset();
      onOpenChange(false);
    },
    onError: (error: Error) => {
      if (error.message.includes("already a member")) {
        form.setError("email", { message: "This user is already a member" });
      } else if (error.message.includes("already been sent")) {
        form.setError("email", {
          message: "An invitation has already been sent to this email",
        });
      } else {
        toast.error("Failed to send invitation. Please try again.");
      }
    },
    onSettled: () => {
      setIsSubmitting(false);
    },
  });

  const handleSubmit = (data: InviteFormValues) => {
    if (isSubmitting || !workspaceId) return;
    setIsSubmitting(true);

    createInvitationMutation.mutate({
      email: data.email,
      role: data.role,
      message: data.message || undefined,
    });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[450px]">
        <DialogHeader>
          <DialogTitle>Invite Team Member</DialogTitle>
          <DialogDescription>
            Send an email invitation to join your workspace.
          </DialogDescription>
        </DialogHeader>

        <Form {...form}>
          <form onSubmit={form.handleSubmit(handleSubmit)} className="space-y-4">
            <FormField
              control={form.control}
              name="email"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Email Address *</FormLabel>
                  <FormControl>
                    <Input
                      type="email"
                      placeholder="colleague@example.com"
                      {...field}
                    />
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
                  <Select
                    onValueChange={field.onChange}
                    defaultValue={field.value}
                  >
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

            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => onOpenChange(false)}
              >
                Cancel
              </Button>
              <Button type="submit" disabled={isSubmitting}>
                {isSubmitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                {isSubmitting ? "Sending..." : "Send Invitation"}
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  );
}
