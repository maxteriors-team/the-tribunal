"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { Loader2 } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import {
  Form,
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { register as registerApi } from "@/lib/api/auth";
import { cn } from "@/lib/utils";
import { getApiErrorMessage } from "@/lib/utils/errors";
import { useAuth } from "@/providers/auth-provider";

const registerSchema = z.object({
  full_name: z.string().trim().min(1, { error: "Please enter your name" }),
  // Matches the backend `UserCreate` minimum; anything shorter is rejected at
  // the API with a 422 the user cannot act on.
  email: z.email({ error: "Please enter a valid email address" }),
  password: z.string().min(8, { error: "Password must be at least 8 characters" }),
});

type RegisterFormValues = z.infer<typeof registerSchema>;

interface RegisterFormProps {
  className?: string;
  /**
   * Email the account must use, when signing up from an invitation. The backend
   * matches pending invitations by email, so letting the invitee change it here
   * would silently drop them into a personal workspace instead of the team's.
   */
  lockedEmail?: string;
}

export function RegisterForm({ className, lockedEmail }: RegisterFormProps) {
  const { login } = useAuth();
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const form = useForm<RegisterFormValues>({
    resolver: zodResolver(registerSchema),
    defaultValues: {
      full_name: "",
      email: lockedEmail ?? "",
      password: "",
    },
  });

  async function onSubmit(data: RegisterFormValues) {
    setIsLoading(true);
    setError(null);

    const email = lockedEmail ?? data.email;

    try {
      await registerApi({
        email,
        password: data.password,
        full_name: data.full_name,
      });
      // Registration does not set auth cookies, so sign in immediately. The
      // account is already a member of any workspace that invited this address,
      // so "/" opens the team's workspace rather than a personal one.
      await login({ email, password: data.password }, { redirectTo: "/" });
    } catch (err) {
      setError(getApiErrorMessage(err, "Could not create your account. Please try again."));
      setIsLoading(false);
    }
  }

  return (
    <div className={cn("grid gap-6", className)}>
      <Form {...form}>
        <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
          <FormField
            control={form.control}
            name="full_name"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Full name</FormLabel>
                <FormControl>
                  <Input
                    placeholder="Jane Doe"
                    autoComplete="name"
                    disabled={isLoading}
                    {...field}
                  />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
          <FormField
            control={form.control}
            name="email"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Email</FormLabel>
                <FormControl>
                  <Input
                    type="email"
                    placeholder="name@example.com"
                    autoCapitalize="none"
                    autoComplete="email"
                    autoCorrect="off"
                    disabled={isLoading || !!lockedEmail}
                    readOnly={!!lockedEmail}
                    {...field}
                  />
                </FormControl>
                {lockedEmail && (
                  <FormDescription>
                    Your invitation was sent to this address.
                  </FormDescription>
                )}
                <FormMessage />
              </FormItem>
            )}
          />
          <FormField
            control={form.control}
            name="password"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Password</FormLabel>
                <FormControl>
                  <Input
                    type="password"
                    placeholder="At least 8 characters"
                    autoComplete="new-password"
                    disabled={isLoading}
                    {...field}
                  />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
          {error && (
            <div className="text-destructive text-sm text-center">{error}</div>
          )}
          <Button type="submit" className="w-full" disabled={isLoading}>
            {isLoading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            Create Account
          </Button>
        </form>
      </Form>
    </div>
  );
}
