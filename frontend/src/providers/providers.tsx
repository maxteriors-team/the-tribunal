"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ThemeProvider } from "next-themes";
import { useState, type ReactNode } from "react";
import { Toaster } from "sonner";

import { PageErrorBoundary } from "@/components/ui/error-boundary";
import { POLL_60S } from "@/lib/query-options";

import { AuthProvider } from "./auth-provider";
import { WorkspaceProvider } from "./workspace-provider";

interface ProvidersProps {
  children: ReactNode;
}

export function Providers({ children }: ProvidersProps) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: POLL_60S.staleTime,
            refetchOnWindowFocus: false,
            throwOnError: (error) => {
              // Propagate server errors to the nearest error boundary (error.tsx)
              // so unexpected failures surface visibly instead of silently failing.
              const status = (error as { status?: number }).status;
              return typeof status === "number" && status >= 500;
            },
          },
          mutations: {
            throwOnError: (error) => {
              const status = (error as { status?: number }).status;
              return typeof status === "number" && status >= 500;
            },
          },
        },
      })
  );

  return (
    <ThemeProvider attribute="class" defaultTheme="dark" disableTransitionOnChange>
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
          <WorkspaceProvider>
            <PageErrorBoundary>
              {children}
            </PageErrorBoundary>
            <Toaster
              position="bottom-right"
              toastOptions={{
                classNames: {
                  toast: "!bg-card/90 !backdrop-blur-md !border !border-border !shadow-lg !shadow-black/10",
                  title: "!text-foreground !font-semibold",
                  description: "!text-muted-foreground",
                  success: "!border-l-4 !border-l-success",
                  error: "!border-l-4 !border-l-destructive",
                  warning: "!border-l-4 !border-l-warning",
                  info: "!border-l-4 !border-l-primary",
                },
              }}
            />
          </WorkspaceProvider>
        </AuthProvider>
      </QueryClientProvider>
    </ThemeProvider>
  );
}
