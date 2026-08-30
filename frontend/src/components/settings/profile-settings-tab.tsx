"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Save, Check, Loader2 } from "lucide-react";
import { useTheme } from "next-themes";
import { useState } from "react";

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
import { Switch } from "@/components/ui/switch";
import { useIsMounted } from "@/hooks/useMounted";
import { useSettingsSaveMutation } from "@/hooks/useSettingsSaveMutation";
import { settingsApi } from "@/lib/api/settings";
import { TIMEZONE_OPTIONS } from "@/lib/constants";
import { queryKeys } from "@/lib/query-keys";

export function ProfileSettingsTab() {
  const queryClient = useQueryClient();
  const [profileSaved, setProfileSaved] = useState(false);
  const { resolvedTheme, setTheme } = useTheme();
  // `resolvedTheme` is undefined during SSR, so hold the switch in its
  // server-rendered state until mount to avoid a hydration mismatch.
  const themeMounted = useIsMounted();
  const isDark = themeMounted && resolvedTheme === "dark";

  // Track local edits separate from server state
  const [localEdits, setLocalEdits] = useState<{
    full_name?: string;
    phone_number?: string;
    timezone?: string;
  }>({});

  // Fetch profile
  const { data: profile, isPending: profileLoading } = useQuery({
    queryKey: queryKeys.settings.profile(),
    queryFn: settingsApi.getProfile,
  });

  // Derive form values from profile + local edits
  const profileForm = {
    full_name: localEdits.full_name ?? profile?.full_name ?? "",
    phone_number: localEdits.phone_number ?? profile?.phone_number ?? "",
    timezone: localEdits.timezone ?? profile?.timezone ?? "America/New_York",
  };

  // Profile mutation
  const profileMutation = useSettingsSaveMutation({
    mutationFn: settingsApi.updateProfile,
    successMessage: "Your profile is up to date.",
    errorMessage: "We couldn't save your profile. Check your connection and try again.",
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.settings.profile() });
      setLocalEdits({});
      setProfileSaved(true);
      setTimeout(() => setProfileSaved(false), 2000);
    },
  });

  // The browser blurs a control the moment it becomes `disabled`, so the save
  // button stays enabled while in flight and guards duplicate submits here
  // instead. Keyboard focus then survives both the success and failure render.
  const handleSaveProfile = () => {
    if (profileMutation.isPending || profileLoading) return;
    profileMutation.mutate({
      full_name: profileForm.full_name || null,
      phone_number: profileForm.phone_number || null,
      timezone: profileForm.timezone,
    });
  };

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>Profile Information</CardTitle>
          <CardDescription>Update your personal details and preferences</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {profileLoading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="size-6 animate-spin text-muted-foreground" />
            </div>
          ) : (
            <>
              <div className="space-y-2">
                <Label htmlFor="fullName">Full Name</Label>
                <Input
                  id="fullName"
                  value={profileForm.full_name}
                  onChange={(e) =>
                    setLocalEdits((prev) => ({
                      ...prev,
                      full_name: e.target.value,
                    }))
                  }
                  placeholder="Enter your full name"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="email">Email</Label>
                <Input
                  id="email"
                  type="email"
                  value={profile?.email || ""}
                  disabled
                  className="bg-muted"
                />
                <p className="text-xs text-muted-foreground">Email cannot be changed</p>
              </div>
              <div className="space-y-2">
                <Label htmlFor="phone">Phone Number</Label>
                <Input
                  id="phone"
                  type="tel"
                  value={profileForm.phone_number}
                  onChange={(e) =>
                    setLocalEdits((prev) => ({
                      ...prev,
                      phone_number: e.target.value,
                    }))
                  }
                  placeholder="+1 (555) 123-4567"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="timezone">Timezone</Label>
                <Select
                  value={profileForm.timezone}
                  onValueChange={(value) => setLocalEdits((prev) => ({ ...prev, timezone: value }))}
                >
                  <SelectTrigger id="timezone">
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
            </>
          )}
        </CardContent>
        <CardFooter>
          <Button
            onClick={handleSaveProfile}
            disabled={profileLoading}
            aria-disabled={profileMutation.isPending}
            aria-busy={profileMutation.isPending}
            className="aria-disabled:opacity-50"
          >
            {profileMutation.isPending ? (
              <>
                <Loader2 className="mr-2 size-4 animate-spin" />
                Saving...
              </>
            ) : profileSaved ? (
              <>
                <Check className="mr-2 size-4" />
                Saved
              </>
            ) : (
              <>
                <Save className="mr-2 size-4" />
                Save Changes
              </>
            )}
          </Button>
        </CardFooter>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Appearance</CardTitle>
          <CardDescription>Customize the look and feel of the application</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-center justify-between">
            <div className="space-y-0.5">
              <Label htmlFor="appearance-dark-mode">Dark Mode</Label>
              <p className="text-sm text-muted-foreground">Use dark theme across the application</p>
            </div>
            <Switch
              id="appearance-dark-mode"
              checked={isDark}
              onCheckedChange={(checked) => setTheme(checked ? "dark" : "light")}
            />
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
