"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { Check, Loader2, Save } from "lucide-react";
import { useEffect, useState } from "react";
import { useForm, useWatch } from "react-hook-form";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { useSettingsSaveMutation } from "@/hooks/useSettingsSaveMutation";
import { workspacesApi } from "@/lib/api/workspaces";
import { TIMEZONE_OPTIONS } from "@/lib/constants";
import { queryKeys } from "@/lib/query-keys";
import {
  companyFormSchema,
  emptyCompanyFormValues,
  type CompanyFormValues,
} from "@/lib/schemas/team-settings";
import { useWorkspace } from "@/providers/workspace-provider";

interface CompanyInfoCardProps {
  workspaceId: string | null;
  canEditWorkspace: boolean;
}

/**
 * "Company Information" card — the GoHighLevel-style subaccount fields stored
 * on `workspace.settings`. Form values flow through react-hook-form so the
 * parent tab can stay focused on layout.
 */
export function CompanyInfoCard({ workspaceId, canEditWorkspace }: CompanyInfoCardProps) {
  const { currentWorkspace } = useWorkspace();
  const queryClient = useQueryClient();
  const [saved, setSaved] = useState(false);

  const workspaceSettings = currentWorkspace?.workspace.settings as
    | Record<string, unknown>
    | undefined;

  const form = useForm<CompanyFormValues>({
    resolver: zodResolver(companyFormSchema),
    defaultValues: emptyCompanyFormValues,
  });

  const timezone = useWatch({ control: form.control, name: "timezone" });

  useEffect(() => {
    if (!currentWorkspace) return;
    const s = workspaceSettings;
    form.reset({
      business_name: (s?.business_name as string) ?? "",
      phone: (s?.phone as string) ?? "",
      website: (s?.website as string) ?? "",
      address: (s?.address as string) ?? "",
      city: (s?.city as string) ?? "",
      state: (s?.state as string) ?? "",
      postal_code: (s?.postal_code as string) ?? "",
      country: (s?.country as string) ?? "",
      timezone: (s?.timezone as string) ?? "America/New_York",
    });
  }, [currentWorkspace, workspaceSettings, form]);

  const updateMutation = useSettingsSaveMutation({
    mutationFn: (data: Record<string, unknown>) =>
      workspacesApi.update(workspaceId!, {
        settings: {
          ...workspaceSettings,
          ...data,
        },
      }),
    successMessage: "Company information is up to date.",
    errorMessage: "We couldn't save company information. Check your connection and try again.",
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.workspaces.all() });
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    },
  });

  const onSubmit = (data: CompanyFormValues) => {
    updateMutation.mutate({
      business_name: data.business_name || undefined,
      phone: data.phone || undefined,
      website: data.website || undefined,
      address: data.address || undefined,
      city: data.city || undefined,
      state: data.state || undefined,
      postal_code: data.postal_code || undefined,
      country: data.country || undefined,
      timezone: data.timezone,
    });
  };

  return (
    <form onSubmit={form.handleSubmit(onSubmit)}>
      <Card>
        <CardHeader>
          <CardTitle>Company Information</CardTitle>
          <CardDescription>
            Business details for this workspace (GoHighLevel-style subaccount info)
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-4 md:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="businessName">Business Name</Label>
              <Input
                id="businessName"
                placeholder="Acme Inc."
                disabled={!canEditWorkspace}
                {...form.register("business_name")}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="companyPhone">Phone Number</Label>
              <Input
                id="companyPhone"
                type="tel"
                placeholder="+1 (555) 123-4567"
                disabled={!canEditWorkspace}
                {...form.register("phone")}
              />
            </div>
          </div>
          <div className="space-y-2">
            <Label htmlFor="companyWebsite">Website</Label>
            <Input
              id="companyWebsite"
              type="url"
              placeholder="https://example.com"
              disabled={!canEditWorkspace}
              {...form.register("website")}
            />
          </div>
          <Separator />
          <div className="space-y-2">
            <Label htmlFor="companyAddress">Street Address</Label>
            <Input
              id="companyAddress"
              placeholder="123 Main Street"
              disabled={!canEditWorkspace}
              {...form.register("address")}
            />
          </div>
          <div className="grid gap-4 md:grid-cols-3">
            <div className="space-y-2">
              <Label htmlFor="companyCity">City</Label>
              <Input
                id="companyCity"
                placeholder="San Francisco"
                disabled={!canEditWorkspace}
                {...form.register("city")}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="companyState">State / Province</Label>
              <Input
                id="companyState"
                placeholder="CA"
                disabled={!canEditWorkspace}
                {...form.register("state")}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="companyPostalCode">Postal Code</Label>
              <Input
                id="companyPostalCode"
                placeholder="94105"
                disabled={!canEditWorkspace}
                {...form.register("postal_code")}
              />
            </div>
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="companyCountry">Country</Label>
              <Input
                id="companyCountry"
                placeholder="United States"
                disabled={!canEditWorkspace}
                {...form.register("country")}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="companyTimezone">Timezone</Label>
              <Select
                value={timezone}
                onValueChange={(value) => form.setValue("timezone", value, { shouldDirty: true })}
                disabled={!canEditWorkspace}
              >
                <SelectTrigger id="companyTimezone">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {TIMEZONE_OPTIONS.map((tz) => (
                    <SelectItem key={tz.value} value={tz.value}>
                      {tz.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
          {!canEditWorkspace && (
            <p className="text-sm text-muted-foreground">
              Only workspace owners and admins can edit company information.
            </p>
          )}
        </CardContent>
        <CardFooter>
          {canEditWorkspace && (
            <Button type="submit" disabled={updateMutation.isPending}>
              {updateMutation.isPending ? (
                <>
                  <Loader2 className="mr-2 size-4 animate-spin" />
                  Saving...
                </>
              ) : saved ? (
                <>
                  <Check className="mr-2 size-4" />
                  Saved
                </>
              ) : (
                <>
                  <Save className="mr-2 size-4" />
                  Save Company Info
                </>
              )}
            </Button>
          )}
        </CardFooter>
      </Card>
    </form>
  );
}
