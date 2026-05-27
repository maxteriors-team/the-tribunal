"use client";

import { useQuery } from "@tanstack/react-query";
import { RefreshCw, Send, Sparkles, Clock, RotateCcw, Loader2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import {
  useFollowupSettings,
  useUpdateFollowupSettings,
  useGenerateFollowup,
  useSendFollowup,
  useResetFollowupCounter,
} from "@/hooks/useFollowups";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import { conversationsApi } from "@/lib/api/conversations";
import { useContactStore } from "@/lib/contact-store";
import { queryKeys } from "@/lib/query-keys";
import { formatRelative } from "@/lib/utils/date";
import type { Conversation } from "@/types";

const DELAY_OPTIONS = [
  { value: "1", label: "1 hour" },
  { value: "2", label: "2 hours" },
  { value: "4", label: "4 hours" },
  { value: "8", label: "8 hours" },
  { value: "12", label: "12 hours" },
  { value: "24", label: "24 hours" },
  { value: "48", label: "2 days" },
  { value: "72", label: "3 days" },
  { value: "168", label: "1 week" },
];

const MAX_COUNT_OPTIONS = [
  { value: "1", label: "1" },
  { value: "2", label: "2" },
  { value: "3", label: "3" },
  { value: "4", label: "4" },
  { value: "5", label: "5" },
];

export function FollowupSection() {
  const { selectedContact } = useContactStore();
  const workspaceId = useWorkspaceId();
  const [generatedMessagesByConversation, setGeneratedMessagesByConversation] =
    useState<Record<string, string>>({});

  // Fetch conversations to find the one for the current contact
  const { data: conversationsData } = useQuery({
    queryKey: queryKeys.conversations.byContact(workspaceId ?? "", selectedContact?.id),
    queryFn: () =>
      workspaceId
        ? conversationsApi.list(workspaceId, { page: 1, page_size: 100 })
        : Promise.resolve({ items: [], total: 0, page: 1, page_size: 100, pages: 0 }),
    enabled: !!workspaceId && !!selectedContact,
  });

  // Find the conversation for the current contact
  const contactConversation: Conversation | undefined = conversationsData?.items?.find(
    (conv) => conv.contact_id === selectedContact?.id
  );

  const conversationId = contactConversation?.id ?? "";
  const generatedMessage = generatedMessagesByConversation[conversationId] ?? "";

  const setGeneratedMessage = (message: string) => {
    if (!conversationId) return;

    setGeneratedMessagesByConversation((currentMessages) => ({
      ...currentMessages,
      [conversationId]: message,
    }));
  };

  // Hooks for followup management
  const { data: settings, isPending: isLoadingSettings } = useFollowupSettings(
    workspaceId ?? "",
    conversationId
  );
  const updateSettings = useUpdateFollowupSettings(workspaceId ?? "");
  const generateFollowup = useGenerateFollowup(workspaceId ?? "");
  const sendFollowup = useSendFollowup(workspaceId ?? "");
  const resetCounter = useResetFollowupCounter(workspaceId ?? "");

  const handleToggleEnabled = async (enabled: boolean) => {
    if (!conversationId) return;

    try {
      await updateSettings.mutateAsync({
        conversationId,
        settings: { enabled },
      });
      toast.success(enabled ? "Auto follow-up enabled" : "Auto follow-up disabled");
    } catch {
      toast.error("Failed to update settings");
    }
  };

  const handleDelayChange = async (value: string) => {
    if (!conversationId) return;

    try {
      await updateSettings.mutateAsync({
        conversationId,
        settings: { delay_hours: parseInt(value, 10) },
      });
    } catch {
      toast.error("Failed to update delay");
    }
  };

  const handleMaxCountChange = async (value: string) => {
    if (!conversationId) return;

    try {
      await updateSettings.mutateAsync({
        conversationId,
        settings: { max_count: parseInt(value, 10) },
      });
    } catch {
      toast.error("Failed to update max count");
    }
  };

  const handleGenerate = async () => {
    if (!conversationId) return;

    try {
      const result = await generateFollowup.mutateAsync({
        conversationId,
      });
      setGeneratedMessage(result.message);
      toast.success("Follow-up message generated");
    } catch {
      toast.error("Failed to generate message");
    }
  };

  const handleSend = async () => {
    if (!conversationId) return;

    try {
      await sendFollowup.mutateAsync({
        conversationId,
        message: generatedMessage || undefined,
      });
      setGeneratedMessage("");
      toast.success("Follow-up sent");
    } catch {
      toast.error("Failed to send follow-up");
    }
  };

  const handleReset = async () => {
    if (!conversationId) return;

    try {
      await resetCounter.mutateAsync(conversationId);
      toast.success("Counter reset");
    } catch {
      toast.error("Failed to reset counter");
    }
  };

  if (!selectedContact) {
    return (
      <div className="text-center py-8 text-sm text-muted-foreground">
        Select a contact to manage follow-ups
      </div>
    );
  }

  if (!contactConversation) {
    return (
      <div className="space-y-3">
        <div className="flex items-center gap-2">
          <RefreshCw className="h-4 w-4 text-info" />
          <h3 className="text-sm font-semibold">Follow-up</h3>
        </div>
        <p className="text-xs text-muted-foreground">
          No conversation yet. Start a conversation to enable follow-ups.
        </p>
      </div>
    );
  }

  const isGenerating = generateFollowup.isPending;
  const isSending = sendFollowup.isPending;
  const isUpdating = updateSettings.isPending;

  // Calculate time until next follow-up
  const nextFollowupText = settings?.next_followup_at
    ? formatRelative(settings.next_followup_at)
    : null;

  return (
    <div className="space-y-3">
      {/* Header */}
      <div className="flex items-center gap-2">
        <RefreshCw className="h-4 w-4 text-info" />
        <h3 className="text-sm font-semibold">Follow-up</h3>
        {nextFollowupText && settings?.enabled && (
          <Badge variant="secondary" className="text-xs ml-auto">
            Next: {nextFollowupText}
          </Badge>
        )}
      </div>

      {/* Auto Follow-up Settings Card */}
      <Card>
        <CardHeader className="py-3 px-4">
          <div className="flex items-center justify-between">
            <CardTitle className="text-sm font-medium">Auto Follow-up</CardTitle>
            <Switch
              checked={settings?.enabled ?? false}
              onCheckedChange={handleToggleEnabled}
              disabled={isLoadingSettings || isUpdating}
            />
          </div>
          <p className="text-xs text-muted-foreground">
            Send if no response
          </p>
        </CardHeader>
        <CardContent className="py-3 px-4 pt-0 space-y-3">
          {/* Delay Setting */}
          <div className="flex items-center justify-between gap-2">
            <Label className="text-xs text-muted-foreground">Send after</Label>
            <Select
              value={String(settings?.delay_hours ?? 24)}
              onValueChange={handleDelayChange}
              disabled={isLoadingSettings || isUpdating}
            >
              <SelectTrigger className="w-full sm:w-[120px] h-8">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {DELAY_OPTIONS.map((option) => (
                  <SelectItem key={option.value} value={option.value}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Max Count Setting */}
          <div className="flex items-center justify-between gap-2">
            <Label className="text-xs text-muted-foreground">Max follow-ups</Label>
            <Select
              value={String(settings?.max_count ?? 3)}
              onValueChange={handleMaxCountChange}
              disabled={isLoadingSettings || isUpdating}
            >
              <SelectTrigger className="w-full sm:w-[120px] h-8">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {MAX_COUNT_OPTIONS.map((option) => (
                  <SelectItem key={option.value} value={option.value}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Status */}
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <Clock className="h-3 w-3" />
              <span>
                {settings?.count_sent ?? 0} of {settings?.max_count ?? 3} sent
              </span>
            </div>
            {(settings?.count_sent ?? 0) > 0 && (
              <Button
                variant="ghost"
                size="sm"
                className="h-6 text-xs"
                onClick={handleReset}
                disabled={resetCounter.isPending}
              >
                <RotateCcw className="h-3 w-3 mr-1" />
                Reset
              </Button>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Manual Send Card */}
      <Card>
        <CardHeader className="py-3 px-4">
          <CardTitle className="text-sm font-medium">Send Now</CardTitle>
        </CardHeader>
        <CardContent className="py-3 px-4 pt-0 space-y-3">
          <Textarea
            placeholder="AI-generated message will appear here..."
            value={generatedMessage}
            onChange={(e) => setGeneratedMessage(e.target.value)}
            className="min-h-[80px] text-sm resize-none"
          />
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              className="flex-1"
              onClick={handleGenerate}
              disabled={isGenerating}
            >
              {isGenerating ? (
                <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />
              ) : (
                <Sparkles className="h-3.5 w-3.5 mr-1.5" />
              )}
              Generate
            </Button>
            <Button
              size="sm"
              className="flex-1"
              onClick={handleSend}
              disabled={isSending}
            >
              {isSending ? (
                <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />
              ) : (
                <Send className="h-3.5 w-3.5 mr-1.5" />
              )}
              Send
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
