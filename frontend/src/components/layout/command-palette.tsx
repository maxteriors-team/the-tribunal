"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Command } from "cmdk";
import { Loader2, Megaphone, Search, User } from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useMemo, useState } from "react";

import { Dialog, DialogContent } from "@/components/ui/dialog";
import { useCapabilities } from "@/hooks/useCapabilities";
import { useDebounce } from "@/hooks/useDebounce";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import { campaignsApi } from "@/lib/api/campaigns";
import { contactsApi } from "@/lib/api/contacts";
import { queryKeys } from "@/lib/query-keys";

import { appNavSections, canSeeNavItem, isNavItemVisible, type AppNavItem } from "./app-nav";

interface CommandPaletteProps {
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
}

const SEARCH_LIMIT = 5;

function contactDisplayName(contact: { first_name: string; last_name?: string }): string {
  return [contact.first_name, contact.last_name].filter(Boolean).join(" ").trim();
}

export function CommandPalette({
  open: controlledOpen,
  onOpenChange,
}: CommandPaletteProps = {}) {
  const [internalOpen, setInternalOpen] = useState(false);
  const [query, setQuery] = useState("");
  const router = useRouter();
  const workspaceId = useWorkspaceId();

  const isControlled = controlledOpen !== undefined;
  const open = isControlled ? controlledOpen : internalOpen;

  const setOpen = useCallback(
    (value: boolean) => {
      // Reset the query when closing so the palette reopens clean.
      if (!value) setQuery("");
      if (!isControlled) setInternalOpen(value);
      onOpenChange?.(value);
    },
    [isControlled, onOpenChange]
  );

  // Live input drives the UI (nav hides as soon as the user types); the
  // debounced value drives the API calls so we don't fire a request per
  // keystroke.
  const hasQuery = query.trim().length > 0;
  const searchTerm = useDebounce(query, 250).trim();
  const searchEnabled = open && searchTerm.length > 0 && !!workspaceId;
  const isDebouncing = hasQuery && query.trim() !== searchTerm;

  const contactsQuery = useQuery({
    queryKey: queryKeys.contacts.list(workspaceId ?? "", {
      search: searchTerm,
      page_size: SEARCH_LIMIT,
    }),
    queryFn: () =>
      contactsApi.list(workspaceId!, { search: searchTerm, page_size: SEARCH_LIMIT }),
    enabled: searchEnabled,
    placeholderData: keepPreviousData,
  });

  const campaignsQuery = useQuery({
    queryKey: queryKeys.campaigns.list(workspaceId ?? "", {
      search: searchTerm,
      page_size: SEARCH_LIMIT,
    }),
    queryFn: () =>
      campaignsApi.list(workspaceId!, { search: searchTerm, page_size: SEARCH_LIMIT }),
    enabled: searchEnabled,
    placeholderData: keepPreviousData,
  });

  const { tier, can } = useCapabilities();
  const commandGroups = useMemo(
    () =>
      appNavSections
        .filter((section) => !section.devOnly || process.env.NODE_ENV !== "production")
        .map((section) => ({
          title: section.title,
          items: section.items.filter(
            (item) =>
              item.commandPalette &&
              isNavItemVisible(item) &&
              canSeeNavItem(item, tier, can)
          ),
        }))
        .filter((section) => section.items.length > 0),
    [tier, can]
  );

  // The palette disables cmdk's built-in filter (shouldFilter={false}) and only
  // renders the nav groups while the input is empty, so typed text never matched
  // pages. Match nav items against the live query ourselves and surface the hits
  // as a "Pages" group. Live query (not the debounced term) keeps it instant.
  const pageMatches = useMemo(() => {
    if (!hasQuery) return [];
    const term = query.trim().toLowerCase();
    return commandGroups
      .flatMap((group) => group.items)
      .map((item) => {
        const titleIndex = item.title.toLowerCase().indexOf(term);
        let score = 0;
        if (titleIndex === 0) score = 3;
        else if (titleIndex > 0) score = 2;
        else if (item.url.toLowerCase().includes(term)) score = 1;
        return { item, score };
      })
      .filter((match) => match.score > 0)
      .sort((a, b) => b.score - a.score)
      .map((match) => match.item);
  }, [hasQuery, query, commandGroups]);

  const contacts = contactsQuery.data?.items ?? [];
  const campaigns = campaignsQuery.data?.items ?? [];
  const isSearching =
    isDebouncing ||
    (searchEnabled && (contactsQuery.isFetching || campaignsQuery.isFetching));

  const handleSelect = (href: string) => {
    router.push(href);
    setOpen(false);
  };

  const renderNavItem = (item: AppNavItem) => {
    const Icon = item.icon;

    return (
      <Command.Item
        key={item.url}
        value={`nav-${item.url}`}
        onSelect={() => handleSelect(item.url)}
        className="flex cursor-pointer items-center gap-3 rounded-md px-2 py-2 text-sm transition-colors hover:bg-accent aria-selected:bg-accent"
      >
        <div className="flex size-7 items-center justify-center rounded-md bg-primary/10">
          <Icon className="size-4 text-primary" />
        </div>
        {item.title}
      </Command.Item>
    );
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent className="max-w-lg overflow-hidden border-primary/20 bg-card/95 p-0 shadow-2xl backdrop-blur-xl">
        <Command
          shouldFilter={false}
          className="[&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:font-medium [&_[cmdk-group-heading]]:text-muted-foreground [&_[cmdk-group]:not([hidden])_~[cmdk-group]]:pt-0 [&_[cmdk-group]]:px-2 [&_[cmdk-input-wrapper]_svg]:size-5 [&_[cmdk-input]]:h-12 [&_[cmdk-item]]:px-2 [&_[cmdk-item]]:py-3 [&_[cmdk-item]_svg]:size-5"
        >
          <div className="flex items-center border-b border-border px-3">
            <Search className="mr-2 size-4 shrink-0 text-muted-foreground" />
            <Command.Input
              value={query}
              onValueChange={setQuery}
              placeholder="Search pages, contacts, campaigns..."
              className="flex h-12 w-full bg-transparent text-sm outline-none placeholder:text-muted-foreground disabled:cursor-not-allowed disabled:opacity-50"
            />
            {isSearching && (
              <Loader2 className="ml-2 size-4 shrink-0 animate-spin text-muted-foreground" />
            )}
          </div>
          <Command.List className="app-scrollbar max-h-80 overflow-y-auto overflow-x-hidden p-2">
            {!isSearching && (
              <Command.Empty className="py-6 text-center text-sm text-muted-foreground">
                No results found.
              </Command.Empty>
            )}

            {!hasQuery &&
              commandGroups.map((group) => (
                <Command.Group key={group.title} heading={group.title}>
                  {group.items.map((item) => renderNavItem(item))}
                </Command.Group>
              ))}

            {hasQuery && pageMatches.length > 0 && (
              <Command.Group heading="Pages">
                {pageMatches.map((item) => renderNavItem(item))}
              </Command.Group>
            )}

            {hasQuery && contacts.length > 0 && (
              <Command.Group heading="Contacts">
                {contacts.map((contact) => {
                  const name = contactDisplayName(contact);
                  const subtitle = contact.email || contact.phone_number || contact.company_name;

                  return (
                    <Command.Item
                      key={`contact-${contact.id}`}
                      value={`contact-${contact.id}`}
                      onSelect={() => handleSelect(`/contacts/${contact.id}`)}
                      className="flex cursor-pointer items-center gap-3 rounded-md px-2 py-2 text-sm transition-colors hover:bg-accent aria-selected:bg-accent"
                    >
                      <div className="flex size-7 items-center justify-center rounded-md bg-primary/10">
                        <User className="size-4 text-primary" />
                      </div>
                      <div className="flex min-w-0 flex-col">
                        <span className="truncate">{name || "Unnamed contact"}</span>
                        {subtitle && (
                          <span className="truncate text-xs text-muted-foreground">
                            {subtitle}
                          </span>
                        )}
                      </div>
                    </Command.Item>
                  );
                })}
              </Command.Group>
            )}

            {hasQuery && campaigns.length > 0 && (
              <Command.Group heading="Campaigns">
                {campaigns.map((campaign) => (
                  <Command.Item
                    key={`campaign-${campaign.id}`}
                    value={`campaign-${campaign.id}`}
                    onSelect={() => handleSelect(`/campaigns/${campaign.id}`)}
                    className="flex cursor-pointer items-center gap-3 rounded-md px-2 py-2 text-sm transition-colors hover:bg-accent aria-selected:bg-accent"
                  >
                    <div className="flex size-7 items-center justify-center rounded-md bg-primary/10">
                      <Megaphone className="size-4 text-primary" />
                    </div>
                    <div className="flex min-w-0 flex-col">
                      <span className="truncate">{campaign.name}</span>
                      <span className="truncate text-xs capitalize text-muted-foreground">
                        {campaign.status}
                      </span>
                    </div>
                  </Command.Item>
                ))}
              </Command.Group>
            )}
          </Command.List>
          <div className="flex items-center gap-2 border-t border-border px-3 py-2 text-xs text-muted-foreground">
            <kbd className="rounded border border-border bg-muted px-1.5 py-0.5 font-mono text-[10px]">
              ↑↓
            </kbd>
            <span>navigate</span>
            <kbd className="rounded border border-border bg-muted px-1.5 py-0.5 font-mono text-[10px]">
              ↵
            </kbd>
            <span>select</span>
            <kbd className="rounded border border-border bg-muted px-1.5 py-0.5 font-mono text-[10px]">
              esc
            </kbd>
            <span>close</span>
            <div className="ml-auto flex items-center gap-1">
              <kbd className="rounded border border-border bg-muted px-1.5 py-0.5 font-mono text-[10px]">
                ⌘K
              </kbd>
            </div>
          </div>
        </Command>
      </DialogContent>
    </Dialog>
  );
}
