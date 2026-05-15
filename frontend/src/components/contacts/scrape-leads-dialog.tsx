"use client";

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { toast } from "sonner";
import { AlertCircle, CheckCircle2, Loader2, Search } from "lucide-react";

import {
  scrapingApi,
  type BusinessResult,
  type ImportLeadsResponse,
} from "@/lib/api/scraping";
import { useWorkspaceId } from "@/hooks/use-workspace-id";
import { useLeadImport } from "@/hooks/useLeadImport";
import { getApiErrorMessage } from "@/lib/utils/errors";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Progress } from "@/components/ui/progress";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  applyLeadFilters,
  LeadFilters,
  type LeadFilterState,
} from "@/components/contacts/shared/lead-filters";
import { LeadResultsList } from "@/components/contacts/shared/lead-results-list";

interface ScrapeLeadsDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

type DialogStep = "search" | "results" | "importing" | "done";

export function ScrapeLeadsDialog({ open, onOpenChange }: ScrapeLeadsDialogProps) {
  const workspaceId = useWorkspaceId();

  const [step, setStep] = useState<DialogStep>("search");
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<BusinessResult[]>([]);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [filters, setFilters] = useState<LeadFilterState>({
    hasPhone: true,
    noWebsite: false,
    minRating: null,
  });
  const [defaultStatus, setDefaultStatus] = useState("new");
  const [importResult, setImportResult] = useState<ImportLeadsResponse | null>(null);

  const searchMutation = useMutation({
    mutationFn: async () => {
      if (!workspaceId) throw new Error("No workspace");
      return scrapingApi.search(workspaceId, query, 40);
    },
    onSuccess: (data) => {
      setResults(data.results);
      // Auto-select leads with phone numbers
      const withPhone = new Set(
        data.results.filter((r) => r.has_phone).map((r) => r.place_id),
      );
      setSelectedIds(withPhone);
      setStep("results");
    },
    onError: (error) => {
      toast.error(
        getApiErrorMessage(error, "Failed to search. Please check your API key configuration."),
      );
    },
  });

  const importMutation = useLeadImport({
    importFn: scrapingApi.importLeads,
    onSuccess: (data) => {
      setImportResult(data);
      setStep("done");
    },
    onError: () => setStep("results"),
  });

  const handleSearch = () => {
    if (!query.trim()) {
      toast.error("Please enter a search query");
      return;
    }
    searchMutation.mutate();
  };

  const handleImport = () => {
    if (selectedIds.size === 0) {
      toast.error("Please select at least one lead to import");
      return;
    }
    const selectedLeads = results.filter((r) => selectedIds.has(r.place_id));
    setStep("importing");
    importMutation.mutate({ leads: selectedLeads, default_status: defaultStatus });
  };

  const handleClose = () => {
    setStep("search");
    setQuery("");
    setResults([]);
    setSelectedIds(new Set());
    setImportResult(null);
    onOpenChange(false);
  };

  const toggleSelect = (placeId: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(placeId)) next.delete(placeId);
      else next.add(placeId);
      return next;
    });
  };

  const filteredResults = applyLeadFilters(results, filters);

  const toggleSelectAll = () => {
    const allSelected = filteredResults.every((r) => selectedIds.has(r.place_id));
    if (allSelected) setSelectedIds(new Set());
    else setSelectedIds(new Set(filteredResults.map((r) => r.place_id)));
  };

  const selectedCount = [...selectedIds].filter((id) =>
    filteredResults.some((r) => r.place_id === id),
  ).length;

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent className="sm:max-w-[700px] max-h-[85vh] flex flex-col">
        <DialogHeader>
          <DialogTitle>
            {step === "search" && "Find Leads"}
            {step === "results" && "Search Results"}
            {step === "importing" && "Importing Leads..."}
            {step === "done" && "Import Complete"}
          </DialogTitle>
          <DialogDescription>
            {step === "search" &&
              "Search Google Places to find businesses and import them as contacts."}
            {step === "results" &&
              `Found ${results.length} businesses. Select the ones you want to import.`}
            {step === "importing" && "Please wait while we import your selected leads."}
            {step === "done" && "Here's a summary of your import."}
          </DialogDescription>
        </DialogHeader>

        {/* Search Step */}
        {step === "search" && (
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label htmlFor="search-query">Search Query</Label>
              <div className="flex gap-2">
                <Input
                  id="search-query"
                  placeholder="e.g., plumbers in Austin TX"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && handleSearch()}
                />
                <Button
                  onClick={handleSearch}
                  disabled={searchMutation.isPending || !query.trim()}
                >
                  {searchMutation.isPending ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Search className="h-4 w-4" />
                  )}
                </Button>
              </div>
              <p className="text-xs text-muted-foreground">
                Tip: Include location for better results (e.g., &quot;restaurants in downtown
                Seattle&quot;)
              </p>
            </div>
          </div>
        )}

        {/* Results Step */}
        {step === "results" && (
          <div className="flex-1 min-h-0 flex flex-col gap-4">
            <LeadFilters
              filters={filters}
              onFiltersChange={setFilters}
              filteredCount={filteredResults.length}
              totalCount={results.length}
              showNoWebsite
            />

            {/* Selection bar */}
            <div className="flex items-center gap-3">
              <Checkbox
                checked={
                  filteredResults.length > 0 &&
                  filteredResults.every((r) => selectedIds.has(r.place_id))
                }
                onCheckedChange={toggleSelectAll}
              />
              <span className="text-sm font-medium">{selectedCount} selected</span>
              <div className="flex-1" />
              <div className="flex items-center gap-2">
                <Label className="text-sm">Import as:</Label>
                <Select value={defaultStatus} onValueChange={setDefaultStatus}>
                  <SelectTrigger className="w-28 h-8">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="new">New</SelectItem>
                    <SelectItem value="contacted">Contacted</SelectItem>
                    <SelectItem value="qualified">Qualified</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>

            <LeadResultsList
              results={filteredResults}
              selectedIds={selectedIds}
              onToggleSelect={toggleSelect}
              variant="list"
            />
          </div>
        )}

        {/* Importing Step */}
        {step === "importing" && (
          <div className="py-8 space-y-4">
            <Progress value={undefined} className="h-2" />
            <p className="text-center text-sm text-muted-foreground">
              Importing {selectedCount} leads...
            </p>
          </div>
        )}

        {/* Done Step */}
        {step === "done" && importResult && (
          <div className="space-y-4 py-4">
            <div className="grid grid-cols-2 gap-4">
              <div className="p-4 bg-success/10 rounded-lg text-center">
                <CheckCircle2 className="h-8 w-8 mx-auto mb-2 text-success" />
                <p className="text-2xl font-bold text-success">{importResult.imported}</p>
                <p className="text-xs text-muted-foreground">Imported</p>
              </div>
              <div className="p-4 bg-muted/50 rounded-lg text-center">
                <p className="text-2xl font-bold">{importResult.total}</p>
                <p className="text-xs text-muted-foreground">Total Selected</p>
              </div>
            </div>

            {(importResult.skipped_duplicates > 0 || importResult.skipped_no_phone > 0) && (
              <div className="flex flex-wrap gap-4 text-sm">
                {importResult.skipped_duplicates > 0 && (
                  <div className="flex items-center gap-2 text-warning">
                    <AlertCircle className="h-4 w-4" />
                    <span>{importResult.skipped_duplicates} duplicates skipped</span>
                  </div>
                )}
                {importResult.skipped_no_phone > 0 && (
                  <div className="flex items-center gap-2 text-warning">
                    <AlertCircle className="h-4 w-4" />
                    <span>{importResult.skipped_no_phone} skipped (no phone)</span>
                  </div>
                )}
              </div>
            )}

            {importResult.errors.length > 0 && (
              <div className="space-y-2">
                <p className="text-sm font-medium">Errors:</p>
                <ScrollArea className="h-[100px] rounded-lg border">
                  <div className="p-3 space-y-2">
                    {importResult.errors.map((error, idx) => (
                      <div
                        key={idx}
                        className="text-xs p-2 bg-destructive/10 rounded text-destructive"
                      >
                        {error}
                      </div>
                    ))}
                  </div>
                </ScrollArea>
              </div>
            )}
          </div>
        )}

        <DialogFooter>
          {step === "search" && (
            <Button variant="outline" onClick={handleClose}>
              Cancel
            </Button>
          )}
          {step === "results" && (
            <>
              <Button variant="outline" onClick={() => setStep("search")}>
                Back
              </Button>
              <Button onClick={handleImport} disabled={selectedCount === 0}>
                Import {selectedCount} Lead{selectedCount !== 1 ? "s" : ""}
              </Button>
            </>
          )}
          {step === "done" && <Button onClick={handleClose}>Done</Button>}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
