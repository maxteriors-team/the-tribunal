"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Mail, Send } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { VirtualContactSelector } from "@/components/campaigns/virtual-contact-selector";
import { AppSidebar } from "@/components/layout/app-sidebar";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import {
  emailCampaignsApi,
  type CreateEmailCampaignRequest,
} from "@/lib/api/email-campaigns";
import { messages } from "@/lib/messages";
import { queryKeys } from "@/lib/query-keys";
import { getApiErrorMessage } from "@/lib/utils/errors";

export default function NewEmailCampaignPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const workspaceId = useWorkspaceId();

  const [name, setName] = useState("");
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());

  const createMutation = useMutation({
    mutationFn: async ({ startNow }: { startNow: boolean }) => {
      if (!workspaceId) throw new Error("Workspace not loaded");

      const data: CreateEmailCampaignRequest = {
        name: name.trim(),
        campaign_type: "email",
        email_subject: subject.trim(),
        initial_message: body.trim(),
      };
      const campaign = await emailCampaignsApi.create(workspaceId, data);

      const contactIds = Array.from(selectedIds);
      if (contactIds.length > 0) {
        await emailCampaignsApi.addContacts(workspaceId, campaign.id, contactIds);
      }
      if (startNow && contactIds.length > 0) {
        await emailCampaignsApi.start(workspaceId, campaign.id);
      }
      return campaign;
    },
    onSuccess: (campaign) => {
      toast.success(messages.campaigns.emailCreated);
      if (workspaceId) {
        queryClient.invalidateQueries({ queryKey: queryKeys.campaigns.all(workspaceId) });
      }
      router.push(`/campaigns/${campaign.id}`);
    },
    onError: (error) => {
      toast.error(getApiErrorMessage(error, messages.campaigns.emailCreateFailed));
    },
  });

  const canSubmit =
    !!workspaceId &&
    name.trim().length > 0 &&
    subject.trim().length > 0 &&
    body.trim().length > 0 &&
    !createMutation.isPending;

  return (
    <AppSidebar>
      <div className="flex h-full min-h-0 flex-col">
        <div className="flex items-center gap-4 px-6 py-4 border-b bg-background">
          <Button variant="ghost" size="icon" asChild>
            <Link href="/campaigns" aria-label="Back to campaigns">
              <ArrowLeft className="size-5" />
            </Link>
          </Button>
          <div className="flex items-center gap-2">
            <Mail className="size-5 text-primary" />
            <div>
              <h1 className="text-xl font-semibold">Create Email Campaign</h1>
              <p className="text-sm text-muted-foreground">
                Send a broadcast email to selected contacts via Resend
              </p>
            </div>
          </div>
        </div>

        <div className="flex-1 min-h-0 overflow-y-auto p-6">
          <div className="mx-auto max-w-3xl space-y-6">
            <Card>
              <CardHeader>
                <CardTitle>Message</CardTitle>
                <CardDescription>
                  Use {"{first_name}"} and {"{company_name}"} to personalize the subject and body.
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="space-y-2">
                  <Label htmlFor="name">Campaign Name</Label>
                  <Input
                    id="name"
                    placeholder="e.g., July Newsletter"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="subject">Subject Line</Label>
                  <Input
                    id="subject"
                    placeholder="Hi {first_name}, an update from Maxteriors"
                    value={subject}
                    onChange={(e) => setSubject(e.target.value)}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="body">Email Body</Label>
                  <Textarea
                    id="body"
                    placeholder="Write your message here…"
                    rows={10}
                    value={body}
                    onChange={(e) => setBody(e.target.value)}
                  />
                  <p className="text-xs text-muted-foreground">
                    An unsubscribe link is added automatically to every email (required for
                    marketing mail).
                  </p>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Recipients</CardTitle>
                <CardDescription>
                  {selectedIds.size > 0
                    ? `${selectedIds.size} contact${selectedIds.size === 1 ? "" : "s"} selected`
                    : "Select the contacts who should receive this email"}
                </CardDescription>
              </CardHeader>
              <CardContent>
                {workspaceId ? (
                  <VirtualContactSelector
                    workspaceId={workspaceId}
                    selectedIds={selectedIds}
                    onSelectionChange={setSelectedIds}
                  />
                ) : null}
              </CardContent>
            </Card>

            <div className="flex items-center justify-end gap-3">
              <Button
                variant="outline"
                onClick={() => createMutation.mutate({ startNow: false })}
                disabled={!canSubmit}
              >
                Save as Draft
              </Button>
              <Button
                onClick={() => createMutation.mutate({ startNow: true })}
                disabled={!canSubmit || selectedIds.size === 0}
              >
                <Send className="size-4" />
                Create &amp; Send
              </Button>
            </div>
          </div>
        </div>
      </div>
    </AppSidebar>
  );
}
