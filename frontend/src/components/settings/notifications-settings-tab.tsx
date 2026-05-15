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
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
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
    </div>
  );
}
