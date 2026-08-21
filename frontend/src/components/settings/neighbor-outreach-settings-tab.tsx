"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, ShieldAlert } from "lucide-react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { useSettingsSaveMutation } from "@/hooks/useSettingsSaveMutation";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import { settingsApi, type UpdateNeighborOutreachSettings } from "@/lib/api/settings";
import { queryKeys } from "@/lib/query-keys";

// Mirrors the server bounds in app/services/field_service/jobsite_radius.py.
// Kept in sync so a value the API would 422 cannot be typed in the first place.
const MIN_RADIUS_METERS = 10;
const MAX_RADIUS_METERS = 5000;
const MAX_NEIGHBORS = 500;

/**
 * Job-site neighbor outreach settings.
 *
 * Every completed job can turn the surrounding street into leads. The controls
 * here are deliberately conservative: the radius is a block, not a market, and
 * the messaging switch is off by default because a radius search returns
 * addresses rather than permission to contact them.
 */
export function NeighborOutreachSettingsTab() {
  const workspaceId = useWorkspaceId();
  const queryClient = useQueryClient();

  const { data: settings, isPending } = useQuery({
    queryKey: queryKeys.settings.neighborOutreach(workspaceId ?? ""),
    queryFn: () => settingsApi.getNeighborOutreach(workspaceId!),
    enabled: !!workspaceId,
  });

  const mutation = useSettingsSaveMutation({
    mutationFn: (data: UpdateNeighborOutreachSettings) =>
      settingsApi.updateNeighborOutreach(workspaceId!, data),
    successMessage: "Neighbor outreach settings are up to date.",
    errorMessage:
      "We couldn't save neighbor outreach settings. Check your connection and try again.",
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.settings.neighborOutreach(workspaceId ?? ""),
      });
    },
  });

  const update = (data: UpdateNeighborOutreachSettings) => mutation.mutate(data);

  if (isPending) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="size-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  const enabled = settings?.enabled ?? false;

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>Neighbor Outreach</CardTitle>
          <CardDescription>
            Turn every completed job into leads from the surrounding street. The neighbors who
            watched your crew work are the warmest audience you have — it is what makes wrapped
            trucks and yard signs compound.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex items-center justify-between">
            <div className="space-y-0.5">
              <Label htmlFor="neighbors-enabled">Enable neighbor outreach</Label>
              <p className="text-sm text-muted-foreground">
                Build a list of nearby job sites when work finishes
              </p>
            </div>
            <Switch
              id="neighbors-enabled"
              checked={enabled}
              onCheckedChange={(checked) => update({ enabled: checked })}
              disabled={mutation.isPending}
            />
          </div>
        </CardContent>
      </Card>

      {enabled && (
        <Card>
          <CardHeader>
            <CardTitle>Search Area</CardTitle>
            <CardDescription>
              How far from the job site to look, and how many neighbors to work
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-6">
            <div className="space-y-2">
              <Label htmlFor="neighbors-radius">Radius (meters)</Label>
              <Input
                id="neighbors-radius"
                type="number"
                min={MIN_RADIUS_METERS}
                max={MAX_RADIUS_METERS}
                className="w-28"
                defaultValue={settings?.radius_meters ?? 150}
                onBlur={(e) => {
                  const value = parseInt(e.target.value, 10);
                  if (
                    Number.isFinite(value) &&
                    value >= MIN_RADIUS_METERS &&
                    value <= MAX_RADIUS_METERS &&
                    value !== settings?.radius_meters
                  ) {
                    update({ radius_meters: value });
                  }
                }}
                disabled={mutation.isPending}
              />
              <p className="text-sm text-muted-foreground">
                About 150 m is one block — the houses that actually saw the work.
              </p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="neighbors-max">Maximum neighbors per job</Label>
              <Input
                id="neighbors-max"
                type="number"
                min={1}
                max={MAX_NEIGHBORS}
                className="w-28"
                defaultValue={settings?.max_neighbors ?? 50}
                onBlur={(e) => {
                  const value = parseInt(e.target.value, 10);
                  if (
                    Number.isFinite(value) &&
                    value >= 1 &&
                    value <= MAX_NEIGHBORS &&
                    value !== settings?.max_neighbors
                  ) {
                    update({ max_neighbors: value });
                  }
                }}
                disabled={mutation.isPending}
              />
              <p className="text-sm text-muted-foreground">The closest ones are kept first.</p>
            </div>

            <div className="flex items-center justify-between">
              <div className="space-y-0.5">
                <Label htmlFor="neighbors-auto">Generate on job completion</Label>
                <p className="text-sm text-muted-foreground">
                  Build the list automatically the moment a job is marked complete
                </p>
              </div>
              <Switch
                id="neighbors-auto"
                checked={settings?.auto_generate_on_completion ?? true}
                onCheckedChange={(checked) => update({ auto_generate_on_completion: checked })}
                disabled={mutation.isPending}
              />
            </div>
          </CardContent>
        </Card>
      )}

      {enabled && (
        <Card>
          <CardHeader>
            <CardTitle>Channels</CardTitle>
            <CardDescription>
              Door hangers and direct mail always work. Texting and email do not.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <Alert>
              <ShieldAlert className="size-4" />
              <AlertDescription>
                A radius search returns addresses, not permission. Neighbors are exported for print
                and canvassing by default. Turning messaging on only unlocks it for neighbors who
                are <strong>already contacts in your CRM with recorded consent</strong> and are not
                opted out — everyone else stays print-only.
              </AlertDescription>
            </Alert>
            <div className="flex items-center justify-between">
              <div className="space-y-0.5">
                <Label htmlFor="neighbors-messaging">Allow SMS/email to consented neighbors</Label>
                <p className="text-sm text-muted-foreground">
                  Existing consented contacts only — never cold addresses
                </p>
              </div>
              <Switch
                id="neighbors-messaging"
                checked={settings?.allow_messaging ?? false}
                onCheckedChange={(checked) => update({ allow_messaging: checked })}
                disabled={mutation.isPending}
              />
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
