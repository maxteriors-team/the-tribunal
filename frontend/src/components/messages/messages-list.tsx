"use client";

import { useInfiniteQuery } from "@tanstack/react-query";
import { Loader2, Mail, MessageSquare, Search } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { MessageThreadDialog } from "@/components/messages/message-thread-dialog";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { PageEmptyState, PageErrorState, PageLoadingState } from "@/components/ui/page-state";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useDebouncedSearch } from "@/hooks/useDebouncedSearch";
import { useFilterState } from "@/hooks/useFilterState";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import { conversationsApi } from "@/lib/api/conversations";
import { queryKeys } from "@/lib/query-keys";
import { formatDate, formatRelative } from "@/lib/utils/date";
import { getInitialsFromName } from "@/lib/utils/initials";
import { formatPhoneNumber } from "@/lib/utils/phone";
import type { Conversation } from "@/types";

const PAGE_SIZE = 50;

/** Operators recognize people, not phone numbers -- fall back only when unnamed. */
function threadLabel(conversation: Conversation): string {
  return (
    conversation.contact_name?.trim() ||
    formatPhoneNumber(conversation.contact_phone) ||
    "Unknown contact"
  );
}

/**
 * Every customer conversation, newest thread first, going back as far as the
 * workspace has history.
 *
 * The header chat menu only ever shows the freshest dozen threads and the
 * contact page needs you to already know whose thread you want, so neither can
 * answer "what did we say to this person two years ago". This is that surface.
 */
export function MessagesList() {
  const workspaceId = useWorkspaceId();
  const search = useDebouncedSearch({ delay: 300 });
  const debouncedSearch = search.debouncedValue;
  const { filters, setFilter } = useFilterState({
    initialFilters: { channel: "all", status: "all" },
  });
  const channelFilter = filters.channel;
  const statusFilter = filters.status;
  const [openThread, setOpenThread] = useState<Conversation | null>(null);
  const sentinelRef = useRef<HTMLDivElement>(null);

  const listParams = useMemo(
    () => ({
      page_size: PAGE_SIZE,
      search: debouncedSearch || undefined,
      channel_filter: channelFilter !== "all" ? channelFilter : undefined,
      status_filter: statusFilter !== "all" ? statusFilter : undefined,
    }),
    [debouncedSearch, channelFilter, statusFilter],
  );

  const { data, isPending, error, fetchNextPage, hasNextPage, isFetchingNextPage } =
    useInfiniteQuery({
      queryKey: queryKeys.conversations.list(workspaceId ?? "", listParams),
      queryFn: ({ pageParam }) => {
        if (!workspaceId) throw new Error("Workspace not loaded");
        return conversationsApi.list(workspaceId, { ...listParams, page: pageParam });
      },
      initialPageParam: 1,
      getNextPageParam: (lastPage) =>
        lastPage.page < lastPage.pages ? lastPage.page + 1 : undefined,
      enabled: !!workspaceId,
    });

  const threads = useMemo(() => data?.pages.flatMap((page) => page.items) ?? [], [data?.pages]);
  const total = data?.pages[0]?.total ?? 0;

  const handleObserver = useCallback(
    (entries: IntersectionObserverEntry[]) => {
      const [entry] = entries;
      if (entry.isIntersecting && hasNextPage && !isFetchingNextPage) {
        fetchNextPage();
      }
    },
    [hasNextPage, isFetchingNextPage, fetchNextPage],
  );

  useEffect(() => {
    const el = sentinelRef.current;
    if (!el) return;
    const observer = new IntersectionObserver(handleObserver, { threshold: 0.1 });
    observer.observe(el);
    return () => observer.disconnect();
  }, [handleObserver]);

  if (isPending) return <PageLoadingState className="h-96" />;

  if (error) {
    return (
      <PageErrorState
        className="h-96"
        message={(error as Error).message || "Failed to load messages"}
      />
    );
  }

  return (
    <div className="space-y-6 p-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Messages</h1>
        <p className="text-muted-foreground">
          Every text and email conversation with your customers, newest first.
        </p>
      </div>

      <Card>
        <CardContent className="pt-6">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-center">
            <div className="relative flex-1">
              <Search
                className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
                aria-hidden="true"
              />
              <Input
                aria-label="Search messages by contact name"
                placeholder="Search by contact name..."
                value={search.value}
                onChange={(event) => search.setValue(event.target.value)}
                className="pl-10"
              />
            </div>
            <div className="flex gap-2">
              <Select value={channelFilter} onValueChange={(value) => setFilter("channel", value)}>
                <SelectTrigger
                  className="w-full sm:w-[140px]"
                  aria-label="Filter messages by channel"
                >
                  <SelectValue placeholder="Channel" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All Channels</SelectItem>
                  <SelectItem value="sms">SMS</SelectItem>
                  <SelectItem value="email">Email</SelectItem>
                </SelectContent>
              </Select>
              <Select value={statusFilter} onValueChange={(value) => setFilter("status", value)}>
                <SelectTrigger
                  className="w-full sm:w-[140px]"
                  aria-label="Filter messages by status"
                >
                  <SelectValue placeholder="Status" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All Status</SelectItem>
                  <SelectItem value="active">Active</SelectItem>
                  <SelectItem value="archived">Archived</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
          {/* Bodies are encrypted at rest, so search can only reach names. Saying
              so beats letting an operator conclude an old thread is gone. */}
          <p className="mt-3 text-xs text-muted-foreground">
            Search matches contact names. Message text itself is encrypted and cannot be searched.
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-0">
          {threads.length === 0 ? (
            <PageEmptyState
              className="py-12"
              icon={<MessageSquare className="size-12" />}
              title={debouncedSearch ? "No matching conversations" : "No conversations yet"}
              description={
                debouncedSearch
                  ? "No contact matches that name. Try a different spelling."
                  : "Texts and emails with customers will appear here."
              }
            />
          ) : (
            <ScrollArea className="h-[calc(100vh-420px)] min-h-[300px]">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Contact</TableHead>
                    <TableHead>Channel</TableHead>
                    <TableHead>Last message</TableHead>
                    <TableHead>When</TableHead>
                    <TableHead className="w-[100px]">Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  <AnimatePresence mode="popLayout">
                    {threads.map((thread) => {
                      const label = threadLabel(thread);
                      const ChannelIcon = thread.channel === "email" ? Mail : MessageSquare;
                      return (
                        <motion.tr
                          key={thread.id}
                          layout
                          initial={{ opacity: 0 }}
                          animate={{ opacity: 1 }}
                          exit={{ opacity: 0 }}
                          className="group"
                        >
                          <TableCell>
                            <div className="flex items-center gap-3">
                              {/* Initials only: the thread payload carries no
                                  avatar URL, and fetching one per row would be a
                                  request per conversation. */}
                              <Avatar className="size-8">
                                <AvatarFallback className="text-xs">
                                  {getInitialsFromName(label)}
                                </AvatarFallback>
                              </Avatar>
                              <div>
                                <div className="text-sm font-medium">{label}</div>
                                {thread.contact_name && thread.contact_phone ? (
                                  <div className="font-mono text-xs text-muted-foreground">
                                    {formatPhoneNumber(thread.contact_phone)}
                                  </div>
                                ) : null}
                              </div>
                            </div>
                          </TableCell>
                          <TableCell>
                            <div className="flex items-center gap-2">
                              <ChannelIcon
                                className="size-4 text-muted-foreground"
                                aria-hidden="true"
                              />
                              <span className="uppercase">{thread.channel}</span>
                            </div>
                          </TableCell>
                          <TableCell className="max-w-[320px]">
                            <div className="flex items-center gap-2">
                              <span className="truncate text-sm text-muted-foreground">
                                {thread.last_message_preview ?? "No messages yet"}
                              </span>
                              {thread.unread_count > 0 ? (
                                <Badge variant="default" className="h-4 shrink-0 px-1.5 text-[10px]">
                                  {thread.unread_count}
                                </Badge>
                              ) : null}
                            </div>
                          </TableCell>
                          <TableCell>
                            {thread.last_message_at ? (
                              <>
                                <div className="text-sm">
                                  {formatRelative(thread.last_message_at)}
                                </div>
                                <div className="text-xs text-muted-foreground">
                                  {formatDate(thread.last_message_at, {
                                    pattern: "MMM d, yyyy",
                                  })}
                                </div>
                              </>
                            ) : (
                              <span className="text-sm text-muted-foreground">-</span>
                            )}
                          </TableCell>
                          <TableCell>
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => setOpenThread(thread)}
                              aria-label={`View conversation with ${label}`}
                            >
                              View
                            </Button>
                          </TableCell>
                        </motion.tr>
                      );
                    })}
                  </AnimatePresence>
                </TableBody>
              </Table>
              <div ref={sentinelRef} className="h-1" />
              {isFetchingNextPage ? (
                <div className="flex items-center justify-center py-4">
                  <Loader2
                    className="size-5 animate-spin text-muted-foreground"
                    aria-hidden="true"
                  />
                  <span className="ml-2 text-sm text-muted-foreground">
                    Loading older conversations...
                  </span>
                </div>
              ) : null}
            </ScrollArea>
          )}
        </CardContent>
      </Card>

      <div className="text-center text-sm text-muted-foreground">
        Showing {threads.length} of {total} conversations
        {hasNextPage ? " - scroll down for more" : ""}
      </div>

      <Dialog open={openThread !== null} onOpenChange={(open) => !open && setOpenThread(null)}>
        <DialogContent className="max-w-2xl">
          {openThread ? (
            <>
              <DialogHeader>
                <DialogTitle>{threadLabel(openThread)}</DialogTitle>
                <DialogDescription>
                  {openThread.channel === "email" ? "Email" : "Text"} conversation
                  {openThread.last_message_at
                    ? `, last active ${formatDate(openThread.last_message_at, {
                        pattern: "MMMM d, yyyy",
                      })}`
                    : ""}
                </DialogDescription>
              </DialogHeader>
              <MessageThreadDialog
                workspaceId={workspaceId ?? ""}
                conversation={openThread}
                contactName={threadLabel(openThread)}
              />
            </>
          ) : null}
        </DialogContent>
      </Dialog>
    </div>
  );
}
