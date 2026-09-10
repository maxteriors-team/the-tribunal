"use client";

import { QueryClient, QueryClientProvider, QueryErrorResetBoundary } from "@tanstack/react-query";
import { ThemeProvider } from "next-themes";
import { useState, type ReactNode } from "react";
import { Toaster, toast } from "sonner";

import { PageErrorBoundary } from "@/components/ui/error-boundary";
import { POLL_60S } from "@/lib/query-options";
import { getApiErrorMessage } from "@/lib/utils/errors";

import { AuthProvider } from "./auth-provider";
import { SoftphoneProvider } from "./softphone-provider";
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
            throwOnError: (error, query) => {
              // Only initial-load failures need the route boundary. A failed
              // background refresh must not unmount forms using cached data.
              const status = (error as { status?: number }).status;
              return query.state.data === undefined && typeof status === "number" && status >= 500;
            },
          },
          mutations: {
            // Keep handled submit errors and unsaved input inside their forms.
            throwOnError: false,
            // Features can override this with more specific inline feedback.
            onError: (error) => {
              toast.error(getApiErrorMessage(error, "The request failed. Please try again."));
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
            <SoftphoneProvider>
              <QueryErrorResetBoundary>
                <PageErrorBoundary>{children}</PageErrorBoundary>
              </QueryErrorResetBoundary>
              <Toaster
              position="bottom-right"
              visibleToasts={1}
              toastOptions={{
                classNames: {
                  toast:
                    "!bg-card/90 !backdrop-blur-md !border !border-border !shadow-lg !shadow-black/10 data-[visible=false]:!hidden",
                  title: "!text-foreground !font-semibold",
                  description: "!text-muted-foreground",
                  success: "!border-l-4 !border-l-success",
                  error: "!border-l-4 !border-l-destructive",
                  warning: "!border-l-4 !border-l-warning",
                  info: "!border-l-4 !border-l-primary",
                },
              }}
              />
            </SoftphoneProvider>
          </WorkspaceProvider>
        </AuthProvider>
      </QueryClientProvider>
    </ThemeProvider>
  );
}
