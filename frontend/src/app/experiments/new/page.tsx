"use client";

import { useQuery, useMutation } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";

import { MessageTestWizard } from "@/components/experiments/message-test-wizard";
import { AppSidebar } from "@/components/layout/app-sidebar";
import { Button } from "@/components/ui/button";
import { PageLoadingState } from "@/components/ui/page-state";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import { agentsApi } from "@/lib/api/agents";
import { contactsApi } from "@/lib/api/contacts";
import {
  messageTestsApi,
  type CreateMessageTestRequest,
} from "@/lib/api/message-tests";
import { phoneNumbersApi } from "@/lib/api/phone-numbers";
import { queryKeys } from "@/lib/query-keys";

export default function NewExperimentPage() {
  const router = useRouter();
  const workspaceId = useWorkspaceId();

  const { data: contacts = [], isPending: contactsLoading } = useQuery({
    queryKey: queryKeys.contacts.all(workspaceId ?? ""),
    queryFn: () => {
      if (!workspaceId) throw new Error("Workspace not loaded");
      return contactsApi.list(workspaceId);
    },
    enabled: !!workspaceId,
    select: (data) => data.items || data,
  });

  const { data: agents = [], isPending: agentsLoading } = useQuery({
    queryKey: queryKeys.agents.all(workspaceId ?? ""),
    queryFn: async () => {
      if (!workspaceId) throw new Error("Workspace not loaded");
      const response = await agentsApi.list(workspaceId);
      return response.items;
    },
    enabled: !!workspaceId,
  });

  const { data: phoneNumbers = [], isPending: phoneNumbersLoading } = useQuery({
    queryKey: queryKeys.phoneNumbers.all(workspaceId ?? ""),
    queryFn: async () => {
      if (!workspaceId) throw new Error("Workspace not loaded");
      const response = await phoneNumbersApi.list(workspaceId);
      return response.items;
    },
    enabled: !!workspaceId,
  });

  const createMutation = useMutation({
    mutationFn: async ({
      data,
      contactIds,
    }: {
      data: CreateMessageTestRequest;
      contactIds: number[];
    }) => {
      if (!workspaceId) throw new Error("Workspace not loaded");

      // Create the test
      const test = await messageTestsApi.create(workspaceId, data);

      // Add contacts
      if (contactIds.length > 0) {
        await messageTestsApi.addContacts(workspaceId, test.id, {
          contact_ids: contactIds,
        });
      }

      return test;
    },
    onSuccess: (test) => {
      toast.success("Experiment created successfully");
      router.push(`/experiments/${test.id}`);
    },
    onError: (error) => {
      toast.error(
        error instanceof Error ? error.message : "Failed to create experiment"
      );
    },
  });

  const handleSubmit = async (
    data: CreateMessageTestRequest,
    contactIds: number[]
  ) => {
    return createMutation.mutateAsync({ data, contactIds });
  };

  const isPending = contactsLoading || agentsLoading || phoneNumbersLoading;

  if (isPending) {
    return (
      <AppSidebar>
        <PageLoadingState className="min-h-full" />
      </AppSidebar>
    );
  }

  return (
    <AppSidebar>
      <div className="flex h-full min-h-0 flex-col">
        {/* Header */}
        <div className="flex items-center gap-4 px-6 py-4 border-b">
          <Button
            variant="ghost"
            size="icon"
            onClick={() => router.back()}
            aria-label="Go back"
          >
            <ArrowLeft className="size-5" />
          </Button>
          <div>
            <h1 className="text-xl font-semibold">New Message Experiment</h1>
            <p className="text-sm text-muted-foreground">
              A/B test different messages to find what resonates best
            </p>
          </div>
        </div>

        {/* Wizard */}
        <div className="flex-1 overflow-hidden">
          <MessageTestWizard
            workspaceId={workspaceId ?? undefined}
            contacts={Array.isArray(contacts) ? contacts : []}
            agents={Array.isArray(agents) ? agents : []}
            phoneNumbers={Array.isArray(phoneNumbers) ? phoneNumbers : []}
            onSubmit={handleSubmit}
            onCancel={() => router.back()}
            isSubmitting={createMutation.isPending}
          />
        </div>
      </div>
    </AppSidebar>
  );
}
