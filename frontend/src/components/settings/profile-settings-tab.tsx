"use client";

import { useState } from "react";
import { useTheme } from "next-themes";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Save, Check, Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Separator } from "@/components/ui/separator";
import { settingsApi } from "@/lib/api/settings";
import { queryKeys } from "@/lib/query-keys";
import { TIMEZONE_OPTIONS } from "@/lib/constants";

export function ProfileSettingsTab() {
  const queryClient = useQueryClient();
  const [profileSaved, setProfileSaved] = useState(false);
  const { theme, setTheme } = useTheme();
  const isDark = theme === "dark";

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
  const profileMutation = useMutation({
    mutationFn: settingsApi.updateProfile,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.settings.profile() });
      setLocalEdits({});
      setProfileSaved(true);
      setTimeout(() => setProfileSaved(false), 2000);
    },
  });

  const handleSaveProfile = () => {
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
          <CardDescription>
            Update your personal details and preferences
          </CardDescription>
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
                <p className="text-xs text-muted-foreground">
                  Email cannot be changed
                </p>
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
                  onValueChange={(value) =>
                    setLocalEdits((prev) => ({ ...prev, timezone: value }))
                  }
                >
                  <SelectTrigger>
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
            disabled={profileMutation.isPending || profileLoading}
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
          <CardDescription>
            Customize the look and feel of the application
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-center justify-between">
            <div className="space-y-0.5">
              <Label>Dark Mode</Label>
              <p className="text-sm text-muted-foreground">
                Use dark theme across the application
              </p>
            </div>
            <Switch
                checked={isDark}
                onCheckedChange={(checked) =>
                  setTheme(checked ? "dark" : "light")
                }
              />
          </div>
          <Separator />
          <div className="flex items-center justify-between">
            <div className="space-y-0.5">
              <Label>Compact Mode</Label>
              <p className="text-sm text-muted-foreground">
                Reduce spacing for more content on screen
              </p>
            </div>
            <Switch />
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
