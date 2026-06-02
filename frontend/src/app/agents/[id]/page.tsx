"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  Code2,
  Trash2,
  Headphones,
  UserCircle,
  BookOpen,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { use, useState, useEffect, useRef, useMemo } from "react";
import { useForm, useWatch } from "react-hook-form";
import { toast } from "sonner";

import { ABTestDashboard } from "@/components/agents/ab-test-dashboard";
import { EmbedAgentDialog } from "@/components/agents/embed-agent-dialog";
import { PromptImprovementDialog } from "@/components/agents/prompt-improvement-dialog";
import { PromptPerformanceChart } from "@/components/agents/prompt-performance-chart";
import { PromptVersionHistory } from "@/components/agents/prompt-version-history";
import {
  TabTriggerWithErrors,
  BasicTab,
  VoiceTab,
  PromptTab,
  ToolsTab,
  AdvancedTab,
  HumanProfileTab,
  KnowledgeBaseTab,
} from "@/components/agents/tabs";
import { VoiceTestDialog } from "@/components/agents/voice-test-dialog";
import { AppSidebar } from "@/components/layout/app-sidebar";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Form } from "@/components/ui/form";
import { PageErrorState, PageLoadingState } from "@/components/ui/page-state";
import { Separator } from "@/components/ui/separator";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useAgent } from "@/hooks/useAgents";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import {
  EDIT_AGENT_FORM_DEFAULTS,
  agentToEditFormValues,
  buildUpdateAgentRequest,
  editAgentFormSchema,
  type EditAgentFormValues,
} from "@/lib/agents/agent-form";
import { getVoicesForProvider, resolveVoiceForProvider } from "@/lib/agents/agent-voice";
import { agentsApi, type UpdateAgentRequest } from "@/lib/api/agents";
import { getLanguagesForTier } from "@/lib/languages";
import { messages } from "@/lib/messages";
import { queryKeys } from "@/lib/query-keys";

interface EditAgentPageProps {
  params: Promise<{ id: string }>;
}

export default function EditAgentPage({ params }: EditAgentPageProps) {
  const { id: agentId } = use(params);
  const router = useRouter();
  const queryClient = useQueryClient();
  const workspaceId = useWorkspaceId();
  const [activeTab, setActiveTab] = useState("basic");
  const [isDeleting, setIsDeleting] = useState(false);
  const [isVoiceTestOpen, setIsVoiceTestOpen] = useState(false);
  const [isEmbedDialogOpen, setIsEmbedDialogOpen] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const isDeletingRef = useRef(false);

  const {
    data: agent,
    isPending,
    error,
  } = useAgent(workspaceId ?? "", agentId);

  // Redirect to agents list when agent is not found (404)
  useEffect(() => {
    if (error && typeof error === "object" && "response" in error) {
      const axiosError = error as { response?: { status?: number } };
      if (axiosError.response?.status === 404) {
        toast.error(messages.agents.notFound);
        router.replace("/agents");
      }
    }
  }, [error, router]);

  const form = useForm<EditAgentFormValues>({
    resolver: zodResolver(editAgentFormSchema),
    defaultValues: EDIT_AGENT_FORM_DEFAULTS,
  });

  // Track if form has been initialized with agent data
  const formInitialized = useRef(false);

  // Reset form when agent data loads
  useEffect(() => {
    if (agent && !formInitialized.current) {
      formInitialized.current = true;
      form.reset(agentToEditFormValues(agent));
    }
  }, [agent, form]);

  // Get available languages
  const availableLanguages = useMemo(() => {
    return getLanguagesForTier("premium");
  }, []);

  // Watch voice provider to show appropriate voices
  const voiceProvider = useWatch({ control: form.control, name: "voiceProvider" });
  const voices = getVoicesForProvider(voiceProvider);

  // Reset voice when provider changes if current voice isn't valid
  useEffect(() => {
    const currentVoice = form.getValues("voiceId");
    const resolved = resolveVoiceForProvider(voiceProvider, currentVoice);
    if (resolved !== currentVoice) {
      form.setValue("voiceId", resolved);
    }
  }, [voiceProvider, form]);

  // Watch tools for UI updates
  const enabledToolIds = useWatch({ control: form.control, name: "enabledToolIds" });

  // Handle delete — custom logic with query cancellation before navigation
  const handleDeleteAgent = async () => {
    if (!workspaceId) {
      toast.error(messages.workspace.notLoaded);
      return;
    }

    isDeletingRef.current = true;
    setIsDeleting(true);

    void queryClient.cancelQueries({ queryKey: queryKeys.agents.detail(workspaceId, agentId) });
    queryClient.removeQueries({ queryKey: queryKeys.agents.detail(workspaceId, agentId) });

    try {
      await agentsApi.delete(workspaceId, agentId);
      toast.success(messages.agents.deleted);
      router.replace("/agents");
    } catch {
      toast.error(messages.agents.deleteFailed);
      router.replace("/agents");
    }
  };

  async function onSubmit(data: EditAgentFormValues) {
    if (!workspaceId) {
      toast.error(messages.workspace.notLoaded);
      return;
    }

    const request: UpdateAgentRequest = buildUpdateAgentRequest(data);

    setIsSaving(true);
    try {
      await agentsApi.update(workspaceId, agentId, request);
      toast.success(messages.agents.updated);
      await queryClient.invalidateQueries({ queryKey: queryKeys.agents.all(workspaceId) });
      await queryClient.invalidateQueries({ queryKey: queryKeys.agents.detail(workspaceId, agentId) });
      router.push("/agents");
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : messages.agents.updateFailed;
      toast.error(errorMessage);
    } finally {
      setIsSaving(false);
    }
  }

  if (isPending) {
    return (
      <AppSidebar>
        <PageLoadingState className="min-h-full py-16" />
      </AppSidebar>
    );
  }

  if (error || !agent) {
    const is404 =
      error &&
      typeof error === "object" &&
      "response" in error &&
      (error as { response?: { status?: number } }).response?.status === 404;

    if (is404) {
      return (
        <AppSidebar>
          <PageLoadingState className="min-h-full py-16" />
        </AppSidebar>
      );
    }

    return (
      <AppSidebar>
        <div className="min-h-full space-y-6 p-6">
        <Button variant="ghost" asChild>
          <Link href="/agents">
            <ArrowLeft className="mr-2 h-4 w-4" />
            Back to Agents
          </Link>
        </Button>
          <PageErrorState
            message={error instanceof Error ? error.message : "Failed to load agent details"}
            onRetry={() => router.push("/agents")}
            retryLabel="Return to Agents"
          />
        </div>
      </AppSidebar>
    );
  }

  return (
    <AppSidebar>
      <div className="min-h-full space-y-4 p-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Button variant="ghost" size="icon" className="h-8 w-8" asChild>
            <Link href="/agents" aria-label="Back to agents">
              <ArrowLeft className="h-4 w-4" />
            </Link>
          </Button>
          <div className="flex items-center gap-2">
            <h1 className="text-xl font-semibold">{agent.name}</h1>
            <Badge variant={agent.is_active ? "default" : "secondary"} className="h-5 text-[10px]">
              {agent.is_active ? "Active" : "Inactive"}
            </Badge>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            className="h-8"
            onClick={() => setIsVoiceTestOpen(true)}
          >
            <Headphones className="mr-1.5 h-3.5 w-3.5" />
            Test Voice
          </Button>
          <Button
            variant="outline"
            size="sm"
            className="h-8"
            onClick={() => setIsEmbedDialogOpen(true)}
          >
            <Code2 className="mr-1.5 h-3.5 w-3.5" />
            Embed
          </Button>
          <AlertDialog>
          <AlertDialogTrigger asChild>
            <Button variant="destructive" size="sm" className="h-8">
              <Trash2 className="mr-1.5 h-3.5 w-3.5" />
              Delete
            </Button>
          </AlertDialogTrigger>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle className="text-destructive">
                Delete &ldquo;{agent.name}&rdquo;?
              </AlertDialogTitle>
              <AlertDialogDescription>
                This action cannot be undone. This will permanently delete the agent and all
                associated data.
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel>Cancel</AlertDialogCancel>
              <AlertDialogAction
                onClick={(e) => {
                  e.preventDefault();
                  void handleDeleteAgent();
                }}
                disabled={isDeleting}
                className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              >
                {isDeleting ? "Deleting..." : "Delete Permanently"}
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
          </AlertDialog>
        </div>
      </div>

      <VoiceTestDialog
        open={isVoiceTestOpen}
        onOpenChange={setIsVoiceTestOpen}
        agentId={agentId}
        agentName={agent.name}
        workspaceId={workspaceId ?? ""}
      />

      <EmbedAgentDialog
        open={isEmbedDialogOpen}
        onOpenChange={setIsEmbedDialogOpen}
        agentId={agentId}
        agentName={agent.name}
        workspaceId={workspaceId ?? ""}
      />

      <Form {...form}>
        <form
          onSubmit={(e) => {
            void form.handleSubmit(onSubmit)(e);
          }}
          className="space-y-4"
        >
          <Tabs value={activeTab} onValueChange={setActiveTab} className="w-full">
            <TabsList>
              <TabTriggerWithErrors value="basic" label="Basic" form={form} />
              <TabTriggerWithErrors value="voice" label="Voice" form={form} />
              <TabTriggerWithErrors value="prompt" label="AI Prompt" form={form} />
              <TabTriggerWithErrors value="tools" label="Tools" form={form} />
              <TabTriggerWithErrors value="advanced" label="Advanced" form={form} />
              <TabsTrigger value="versions">Versions</TabsTrigger>
              <TabsTrigger value="ab-testing">A/B Testing</TabsTrigger>
              <TabsTrigger value="my-human">
                <UserCircle className="mr-1.5 h-3.5 w-3.5" />
                My Human
              </TabsTrigger>
              <TabsTrigger value="knowledge-base">
                <BookOpen className="mr-1.5 h-3.5 w-3.5" />
                Knowledge
              </TabsTrigger>
            </TabsList>

            <TabsContent value="basic" className="mt-4 space-y-3">
              <BasicTab form={form} availableLanguages={availableLanguages} />
            </TabsContent>

            <TabsContent value="voice" className="mt-4 space-y-3">
              <VoiceTab form={form} voices={voices} />
            </TabsContent>

            <TabsContent value="prompt" className="mt-4 space-y-3">
              <PromptTab form={form} />
            </TabsContent>

            <TabsContent value="tools" className="mt-4 space-y-3">
              <ToolsTab form={form} voiceProvider={voiceProvider} enabledToolIds={enabledToolIds} />
            </TabsContent>

            <TabsContent value="advanced" className="mt-4 space-y-3">
              <AdvancedTab form={form} voiceProvider={voiceProvider} agent={agent} />
            </TabsContent>

            <TabsContent value="versions" className="mt-4 space-y-3">
              <Card>
                <CardHeader className="pb-3">
                  <CardTitle className="text-sm font-medium">Prompt Version History</CardTitle>
                </CardHeader>
                <CardContent>
                  <PromptVersionHistory agentId={agentId} />
                </CardContent>
              </Card>
              <PromptPerformanceChart agentId={agentId} />
            </TabsContent>

            <TabsContent value="ab-testing" className="mt-4 space-y-4">
              <div className="flex items-center justify-between">
                <div>
                  <h3 className="text-lg font-medium">A/B Testing</h3>
                  <p className="text-sm text-muted-foreground">
                    Compare prompt variations and optimize performance
                  </p>
                </div>
                <PromptImprovementDialog agentId={agentId} agentName={agent.name} />
              </div>
              <ABTestDashboard agentId={agentId} />
            </TabsContent>

            <TabsContent value="my-human" className="mt-4 space-y-4">
              <HumanProfileTab agentId={agentId} />
            </TabsContent>

            <TabsContent value="knowledge-base" className="mt-4 space-y-4">
              <KnowledgeBaseTab agentId={agentId} />
            </TabsContent>
          </Tabs>

          <Separator />

          <div className="flex justify-end gap-3">
            <Button
              type="button"
              variant="outline"
              size="sm"
              asChild
              disabled={isSaving}
            >
              <Link href="/agents">Cancel</Link>
            </Button>
            <Button type="submit" size="sm" disabled={isSaving}>
              {isSaving ? "Saving..." : "Save Changes"}
            </Button>
          </div>
        </form>
      </Form>
      </div>
    </AppSidebar>
  );
}
