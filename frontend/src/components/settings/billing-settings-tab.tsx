import { CreditCard } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

export function BillingSettingsTab() {
  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>Current Plan</CardTitle>
          <CardDescription>You are currently on the Pro plan</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex items-center justify-between p-4 rounded-lg border bg-primary/5">
            <div>
              <h3 className="text-lg font-semibold">Pro Plan</h3>
              <p className="text-sm text-muted-foreground">
                $99/month, billed monthly
              </p>
            </div>
            <Badge>Current Plan</Badge>
          </div>
          <div className="mt-4 grid grid-cols-3 gap-4 text-center">
            <div className="p-3 rounded-lg border">
              <p className="text-2xl font-bold">5,000</p>
              <p className="text-sm text-muted-foreground">SMS/month</p>
            </div>
            <div className="p-3 rounded-lg border">
              <p className="text-2xl font-bold">500</p>
              <p className="text-sm text-muted-foreground">AI minutes</p>
            </div>
            <div className="p-3 rounded-lg border">
              <p className="text-2xl font-bold">10</p>
              <p className="text-sm text-muted-foreground">Team members</p>
            </div>
          </div>
        </CardContent>
        <CardFooter className="flex gap-2">
          <Button variant="outline">Change Plan</Button>
          <Button variant="outline">View Usage</Button>
        </CardFooter>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Payment Method</CardTitle>
          <CardDescription>Manage your payment information</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex items-center justify-between p-3 rounded-lg border">
            <div className="flex items-center gap-3">
              <CreditCard className="size-8 text-muted-foreground" />
              <div>
                <p className="font-medium">Visa ending in 4242</p>
                <p className="text-sm text-muted-foreground">Expires 12/25</p>
              </div>
            </div>
            <Button variant="outline" size="sm">
              Update
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
