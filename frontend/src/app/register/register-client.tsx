"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useSearchParams } from "next/navigation";

import { AuthShell } from "@/components/auth/auth-shell";
import { RegisterForm } from "@/components/auth/register-form";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { PageLoadingState } from "@/components/ui/page-state";
import { invitationsApi } from "@/lib/api/invitations";
import { queryKeys } from "@/lib/query-keys";
import { useAuth } from "@/providers/auth-provider";

export function RegisterClient() {
  const { isLoading } = useAuth();
  const inviteToken = useSearchParams().get("invite");

  // Signing up from an invitation: resolve the invite so the workspace name is
  // visible and the email is pinned to the invited address.
  const { data: invitation, isPending: isInvitationLoading } = useQuery({
    queryKey: queryKeys.invitations.byToken(inviteToken ?? ""),
    queryFn: () => invitationsApi.getByToken(inviteToken!),
    enabled: !!inviteToken,
    retry: false,
  });

  if (isLoading || (inviteToken && isInvitationLoading)) {
    return <PageLoadingState className="min-h-screen" />;
  }

  const invitedEmail = invitation?.is_valid ? invitation.email : undefined;

  return (
    <AuthShell>
      <Card>
        <CardHeader>
          <CardTitle className="text-2xl">
            {invitedEmail ? `Join ${invitation?.workspace_name}` : "Create your account"}
          </CardTitle>
          <CardDescription>
            {invitedEmail
              ? "Set a password to accept your invitation and join the team."
              : "Get started with your workspace"}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <RegisterForm lockedEmail={invitedEmail} />
        </CardContent>
        <CardFooter className="justify-center">
          <p className="text-sm text-muted-foreground">
            Already have an account?{" "}
            <Link
              href={inviteToken ? `/login?redirect=/invite/${inviteToken}` : "/login"}
              className="font-medium text-primary hover:underline"
            >
              Sign in
            </Link>
          </p>
        </CardFooter>
      </Card>
    </AuthShell>
  );
}
