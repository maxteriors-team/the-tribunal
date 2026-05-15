"use client";

import * as React from "react";
import { use } from "react";
import { useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Loader2, XCircle, Clock, Users } from "lucide-react";

import { PageLoadingState } from "@/components/ui/page-state";
import { invitationsApi } from "@/lib/api/invitations";
import { queryKeys } from "@/lib/query-keys";
import { useAuth } from "@/providers/auth-provider";
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

interface PageProps {
  params: Promise<{ token: string }>;
}

export default function InviteAcceptPage({ params }: PageProps) {
  const { token } = use(params);
  const router = useRouter();
  const queryClient = useQueryClient();
  const { user, isLoading: isAuthLoading, isAuthenticated } = useAuth();

  // Fetch invitation details
  const {
    data: invitation,
    isPending: isInvitationLoading,
    error,
  } = useQuery({
    queryKey: queryKeys.invitations.byToken(token),
    queryFn: () => invitationsApi.getByToken(token),
    retry: false,
  });

  // Accept invitation mutation
  const acceptMutation = useMutation({
    mutationFn: () => invitationsApi.accept(token),
    onSuccess: (data) => {
      toast.success(data.message || "Invitation accepted!");
      queryClient.invalidateQueries({ queryKey: queryKeys.workspaces.all() });
      queryClient.invalidateQueries({ queryKey: queryKeys.auth.user() });
      // Redirect to the workspace
      if (data.workspace_slug) {
        router.push(`/?workspace=${data.workspace_slug}`);
      } else {
        router.push("/");
      }
    },
    onError: (err: Error) => {
      toast.error(err.message || "Failed to accept invitation");
    },
  });

  const handleAccept = () => {
    acceptMutation.mutate();
  };

  const handleLogin = () => {
    // Redirect to login with return URL
    router.push(`/login?redirect=/invite/${token}`);
  };

  // Loading state
  if (isAuthLoading || isInvitationLoading) {
    return <PageLoadingState className="min-h-screen" />;
  }

  // Error state
  if (error || !invitation) {
    return (
      <div className="flex min-h-screen items-center justify-center px-4">
        <Card className="w-full max-w-md">
          <CardHeader className="text-center">
            <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-destructive/10">
              <XCircle className="h-6 w-6 text-destructive" />
            </div>
            <CardTitle>Invalid Invitation</CardTitle>
            <CardDescription>
              This invitation link is invalid or has already been used.
            </CardDescription>
          </CardHeader>
          <CardFooter className="justify-center">
            <Button variant="outline" onClick={() => router.push("/")}>
              Go to Dashboard
            </Button>
          </CardFooter>
        </Card>
      </div>
    );
  }

  // Expired invitation
  if (invitation.is_expired || !invitation.is_valid) {
    return (
      <div className="flex min-h-screen items-center justify-center px-4">
        <Card className="w-full max-w-md">
          <CardHeader className="text-center">
            <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-warning/10">
              <Clock className="h-6 w-6 text-warning" />
            </div>
            <CardTitle>Invitation Expired</CardTitle>
            <CardDescription>
              This invitation has expired. Please contact the workspace
              administrator to request a new invitation.
            </CardDescription>
          </CardHeader>
          <CardFooter className="justify-center">
            <Button variant="outline" onClick={() => router.push("/")}>
              Go to Dashboard
            </Button>
          </CardFooter>
        </Card>
      </div>
    );
  }

  // Valid invitation - show details
  return (
    <div className="flex min-h-screen items-center justify-center px-4">
      <Card className="w-full max-w-md">
        <CardHeader className="text-center">
          <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-primary/10">
            <Users className="h-6 w-6 text-primary" />
          </div>
          <CardTitle>You&apos;re Invited!</CardTitle>
          <CardDescription>
            {invitation.invited_by_name
              ? `${invitation.invited_by_name} has invited you to join`
              : "You've been invited to join"}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="rounded-lg border bg-muted/50 p-4 text-center">
            <h3 className="text-lg font-semibold">{invitation.workspace_name}</h3>
            <div className="mt-2 flex items-center justify-center gap-2">
              <Badge variant="secondary" className="capitalize">
                {invitation.role}
              </Badge>
            </div>
          </div>

          <div className="text-center text-sm text-muted-foreground">
            <p>
              You&apos;ll join as{" "}
              {invitation.role === "admin" ? "an administrator" : "a team member"}.
            </p>
          </div>

          {!isAuthenticated && (
            <div className="rounded-lg border border-warning/20 bg-warning/10 p-3 text-center text-sm">
              <p className="text-warning">
                You need to sign in to accept this invitation.
              </p>
            </div>
          )}

          {isAuthenticated && user?.email !== invitation.email && (
            <div className="rounded-lg border border-warning/20 bg-warning/10 p-3 text-center text-sm">
              <p className="text-warning">
                This invitation was sent to {invitation.email}. You&apos;re
                currently signed in as {user?.email}.
              </p>
            </div>
          )}
        </CardContent>
        <CardFooter className="flex flex-col gap-2">
          {isAuthenticated ? (
            <Button
              className="w-full"
              onClick={handleAccept}
              disabled={acceptMutation.isPending}
            >
              {acceptMutation.isPending && (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              )}
              {acceptMutation.isPending ? "Accepting..." : "Accept Invitation"}
            </Button>
          ) : (
            <Button className="w-full" onClick={handleLogin}>
              Sign in to Accept
            </Button>
          )}
          <Button
            variant="ghost"
            className="w-full"
            onClick={() => router.push("/")}
          >
            {isAuthenticated ? "Maybe Later" : "Go Back"}
          </Button>
        </CardFooter>
      </Card>
    </div>
  );
}
