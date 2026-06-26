"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";

import { POLL_60S } from "@/lib/query-options";

export default function LandingLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: POLL_60S.staleTime,
            retry: false,
          },
        },
      })
  );

  return (
    <QueryClientProvider client={queryClient}>
      <div className="min-h-screen bg-[#fafaf9] relative">
        {/* Global decorative blur blobs */}
        <div className="fixed top-20 right-10 w-[500px] h-[500px] bg-yellow-200/40 rounded-full blur-3xl pointer-events-none" />
        <div className="fixed bottom-20 left-10 w-[400px] h-[400px] bg-amber-200/25 rounded-full blur-3xl pointer-events-none" />
        <div className="fixed top-1/2 left-1/3 w-[600px] h-[600px] bg-yellow-100/30 rounded-full blur-3xl pointer-events-none" />

        {/* Global subtle grid pattern overlay */}
        <div
          className="fixed inset-0 pointer-events-none opacity-[0.03]"
          style={{
            backgroundImage: `linear-gradient(to right, var(--brand-ink) 1px, transparent 1px), linear-gradient(to bottom, var(--brand-ink) 1px, transparent 1px)`,
            backgroundSize: '60px 60px',
          }}
        />

        <div className="relative z-10">
          {children}
        </div>
      </div>
    </QueryClientProvider>
  );
}
