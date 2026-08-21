"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { KanbanSquare, Loader2 } from "lucide-react";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { useSettingsSaveMutation } from "@/hooks/useSettingsSaveMutation";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import { type AutoPipelineSettings, settingsApi } from "@/lib/api/settings";
import { queryKeys } from "@/lib/query-keys";

/**
 * What lands on the Opportunities board without anyone typing it in.
 *
 * Two switches, not one, because the signals are not equal: a raw inbound lead
 * is somebody who filled in a form (off by default — they belong in Contacts
 * until contacted), while a sent quote means somebody was quoted a price (on by
 * default). Both write the same `auto_pipeline` settings namespace, so they are
 * saved together.
 */
export function PipelineSettingsTab() {
  const workspaceId = useWorkspaceId();
  const queryClient = useQueryClient();

  const { data: settings, isPending } = useQuery({
    queryKey: queryKeys.settings.autoPipeline(workspaceId ?? ""),
    queryFn: () => settingsApi.getAutoPipeline(workspaceId!),
    enabled: !!workspaceId,
  });

  const mutation = useSettingsSaveMutation({
    mutationFn: (data: AutoPipelineSettings) => settingsApi.updateAutoPipeline(workspaceId!, data),
    successMessage: "Pipeline automation is up to date.",
    errorMessage: "We couldn't save pipeline automation. Check your connection and try again.",
    onSuccess: (saved) => {
      queryClient.setQueryData(queryKeys.settings.autoPipeline(workspaceId!), saved);
    },
  });

  if (!workspaceId || isPending || !settings) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="size-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  const save = (patch: Partial<AutoPipelineSettings>) => mutation.mutate({ ...settings, ...patch });

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <KanbanSquare className="size-5" /> Automatic pipeline cards
        </CardTitle>
        <CardDescription>
          Which events put a deal on the Opportunities board on their own. You can always remove a
          card afterwards, and the <span className="font-medium">no-automation</span> contact tag
          stops both of these for one customer.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        <div className="flex items-start justify-between gap-4">
          <div className="space-y-0.5">
            <Label htmlFor="auto-pipeline-quote-sent">When a quote is sent</Label>
            <p className="text-sm text-muted-foreground">
              Moves the customer&apos;s open deal to{" "}
              <span className="font-medium">Quote Sent / Follow Up</span>, or opens one there if
              they have none. Fires once, on first send, and never moves a deal backwards.
            </p>
          </div>
          <Switch
            id="auto-pipeline-quote-sent"
            checked={settings.on_quote_sent}
            onCheckedChange={(on_quote_sent) => save({ on_quote_sent })}
            disabled={mutation.isPending}
          />
        </div>

        <div className="flex items-start justify-between gap-4">
          <div className="space-y-0.5">
            <Label htmlFor="auto-pipeline-leads">When a new lead comes in</Label>
            <p className="text-sm text-muted-foreground">
              Opens a card in the first stage for every inbound lead — forms, the chat widget, offer
              opt-ins, inbound texts and calls. Off by default: an uncontacted lead usually belongs
              in Contacts, not on the sales board.
            </p>
          </div>
          <Switch
            id="auto-pipeline-leads"
            checked={settings.enabled}
            onCheckedChange={(enabled) => save({ enabled })}
            disabled={mutation.isPending}
          />
        </div>
      </CardContent>
    </Card>
  );
}
