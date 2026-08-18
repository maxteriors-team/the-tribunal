"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { FormEvent, Suspense, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { confirmPasswordReset } from "@/lib/api/auth";

function ResetPasswordForm() {
  const token = useSearchParams().get("token") ?? "";
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [complete, setComplete] = useState(false);
  const [loading, setLoading] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (password.length < 8) return setError("Password must be at least 8 characters.");
    if (password !== confirmation) return setError("Passwords do not match.");
    if (!token) return setError("This reset link is invalid or incomplete.");
    setLoading(true);
    setError(null);
    try {
      await confirmPasswordReset(token, password);
      setComplete(true);
    } catch {
      setError("This reset link is invalid or expired. Request a new one.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <Card className="w-full max-w-md">
      <CardHeader className="text-center">
        <h1 className="text-2xl font-semibold leading-none">Choose a new password</h1>
        <CardDescription>The link works once and expires after 30 minutes.</CardDescription>
      </CardHeader>
      <CardContent>
        {complete ? (
          <div className="space-y-4 text-center">
            <p className="text-sm">
              Your password has been updated. Sign in on all devices with your new password.
            </p>
            <Button asChild>
              <Link href="/login">Sign in</Link>
            </Button>
          </div>
        ) : (
          <form className="space-y-4" onSubmit={submit}>
            <div className="space-y-2">
              <label className="text-sm font-medium" htmlFor="password">
                New password
              </label>
              <Input
                id="password"
                type="password"
                autoComplete="new-password"
                minLength={8}
                required
                value={password}
                onChange={(event) => setPassword(event.target.value)}
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium" htmlFor="confirmation">
                Confirm new password
              </label>
              <Input
                id="confirmation"
                type="password"
                autoComplete="new-password"
                minLength={8}
                required
                value={confirmation}
                onChange={(event) => setConfirmation(event.target.value)}
              />
            </div>
            {error && (
              <p className="text-destructive text-center text-sm" role="alert">
                {error}
              </p>
            )}
            <Button className="w-full" type="submit" disabled={loading}>
              {loading ? "Updating…" : "Update password"}
            </Button>
            <div className="text-center">
              <Link className="text-sm underline-offset-4 hover:underline" href="/forgot-password">
                Request a new link
              </Link>
            </div>
          </form>
        )}
      </CardContent>
    </Card>
  );
}

export default function ResetPasswordPage() {
  return (
    <main className="flex min-h-screen items-center justify-center px-4">
      <Suspense fallback={<div>Loading…</div>}>
        <ResetPasswordForm />
      </Suspense>
    </main>
  );
}
