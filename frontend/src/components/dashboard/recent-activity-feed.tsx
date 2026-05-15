import { memo } from "react";
import { Calendar, Megaphone, MessageSquare, Phone } from "lucide-react";

import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Skeleton } from "@/components/ui/skeleton";
import type { RecentActivity } from "@/lib/api/dashboard";

interface RecentActivityFeedProps {
  activities: RecentActivity[];
  isPending: boolean;
}

export const RecentActivityFeed = memo(function RecentActivityFeed({
  activities,
  isPending,
}: RecentActivityFeedProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="gradient-heading">Recent Activity</CardTitle>
        <CardDescription>Latest interactions and updates</CardDescription>
      </CardHeader>
      <CardContent>
        <ScrollArea className="max-h-[400px]">
          <div className="space-y-4 pr-3">
            {isPending ? (
              <>
                {[1, 2, 3, 4, 5].map((i) => (
                  <div key={i} className="flex items-center gap-4 text-sm">
                    <Skeleton className="size-9 rounded-full" />
                    <div className="flex-1">
                      <Skeleton className="h-4 w-48 mb-1" />
                      <Skeleton className="h-3 w-24" />
                    </div>
                    <Skeleton className="size-4" />
                  </div>
                ))}
              </>
            ) : activities.length === 0 ? (
              <div className="text-center py-6 text-muted-foreground">
                No recent activity yet.
              </div>
            ) : (
              activities.map((activity) => (
                <div key={activity.id} className="flex items-center gap-4 text-sm">
                  <Avatar className="size-9">
                    <AvatarFallback className="text-xs">
                      {activity.initials}
                    </AvatarFallback>
                  </Avatar>
                  <div className="flex-1">
                    <p>
                      <span className="font-medium">{activity.contact}</span>{" "}
                      <span className="text-muted-foreground">{activity.action}</span>
                    </p>
                    <p className="text-xs text-muted-foreground">
                      {activity.time}
                      {activity.duration && ` - ${activity.duration}`}
                    </p>
                  </div>
                  {activity.type === "call" && (
                    <Phone className="size-4 text-muted-foreground" />
                  )}
                  {activity.type === "sms" && (
                    <MessageSquare className="size-4 text-muted-foreground" />
                  )}
                  {activity.type === "campaign" && (
                    <Megaphone className="size-4 text-muted-foreground" />
                  )}
                  {activity.type === "booking" && (
                    <Calendar className="size-4 text-muted-foreground" />
                  )}
                </div>
              ))
            )}
          </div>
        </ScrollArea>
      </CardContent>
    </Card>
  );
});
