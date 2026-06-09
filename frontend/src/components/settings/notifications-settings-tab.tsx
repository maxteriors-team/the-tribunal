"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import {
  settingsApi,
  type NotificationSettings,
} from "@/lib/api/settings";
import { queryKeys } from "@/lib/query-keys";
export function NotificationsSettingsTab() {
  const queryClient = useQueryClient();

  // Fetch notifications
  const { data: notifications, isPending: notificationsLoading } = useQuery({
    queryKey: queryKeys.settings.notifications(),
    queryFn: settingsApi.getNotifications,
  });

  // Notifications mutation
  const notificationsMutation = useMutation({
    mutationFn: settingsApi.updateNotifications,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.settings.notifications() });
    },
  });

  const handleNotificationChange = (
    key: keyof NotificationSettings,
    value: boolean
  ) => {
    notificationsMutation.mutate({ [key]: value });
  };

  // Per-type toggles for actionable workspace events (push + email).
  const eventTypeToggles: {
    key: keyof NotificationSettings;
    label: string;
    description: string;
  }[] = [
    {
      key: "notification_push_reviews",
      label: "Reviews",
      description: "New reviews and rating responses",
    },
    {
      key: "notification_push_deal_alerts",
      label: "At-risk deals",
      description: "Deal-coach alerts for deals losing momentum",
    },
    {
      key: "notification_push_missed_call_textback",
      label: "Missed-call text-backs",
      description: "When a missed-call follow-up text is sent",
    },
    {
      key: "notification_push_roleplay",
      label: "Roleplay runs",
      description: "When a practice roleplay finishes and is scored",
    },
    {
      key: "notification_push_automations",
      label: "Automations",
      description: "When an automation triggers for your workspace",
    },
  ];

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>Email Notifications</CardTitle>
          <CardDescription>
            Configure which emails you want to receive
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {notificationsLoading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="size-6 animate-spin text-muted-foreground" />
            </div>
          ) : (
            <div className="flex items-center justify-between">
              <div className="space-y-0.5">
                <Label>Email Notifications</Label>
                <p className="text-sm text-muted-foreground">
                  Receive email notifications for important events
                </p>
              </div>
              <Switch
                checked={notifications?.notification_email ?? true}
                onCheckedChange={(checked) =>
                  handleNotificationChange("notification_email", checked)
                }
                disabled={notificationsMutation.isPending}
              />
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>SMS Notifications</CardTitle>
          <CardDescription>Receive text message alerts</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {notificationsLoading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="size-6 animate-spin text-muted-foreground" />
            </div>
          ) : (
            <div className="flex items-center justify-between">
              <div className="space-y-0.5">
                <Label>SMS Notifications</Label>
                <p className="text-sm text-muted-foreground">
                  Get SMS alerts for critical events
                </p>
              </div>
              <Switch
                checked={notifications?.notification_sms ?? true}
                onCheckedChange={(checked) =>
                  handleNotificationChange("notification_sms", checked)
                }
                disabled={notificationsMutation.isPending}
              />
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Push Notifications</CardTitle>
          <CardDescription>Real-time alerts in your browser</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {notificationsLoading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="size-6 animate-spin text-muted-foreground" />
            </div>
          ) : (
            <div className="flex items-center justify-between">
              <div className="space-y-0.5">
                <Label>Push Notifications</Label>
                <p className="text-sm text-muted-foreground">
                  Receive push notifications in your browser
                </p>
              </div>
              <Switch
                checked={notifications?.notification_push ?? true}
                onCheckedChange={(checked) =>
                  handleNotificationChange("notification_push", checked)
                }
                disabled={notificationsMutation.isPending}
              />
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Event Notifications</CardTitle>
          <CardDescription>
            Choose which actionable events notify you by push and email
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {notificationsLoading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="size-6 animate-spin text-muted-foreground" />
            </div>
          ) : (
            eventTypeToggles.map((toggle) => (
              <div
                key={toggle.key}
                className="flex items-center justify-between"
              >
                <div className="space-y-0.5">
                  <Label>{toggle.label}</Label>
                  <p className="text-sm text-muted-foreground">
                    {toggle.description}
                  </p>
                </div>
                <Switch
                  checked={notifications?.[toggle.key] ?? true}
                  onCheckedChange={(checked) =>
                    handleNotificationChange(toggle.key, checked)
                  }
                  disabled={notificationsMutation.isPending}
                />
              </div>
            ))
          )}
        </CardContent>
      </Card>
    </div>
  );
}
