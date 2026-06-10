"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { adLibraryApi, adLibraryQueryOptions } from "@/lib/api/ad-library";
import { queryKeys } from "@/lib/query-keys";
import { getApiErrorMessage } from "@/lib/utils/errors";

interface MonitorsPanelProps {
  workspaceId: string;
}

export function MonitorsPanel({ workspaceId }: MonitorsPanelProps) {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [keyword, setKeyword] = useState("");
  const [intervalHours, setIntervalHours] = useState(24);

  const monitorsQuery = useQuery({
    ...adLibraryQueryOptions.monitors(workspaceId),
    enabled: Boolean(workspaceId),
  });

  function invalidate() {
    queryClient.invalidateQueries({ queryKey: queryKeys.adLibrary.monitors(workspaceId) });
  }

  const createMutation = useMutation({
    mutationFn: () =>
      adLibraryApi.createMonitor(workspaceId, {
        name: name.trim(),
        search: {
          platform: "meta",
          country: "US",
          search_terms: keyword.trim(),
          max_results: 50,
          sort_by: "longest_running",
          use_thirdparty_fallback: false,
        },
        icp_thresholds: {
          min_continuity_score: 0.5,
          min_longest_running_days: 60,
          min_active_ads: 1,
          min_opportunity_score: 50,
          max_distinct_creatives: 8,
          max_active_creatives: 12,
          max_creative_refresh_rate: 4,
        },
        schedule_interval_hours: intervalHours,
        is_active: true,
      }),
    onSuccess: () => {
      toast.success("Monitor created");
      setName("");
      setKeyword("");
      invalidate();
    },
    onError: (error) => toast.error(getApiErrorMessage(error, "Couldn't create monitor")),
  });

  const toggleMutation = useMutation({
    mutationFn: ({ id, isActive }: { id: string; isActive: boolean }) =>
      adLibraryApi.updateMonitor(workspaceId, id, { is_active: isActive }),
    onSuccess: invalidate,
    onError: (error) => toast.error(getApiErrorMessage(error, "Couldn't update monitor")),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => adLibraryApi.deleteMonitor(workspaceId, id),
    onSuccess: () => {
      toast.success("Monitor deleted");
      invalidate();
    },
    onError: (error) => toast.error(getApiErrorMessage(error, "Couldn't delete monitor")),
  });

  const monitors = monitorsQuery.data ?? [];
  const canCreate = name.trim().length > 0 && keyword.trim().length > 0;

  return (
    <Card>
      <CardContent className="space-y-4 pt-6">
        <div>
          <h2 className="text-sm font-medium">Saved monitors</h2>
          <p className="text-xs text-muted-foreground">
            Re-scan saved ICP searches on a schedule to catch advertisers still
            running the same ad over time.
          </p>
        </div>

        <div className="grid gap-3 sm:grid-cols-[1fr_1fr_auto_auto] sm:items-end">
          <div className="space-y-1">
            <Label htmlFor="monitor-name">Name</Label>
            <Input
              id="monitor-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Stale roofers"
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="monitor-keyword">Keyword</Label>
            <Input
              id="monitor-keyword"
              value={keyword}
              onChange={(e) => setKeyword(e.target.value)}
              placeholder="roofing"
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="monitor-interval">Every (hrs)</Label>
            <Input
              id="monitor-interval"
              type="number"
              min={1}
              className="w-24"
              value={intervalHours}
              onChange={(e) => setIntervalHours(Number(e.target.value) || 24)}
            />
          </div>
          <Button
            disabled={!canCreate || createMutation.isPending}
            onClick={() => createMutation.mutate()}
          >
            Add monitor
          </Button>
        </div>

        {monitors.length > 0 ? (
          <ul className="divide-y rounded-md border">
            {monitors.map((monitor) => (
              <li
                key={monitor.id}
                className="flex items-center justify-between gap-3 p-3"
              >
                <div>
                  <p className="text-sm font-medium">{monitor.name}</p>
                  <p className="text-xs text-muted-foreground">
                    Every {monitor.schedule_interval_hours}h
                    {monitor.next_run_at
                      ? ` · next ${new Date(monitor.next_run_at).toLocaleString()}`
                      : ""}
                  </p>
                </div>
                <div className="flex items-center gap-3">
                  <Switch
                    checked={monitor.is_active}
                    onCheckedChange={(checked) =>
                      toggleMutation.mutate({ id: monitor.id, isActive: checked })
                    }
                  />
                  <Button
                    size="icon"
                    variant="ghost"
                    aria-label="Delete monitor"
                    onClick={() => deleteMutation.mutate(monitor.id)}
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-xs text-muted-foreground">No monitors yet.</p>
        )}
      </CardContent>
    </Card>
  );
}
