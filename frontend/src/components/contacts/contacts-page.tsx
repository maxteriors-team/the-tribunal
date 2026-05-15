"use client";

import * as React from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { AnimatePresence } from "motion/react";
import { toast } from "sonner";
import { Users, CheckSquare, X, Plus, Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Badge } from "@/components/ui/badge";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { useContactStore } from "@/lib/contact-store";
import { CreateContactDialog } from "@/components/contacts/create-contact-dialog";
import { ImportContactsDialog } from "@/components/contacts/import-contacts-dialog";
import { ScrapeLeadsDialog } from "@/components/contacts/scrape-leads-dialog";
import { BulkTagDialog } from "@/components/contacts/bulk-tag-dialog";
import { ResourceListPagination } from "@/components/resource-list/resource-list-pagination";
import { ContactCard, ContactCardSkeleton } from "@/components/contacts/contact-card";
import { ContactsToolbar } from "@/components/contacts/contacts-toolbar";
import { ContactsBulkActions } from "@/components/contacts/contacts-bulk-actions";
import { ContactsEmptyState } from "@/components/contacts/contacts-empty-state";
import { useQueryClient } from "@tanstack/react-query";
import { useBulkDeleteContacts, useBulkUpdateStatus, useContactIds, useContactsPaginated } from "@/hooks/useContacts";
import { useWorkspaceId } from "@/hooks/use-workspace-id";
import { queryKeys } from "@/lib/query-keys";
import type { Contact, ContactStatus } from "@/types";
import type { ContactIdsParams, ContactsListParams } from "@/lib/api/contacts";

export function ContactsPage() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const [isCreateDialogOpen, setIsCreateDialogOpen] = React.useState(false);
  const [isImportDialogOpen, setIsImportDialogOpen] = React.useState(false);
  const [isScrapeDialogOpen, setIsScrapeDialogOpen] = React.useState(false);

  // Auto-open import dialog when navigated here with ?import=true
  React.useEffect(() => {
    if (searchParams.get("import") === "true") {
      setIsImportDialogOpen(true);
      const urlParams = new URLSearchParams(searchParams.toString());
      urlParams.delete("import");
      const newUrl = urlParams.size > 0 ? `/?${urlParams.toString()}` : "/";
      router.replace(newUrl, { scroll: false });
    }
  }, [searchParams, router]);

  const [isSelectionMode, setIsSelectionMode] = React.useState(false);
  const [selectedIds, setSelectedIds] = React.useState<Set<number>>(new Set());
  const [selectAllMatchingIds, setSelectAllMatchingIds] = React.useState<Set<number> | null>(null);
  const [isDeleteDialogOpen, setIsDeleteDialogOpen] = React.useState(false);
  const [isBulkTagDialogOpen, setIsBulkTagDialogOpen] = React.useState(false);
  const [lastClickedIndex, setLastClickedIndex] = React.useState<number | null>(null);

  // Debounced search input: local state updates immediately, store updates after delay
  const [inputValue, setInputValue] = React.useState("");

  const workspaceId = useWorkspaceId();
  const queryClient = useQueryClient();
  const bulkDeleteMutation = useBulkDeleteContacts(workspaceId ?? "");
  const bulkUpdateStatusMutation = useBulkUpdateStatus(workspaceId ?? "");

  const {
    searchQuery,
    setSearchQuery,
    statusFilter,
    setStatusFilter,
    sortBy,
    setSortBy,
    filters,
    setFilters,
    contactsPage,
    contactsPageSize,
    setContactsPage,
  } = useContactStore();

  // Build query params from store filter/sort/pagination state
  const contactsListParams = React.useMemo<ContactsListParams>(() => ({
    page: contactsPage,
    page_size: contactsPageSize,
    sort_by: sortBy,
    ...(searchQuery.trim() && { search: searchQuery.trim() }),
    ...(statusFilter && { status: statusFilter as ContactStatus }),
    ...(filters && { filters: JSON.stringify(filters) }),
  }), [contactsPage, contactsPageSize, sortBy, searchQuery, statusFilter, filters]);

  // Fetch contacts via React Query
  const { data: contactsData, isPending: isLoadingContacts } = useContactsPaginated(
    workspaceId ?? "",
    contactsListParams,
  );
  const contacts = React.useMemo(() => contactsData?.items ?? [], [contactsData?.items]);
  const contactsTotal = contactsData?.total ?? 0;
  const contactsTotalPages = contactsData?.pages ?? 1;

  // Sync local input value on mount
  React.useEffect(() => {
    setInputValue(searchQuery);
  // Only run on mount to avoid fighting the debounce
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Debounce search: update store query 400ms after user stops typing
  React.useEffect(() => {
    const timer = setTimeout(() => {
      setSearchQuery(inputValue);
    }, 400);
    return () => clearTimeout(timer);
  }, [inputValue, setSearchQuery]);

  // Build params for the /ids endpoint (for "select all matching")
  const idsParams = React.useMemo<ContactIdsParams>(() => {
    const params: ContactIdsParams = {};
    if (searchQuery.trim()) params.search = searchQuery.trim();
    if (statusFilter) params.status = statusFilter as ContactStatus;
    if (filters) params.filters = JSON.stringify(filters);
    return params;
  }, [searchQuery, statusFilter, filters]);

  // Effective selected IDs: either the explicit set or the "select all matching" set
  const effectiveSelectedIds = selectAllMatchingIds ?? selectedIds;
  const selectedCount = effectiveSelectedIds.size;
  const selectedArray = React.useMemo(() => Array.from(effectiveSelectedIds), [effectiveSelectedIds]);

  // Status counts from current page contacts (all count uses server total)
  const statusCounts = React.useMemo<Record<ContactStatus | "all", number>>(() => {
    const counts: Record<ContactStatus | "all", number> = {
      all: contactsTotal,
      new: 0,
      contacted: 0,
      qualified: 0,
      converted: 0,
      lost: 0,
    };
    contacts.forEach((contact: Contact) => {
      counts[contact.status]++;
    });
    return counts;
  }, [contacts, contactsTotal]);

  const handleToggleSelectionMode = () => {
    if (isSelectionMode) {
      setSelectedIds(new Set());
      setSelectAllMatchingIds(null);
      setLastClickedIndex(null);
    }
    setIsSelectionMode(!isSelectionMode);
  };

  const handleSelectContact = (contactId: number, checked: boolean, shiftKey: boolean) => {
    if (selectAllMatchingIds) {
      setSelectAllMatchingIds(null);
      const next = new Set(selectAllMatchingIds);
      if (checked) next.add(contactId);
      else next.delete(contactId);
      setSelectedIds(next);

      const idx = contacts.findIndex((c: Contact) => c.id === contactId);
      if (idx !== -1) setLastClickedIndex(idx);
      return;
    }

    // Shift+click range selection
    if (shiftKey && lastClickedIndex !== null) {
      const currentIndex = contacts.findIndex((c: Contact) => c.id === contactId);
      if (currentIndex !== -1) {
        const start = Math.min(lastClickedIndex, currentIndex);
        const end = Math.max(lastClickedIndex, currentIndex);
        setSelectedIds((prev) => {
          const next = new Set(prev);
          for (let i = start; i <= end; i++) {
            next.add(contacts[i].id);
          }
          return next;
        });
        setLastClickedIndex(currentIndex);
        return;
      }
    }

    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (checked) next.add(contactId);
      else next.delete(contactId);
      return next;
    });

    const idx = contacts.findIndex((c: Contact) => c.id === contactId);
    if (idx !== -1) setLastClickedIndex(idx);
  };

  const handleSelectAllVisible = () => {
    setSelectAllMatchingIds(null);
    const allVisibleIds = new Set(contacts.map((c: Contact) => c.id));
    if (contacts.every((c: Contact) => selectedIds.has(c.id))) {
      setSelectedIds((prev) => {
        const next = new Set(prev);
        allVisibleIds.forEach((id) => next.delete(id));
        return next;
      });
    } else {
      setSelectedIds((prev) => new Set([...prev, ...allVisibleIds]));
    }
  };

  const [fetchAllIds, setFetchAllIds] = React.useState(false);
  const { data: allIdsData, isFetching: isFetchingAllIds } = useContactIds(
    workspaceId ?? "",
    idsParams,
    fetchAllIds,
  );

  const handleSelectAllMatching = () => {
    if (allIdsData) {
      setSelectAllMatchingIds(new Set(allIdsData.ids));
      setSelectedIds(new Set());
      setFetchAllIds(false);
    } else {
      setFetchAllIds(true);
    }
  };

  React.useEffect(() => {
    if (fetchAllIds && allIdsData) {
      setSelectAllMatchingIds(new Set(allIdsData.ids));
      setSelectedIds(new Set());
      setFetchAllIds(false);
    }
  }, [fetchAllIds, allIdsData]);

  const handleClearSelection = () => {
    setSelectedIds(new Set());
    setSelectAllMatchingIds(null);
    setLastClickedIndex(null);
  };

  const handleBulkDelete = async () => {
    if (!workspaceId || selectedCount === 0) return;
    try {
      const result = await bulkDeleteMutation.mutateAsync(selectedArray);
      handleClearSelection();
      setIsDeleteDialogOpen(false);
      toast.success(`Deleted ${result.deleted} contact${result.deleted !== 1 ? "s" : ""}`);
    } catch {
      toast.error("Failed to delete contacts");
    }
  };

  const handleBulkStatusChange = async (status: ContactStatus) => {
    if (!workspaceId || selectedCount === 0) return;
    try {
      const result = await bulkUpdateStatusMutation.mutateAsync({ ids: selectedArray, status });
      void queryClient.invalidateQueries({ queryKey: queryKeys.contacts.bare(workspaceId ?? "") });
      toast.success(`Updated ${result.updated} contact${result.updated !== 1 ? "s" : ""} to ${status}`);
    } catch {
      toast.error("Failed to update status");
    }
  };

  const allVisibleSelected = contacts.length > 0 && contacts.every((c: Contact) => effectiveSelectedIds.has(c.id));
  const someVisibleSelected = contacts.some((c: Contact) => effectiveSelectedIds.has(c.id));
  const hasActiveFilters = !!(searchQuery.trim() || statusFilter || filters);
  const showSelectAllMatching = allVisibleSelected && !selectAllMatchingIds && contactsTotal > contacts.length;

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Header */}
      <div className="shrink-0 p-6 border-b space-y-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Users className="h-6 w-6 text-primary" />
            <h1 className="text-2xl font-bold">Contacts</h1>
            <Badge variant="secondary" className="text-sm">
              {contactsTotal}
            </Badge>
          </div>
          <div className="flex items-center gap-2">
            {!isSelectionMode && (
              <>
                <Button variant="outline" className="gap-2" onClick={() => setIsImportDialogOpen(true)}>
                  <Upload className="h-4 w-4" />
                  Import CSV
                </Button>
                <Button className="gap-2" onClick={() => setIsCreateDialogOpen(true)}>
                  <Plus className="h-4 w-4" />
                  Add Contact
                </Button>
              </>
            )}
            {contacts.length > 0 && (
              <Button
                variant={isSelectionMode ? "default" : "outline"}
                className="gap-2"
                onClick={handleToggleSelectionMode}
              >
                {isSelectionMode ? <X className="h-4 w-4" /> : <CheckSquare className="h-4 w-4" />}
                {isSelectionMode ? "Done" : "Select"}
              </Button>
            )}
          </div>
        </div>

        {/* Bulk Actions Bar */}
        {isSelectionMode && (
          <ContactsBulkActions
            selectedCount={selectedCount}
            selectAllMatchingIds={selectAllMatchingIds}
            allVisibleSelected={allVisibleSelected}
            someVisibleSelected={someVisibleSelected}
            showSelectAllMatching={showSelectAllMatching}
            hasActiveFilters={hasActiveFilters}
            contactsTotal={contactsTotal}
            visibleCount={contacts.length}
            isFetchingAllIds={isFetchingAllIds}
            isBulkUpdatePending={bulkUpdateStatusMutation.isPending}
            isBulkDeletePending={bulkDeleteMutation.isPending}
            onSelectAllVisible={handleSelectAllVisible}
            onClearSelection={handleClearSelection}
            onSelectAllMatching={handleSelectAllMatching}
            onBulkStatusChange={handleBulkStatusChange}
            onOpenTagDialog={() => setIsBulkTagDialogOpen(true)}
            onOpenDeleteDialog={() => setIsDeleteDialogOpen(true)}
          />
        )}

        <ContactsToolbar
          inputValue={inputValue}
          onInputChange={setInputValue}
          sortBy={sortBy}
          onSortByChange={setSortBy}
          workspaceId={workspaceId}
          filters={filters}
          onFiltersChange={setFilters}
          statusFilter={statusFilter}
          onStatusChange={setStatusFilter as (status: ContactStatus | null) => void}
          statusCounts={statusCounts}
        />
      </div>

      {/* Contacts Grid */}
      <ScrollArea className="flex-1 min-h-0">
        <div className="p-6">
          {isLoadingContacts ? (
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
              {Array.from({ length: 8 }).map((_, i) => (
                <ContactCardSkeleton key={i} />
              ))}
            </div>
          ) : contacts.length === 0 ? (
            <ContactsEmptyState
              hasFilters={hasActiveFilters}
              onAddContact={() => setIsCreateDialogOpen(true)}
            />
          ) : (
            <AnimatePresence mode="popLayout">
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                {contacts.map((contact: Contact) => (
                  <ContactCard
                    key={contact.id}
                    contact={contact}
                    isSelected={effectiveSelectedIds.has(contact.id)}
                    onSelectChange={(checked, shiftKey) => handleSelectContact(contact.id, checked, shiftKey)}
                    isSelectionMode={isSelectionMode}
                  />
                ))}
              </div>
            </AnimatePresence>
          )}

          {contactsTotalPages > 1 && (
            <div className="mt-6">
              <ResourceListPagination
                filteredCount={contacts.length}
                totalCount={contactsTotal}
                resourceName="contacts"
                page={contactsPage}
                totalPages={contactsTotalPages}
                onPageChange={setContactsPage}
              />
            </div>
          )}
        </div>
      </ScrollArea>

      <CreateContactDialog
        open={isCreateDialogOpen}
        onOpenChange={setIsCreateDialogOpen}
      />

      <ImportContactsDialog
        open={isImportDialogOpen}
        onOpenChange={setIsImportDialogOpen}
      />

      <ScrapeLeadsDialog
        open={isScrapeDialogOpen}
        onOpenChange={setIsScrapeDialogOpen}
      />

      {workspaceId && (
        <BulkTagDialog
          open={isBulkTagDialogOpen}
          onOpenChange={setIsBulkTagDialogOpen}
          selectedContactIds={selectedArray}
          workspaceId={workspaceId}
        />
      )}

      <AlertDialog open={isDeleteDialogOpen} onOpenChange={setIsDeleteDialogOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete {selectedCount} contact{selectedCount !== 1 ? "s" : ""}?</AlertDialogTitle>
            <AlertDialogDescription>
              This action cannot be undone. This will permanently delete the selected contact{selectedCount !== 1 ? "s" : ""} and all associated data.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleBulkDelete}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              disabled={bulkDeleteMutation.isPending}
            >
              {bulkDeleteMutation.isPending ? "Deleting..." : "Delete"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
