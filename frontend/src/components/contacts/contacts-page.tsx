"use client";

import { useQueryClient } from "@tanstack/react-query";
import { Users, CheckSquare, X, Plus, Upload } from "lucide-react";
import { AnimatePresence } from "motion/react";
import { useSearchParams, useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { BulkTagDialog } from "@/components/contacts/bulk-tag-dialog";
import { ContactCard, ContactCardSkeleton } from "@/components/contacts/contact-card";
import { ContactFormDialog } from "@/components/contacts/contact-form-dialog";
import { ContactsBulkActions } from "@/components/contacts/contacts-bulk-actions";
import { ContactsEmptyState } from "@/components/contacts/contacts-empty-state";
import { ContactsToolbar } from "@/components/contacts/contacts-toolbar";
import { ImportContactsDialog } from "@/components/contacts/import-contacts-dialog";
import { ScrapeLeadsDialog } from "@/components/contacts/scrape-leads-dialog";
import { ResourceListPagination } from "@/components/resource-list/resource-list-pagination";
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
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { PageErrorState } from "@/components/ui/page-state";
import { ScrollArea } from "@/components/ui/scroll-area";
import { useCapabilities } from "@/hooks/useCapabilities";
import { useBulkDeleteContacts, useBulkUpdateStatus, useContactIds, useContactsPaginated } from "@/hooks/useContacts";
import { useRowSelection } from "@/hooks/useRowSelection";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import type { ContactIdsParams, ContactsListParams } from "@/lib/api/contacts";
import { useContactStore } from "@/lib/contact-store";
import { queryKeys } from "@/lib/query-keys";
import type { Contact, ContactStatus } from "@/types";

export function ContactsPage() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const { can } = useCapabilities();
  // crm:write — managers/admins. Sales & tech have crm:read only (view, no edit).
  const canWriteContacts = can("crm:write");
  const [isCreateDialogOpen, setIsCreateDialogOpen] = useState(false);
  const [isScrapeDialogOpen, setIsScrapeDialogOpen] = useState(false);

  const importRequested = searchParams.get("import") === "true";
  const [isImportDialogOpen, setIsImportDialogOpen] = useState(importRequested);

  // Auto-open import dialog when navigated here with ?import=true
  useEffect(() => {
    if (!importRequested) return undefined;

    const timer = window.setTimeout(() => setIsImportDialogOpen(true), 0);
    const urlParams = new URLSearchParams(searchParams.toString());
    urlParams.delete("import");
    const newUrl = urlParams.size > 0 ? `/?${urlParams.toString()}` : "/";
    router.replace(newUrl, { scroll: false });

    return () => window.clearTimeout(timer);
  }, [importRequested, searchParams, router]);

  const [isSelectionMode, setIsSelectionMode] = useState(false);
  const [selectAllMatchingIds, setSelectAllMatchingIds] = useState<Set<number> | null>(null);
  const [isDeleteDialogOpen, setIsDeleteDialogOpen] = useState(false);
  const [isBulkTagDialogOpen, setIsBulkTagDialogOpen] = useState(false);

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

  // Pre-apply a segment's filter definition when navigated here with
  // ?filters=<json> (e.g. "View contacts" from the Segments page).
  const filtersParam = searchParams.get("filters");
  useEffect(() => {
    if (!filtersParam) return;
    try {
      const parsed = JSON.parse(filtersParam) as typeof filters;
      if (parsed && Array.isArray(parsed.rules) && parsed.rules.length > 0) {
        setFilters(parsed);
      }
    } catch {
      // Ignore malformed filter params.
    }
    const urlParams = new URLSearchParams(searchParams.toString());
    urlParams.delete("filters");
    const newUrl = urlParams.size > 0 ? `/contacts?${urlParams.toString()}` : "/contacts";
    router.replace(newUrl, { scroll: false });
  }, [filtersParam, searchParams, router, setFilters]);

  // Debounced search input: local state updates immediately, store updates after delay
  const [inputValue, setInputValue] = useState(searchQuery);

  // Build query params from store filter/sort/pagination state
  const contactsListParams = useMemo<ContactsListParams>(() => ({
    page: contactsPage,
    page_size: contactsPageSize,
    sort_by: sortBy,
    ...(searchQuery.trim() && { search: searchQuery.trim() }),
    ...(statusFilter && { status: statusFilter as ContactStatus }),
    ...(filters && { filters: JSON.stringify(filters) }),
  }), [contactsPage, contactsPageSize, sortBy, searchQuery, statusFilter, filters]);

  // Fetch contacts via React Query
  const {
    data: contactsData,
    isPending: isLoadingContacts,
    isError: isContactsError,
    refetch: refetchContacts,
  } = useContactsPaginated(
    workspaceId ?? "",
    contactsListParams,
  );
  const contacts = useMemo(() => contactsData?.items ?? [], [contactsData?.items]);
  const contactsTotal = contactsData?.total ?? 0;
  const contactsTotalPages = contactsData?.pages ?? 1;

  // Standardized base row selection (single toggle, shift-range, clear).
  // `selectAllMatchingIds` overlays this as a server-side "all matching" set.
  const rowIds = useMemo(() => contacts.map((c: Contact) => c.id), [contacts]);
  const selection = useRowSelection<number>({ rowIds });

  // Debounce search: update store query 400ms after user stops typing
  useEffect(() => {
    const timer = setTimeout(() => {
      setSearchQuery(inputValue);
    }, 400);
    return () => clearTimeout(timer);
  }, [inputValue, setSearchQuery]);

  // Build params for the /ids endpoint (for "select all matching")
  const idsParams = useMemo<ContactIdsParams>(() => {
    const params: ContactIdsParams = {};
    if (searchQuery.trim()) params.search = searchQuery.trim();
    if (statusFilter) params.status = statusFilter as ContactStatus;
    if (filters) params.filters = JSON.stringify(filters);
    return params;
  }, [searchQuery, statusFilter, filters]);

  // Effective selected IDs: either the explicit set or the "select all matching" set
  const effectiveSelectedIds: ReadonlySet<number> = selectAllMatchingIds ?? selection.selectedIds;
  const selectedCount = effectiveSelectedIds.size;
  const selectedArray = useMemo(() => Array.from(effectiveSelectedIds), [effectiveSelectedIds]);

  // Status counts from current page contacts (all count uses server total)
  const statusCounts = useMemo<Record<ContactStatus | "all", number>>(() => {
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
      selection.clear();
      setSelectAllMatchingIds(null);
    }
    setIsSelectionMode(!isSelectionMode);
  };

  const handleSelectContact = (contactId: number, _checked: boolean, shiftKey: boolean) => {
    // Breaking out of "select all matching": materialize the overlay into the
    // base selection, then toggle the clicked row on top of it.
    if (selectAllMatchingIds) {
      setSelectAllMatchingIds(null);
      selection.selectIds(selectAllMatchingIds);
    }
    selection.toggle(contactId, shiftKey);
  };

  const handleSelectAllVisible = () => {
    setSelectAllMatchingIds(null);
    selection.toggleAllVisible();
  };

  const [fetchAllIds, setFetchAllIds] = useState(false);
  const { data: allIdsData, isFetching: isFetchingAllIds } = useContactIds(
    workspaceId ?? "",
    idsParams,
    fetchAllIds,
    (data) => {
      setSelectAllMatchingIds(new Set(data.ids));
      selection.clear();
      setFetchAllIds(false);
    }
  );

  const handleSelectAllMatching = () => {
    if (allIdsData) {
      setSelectAllMatchingIds(new Set(allIdsData.ids));
      selection.clear();
      setFetchAllIds(false);
    } else {
      setFetchAllIds(true);
    }
  };

  const handleClearSelection = () => {
    selection.clear();
    setSelectAllMatchingIds(null);
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
      void queryClient.invalidateQueries({ queryKey: queryKeys.contacts.all(workspaceId ?? "") });
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
            {!isSelectionMode && canWriteContacts && (
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
          ) : isContactsError ? (
            <PageErrorState
              message="We couldn't load your contacts. Please try again."
              onRetry={() => refetchContacts()}
            />
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

      <ContactFormDialog
        mode="create"
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
