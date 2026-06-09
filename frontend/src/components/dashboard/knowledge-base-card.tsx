"use client";

import { ArrowUpRight, Boxes, Bot, BookOpen, FileText } from "lucide-react";
import Link from "next/link";
import { memo } from "react";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import type { KnowledgeBaseStats } from "@/lib/api/dashboard";
import { formatNumber } from "@/lib/utils/number";

interface KnowledgeBaseCardProps {
  knowledgeBaseStats: KnowledgeBaseStats | undefined;
  isPending: boolean;
}

export const KnowledgeBaseCard = memo(function KnowledgeBaseCard({
  knowledgeBaseStats,
  isPending,
}: KnowledgeBaseCardProps) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <div>
          <CardTitle className="flex items-center gap-2 gradient-heading">
            <BookOpen className="size-5" />
            Knowledge Base
          </CardTitle>
          <CardDescription>Documents powering agent context</CardDescription>
        </div>
        <Button variant="outline" size="sm" asChild>
          <Link href="/agents">
            Manage
            <ArrowUpRight className="ml-2 size-4" />
          </Link>
        </Button>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          {isPending && !knowledgeBaseStats ? (
            <>
              {[1, 2, 3, 4].map((i) => (
                <div key={i} className="space-y-1 text-center">
                  <Skeleton className="mx-auto h-8 w-12" />
                  <Skeleton className="mx-auto h-3 w-16" />
                  <Skeleton className="mx-auto h-3 w-20" />
                </div>
              ))}
            </>
          ) : (
            <>
              <div className="space-y-1 text-center">
                <div className="flex items-center justify-center gap-1 text-primary">
                  <FileText className="size-4" />
                  <span className="text-2xl font-bold">
                    {knowledgeBaseStats?.active_documents ?? 0}
                  </span>
                </div>
                <p className="text-xs font-medium">Active Docs</p>
                <p className="text-xs text-muted-foreground">
                  of {knowledgeBaseStats?.total_documents ?? 0} total
                </p>
              </div>

              <div className="space-y-1 text-center">
                <div className="flex items-center justify-center gap-1 text-info">
                  <Boxes className="size-4" />
                  <span className="text-2xl font-bold">
                    {formatNumber(knowledgeBaseStats?.total_chunks ?? 0)}
                  </span>
                </div>
                <p className="text-xs font-medium">Chunks</p>
                <p className="text-xs text-muted-foreground">Indexed</p>
              </div>

              <div className="space-y-1 text-center">
                <div className="flex items-center justify-center gap-1 text-foreground">
                  <span className="text-2xl font-bold">
                    {formatNumber(knowledgeBaseStats?.total_tokens ?? 0)}
                  </span>
                </div>
                <p className="text-xs font-medium">Tokens</p>
                <p className="text-xs text-muted-foreground">Available</p>
              </div>

              <div className="space-y-1 text-center">
                <div className="flex items-center justify-center gap-1 text-primary">
                  <Bot className="size-4" />
                  <span className="text-2xl font-bold">
                    {knowledgeBaseStats?.agents_with_knowledge ?? 0}
                  </span>
                </div>
                <p className="text-xs font-medium">Agents</p>
                <p className="text-xs text-muted-foreground">With docs</p>
              </div>
            </>
          )}
        </div>
      </CardContent>
    </Card>
  );
});
