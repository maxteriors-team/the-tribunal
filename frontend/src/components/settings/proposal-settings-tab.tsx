"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { toast } from "sonner";

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
  proposalTemplateApi,
  type UpdateProposalTemplateRequest,
} from "@/lib/api/proposal-template";
import { queryKeys } from "@/lib/query-keys";
import { getApiErrorMessage } from "@/lib/utils/errors";

export function ProposalSettingsTab() {
  const workspaceId = useWorkspaceId();
  const queryClient = useQueryClient();

  const { data: settings, isPending } = useQuery({
    queryKey: queryKeys.proposalTemplate.settings(workspaceId ?? ""),
    queryFn: () => proposalTemplateApi.get(workspaceId!),
    enabled: !!workspaceId,
  });

  const mutation = useMutation({
    mutationFn: (data: UpdateProposalTemplateRequest) =>
      proposalTemplateApi.update(workspaceId!, data),
    onSuccess: (updated) => {
      queryClient.setQueryData(
        queryKeys.proposalTemplate.settings(workspaceId ?? ""),
        updated,
      );
      toast.success("Proposal settings saved");
    },
    onError: (err: unknown) =>
      toast.error(getApiErrorMessage(err, "Failed to save proposal settings")),
  });

  const update = (data: UpdateProposalTemplateRequest) => mutation.mutate(data);
  const disabled = mutation.isPending;

  if (isPending || !settings) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="size-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>Proposal Branding</CardTitle>
          <CardDescription>
            These control how your client-facing proposals look. Edit them
            anytime — every proposal you send re-renders with the latest
            branding, no developer needed.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          <div className="space-y-2">
            <Label htmlFor="business-name">Business name</Label>
            <Input
              id="business-name"
              placeholder="Maxteriors Lighting"
              defaultValue={settings.business_name ?? ""}
              onBlur={(e) => update({ business_name: e.target.value || null })}
              disabled={disabled}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="logo-url">Logo URL</Label>
            <div className="flex items-center gap-3">
              <Input
                id="logo-url"
                placeholder="https://…/logo.png"
                defaultValue={settings.logo_url ?? ""}
                onBlur={(e) => update({ logo_url: e.target.value || null })}
                disabled={disabled}
              />
              {settings.logo_url ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={settings.logo_url}
                  alt="Logo preview"
                  className="h-10 w-10 rounded object-contain border"
                />
              ) : null}
            </div>
            <p className="text-xs text-muted-foreground">
              Paste a public URL to your logo image (PNG or SVG works best).
            </p>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="brand-color">Brand color</Label>
              <div className="flex items-center gap-2">
                <input
                  id="brand-color"
                  type="color"
                  className="h-9 w-12 cursor-pointer rounded border bg-transparent"
                  defaultValue={settings.brand_color}
                  onBlur={(e) => update({ brand_color: e.target.value })}
                  disabled={disabled}
                  aria-label="Brand color"
                />
                <Input
                  className="w-28"
                  defaultValue={settings.brand_color}
                  onBlur={(e) =>
                    e.target.value && update({ brand_color: e.target.value })
                  }
                  disabled={disabled}
                />
              </div>
            </div>
            <div className="space-y-2">
              <Label htmlFor="accent-color">Accent color</Label>
              <div className="flex items-center gap-2">
                <input
                  id="accent-color"
                  type="color"
                  className="h-9 w-12 cursor-pointer rounded border bg-transparent"
                  defaultValue={settings.accent_color}
                  onBlur={(e) => update({ accent_color: e.target.value })}
                  disabled={disabled}
                  aria-label="Accent color"
                />
                <Input
                  className="w-28"
                  defaultValue={settings.accent_color}
                  onBlur={(e) =>
                    e.target.value && update({ accent_color: e.target.value })
                  }
                  disabled={disabled}
                />
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Business Details</CardTitle>
          <CardDescription>
            Shown in the proposal header so clients know who it is from.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          <div className="space-y-2">
            <Label htmlFor="business-address">Address</Label>
            <Input
              id="business-address"
              placeholder="123 Main St, Springfield, IL"
              defaultValue={settings.business_address ?? ""}
              onBlur={(e) =>
                update({ business_address: e.target.value || null })
              }
              disabled={disabled}
            />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="business-phone">Phone</Label>
              <Input
                id="business-phone"
                placeholder="(555) 010-0100"
                defaultValue={settings.business_phone ?? ""}
                onBlur={(e) =>
                  update({ business_phone: e.target.value || null })
                }
                disabled={disabled}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="business-email">Email</Label>
              <Input
                id="business-email"
                placeholder="hello@maxteriors.com"
                defaultValue={settings.business_email ?? ""}
                onBlur={(e) =>
                  update({ business_email: e.target.value || null })
                }
                disabled={disabled}
              />
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Proposal Content</CardTitle>
          <CardDescription>
            Default copy applied to every proposal. A specific quote can still
            override its own notes and terms.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          <div className="space-y-2">
            <Label htmlFor="intro">Intro blurb</Label>
            <Textarea
              id="intro"
              rows={3}
              placeholder="Thanks for the opportunity to earn your business…"
              defaultValue={settings.intro ?? ""}
              onBlur={(e) => update({ intro: e.target.value || null })}
              disabled={disabled}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="default-terms">Default terms</Label>
            <Textarea
              id="default-terms"
              rows={4}
              placeholder="50% deposit due on approval; balance on completion…"
              defaultValue={settings.default_terms ?? ""}
              onBlur={(e) => update({ default_terms: e.target.value || null })}
              disabled={disabled}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="footer">Footer</Label>
            <Input
              id="footer"
              placeholder="Licensed & insured — Lic #123456"
              defaultValue={settings.footer ?? ""}
              onBlur={(e) => update({ footer: e.target.value || null })}
              disabled={disabled}
            />
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
