"use client";

import { useState } from "react";
import Link from "next/link";
import { useMutation } from "@tanstack/react-query";
import { toast } from "sonner";
import { CheckCircle2, Loader2, MapPin, Search, Users } from "lucide-react";

import {
  scrapingApi,
  type BusinessResult,
  type ImportLeadsResponse,
} from "@/lib/api/scraping";
import { useWorkspaceId } from "@/hooks/use-workspace-id";
import { useLeadImport } from "@/hooks/useLeadImport";
import { getApiErrorMessage } from "@/lib/utils/errors";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Card,
  CardContent,
} from "@/components/ui/card";
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

export function FindLeadsPage() {
  const workspaceId = useWorkspaceId();

  const [query, setQuery] = useState("");
  const [results, setResults] = useState<BusinessResult[]>([]);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [filters, setFilters] = useState<LeadFilterState>({
    hasPhone: true,
    noWebsite: false,
    hideTollFree: true,
    minRating: null,
  });
  const [maxResults, setMaxResults] = useState(60);
  const [defaultStatus, setDefaultStatus] = useState("new");
  const [importResult, setImportResult] = useState<ImportLeadsResponse | null>(null);
  const [hasSearched, setHasSearched] = useState(false);

  const searchMutation = useMutation({
    mutationFn: async () => {
      if (!workspaceId) throw new Error("No workspace");
      return scrapingApi.search(workspaceId, query, maxResults);
    },
    onSuccess: (data) => {
      setResults(data.results);
      setHasSearched(true);
      setImportResult(null);
      const withPhone = new Set(
        data.results.filter((r) => r.has_phone).map((r) => r.place_id)
      );
      setSelectedIds(withPhone);
      toast.success(`Found ${data.results.length} businesses`);
    },
    onError: (error) => {
      toast.error(
        getApiErrorMessage(error, "Failed to search. Please check your API key configuration.")
      );
    },
  });

  const importMutation = useLeadImport({
    importFn: scrapingApi.importLeads,
    onSuccess: setImportResult,
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
    importMutation.mutate({ leads: selectedLeads, default_status: defaultStatus });
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
    filteredResults.some((r) => r.place_id === id)
  ).length;

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Header */}
      <div className="shrink-0 p-6 border-b space-y-4">
        <div className="flex items-center gap-3">
          <MapPin className="h-6 w-6 text-primary" />
          <h1 className="text-2xl font-bold">Find Leads</h1>
        </div>
        <p className="text-muted-foreground">
          Search Google Places for businesses and import them as contacts for your SMS campaigns.
        </p>

        {/* Search Bar */}
        <div className="flex gap-2 max-w-2xl">
          <Input
            placeholder="e.g., plumbers in Austin TX, restaurants in downtown Seattle"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleSearch()}
            className="flex-1"
          />
          <Select value={maxResults.toString()} onValueChange={(v) => setMaxResults(parseInt(v))}>
            <SelectTrigger className="w-24">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="20">20</SelectItem>
              <SelectItem value="40">40</SelectItem>
              <SelectItem value="60">60</SelectItem>
              <SelectItem value="80">80</SelectItem>
              <SelectItem value="100">100</SelectItem>
            </SelectContent>
          </Select>
          <Button
            onClick={handleSearch}
            disabled={searchMutation.isPending || !query.trim()}
            className="gap-2"
          >
            {searchMutation.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Search className="h-4 w-4" />
            )}
            Search
          </Button>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 min-h-0 overflow-hidden">
        {!hasSearched ? (
          <div className="flex flex-col items-center justify-center h-full text-center p-6">
            <MapPin className="h-16 w-16 text-muted-foreground/50 mb-4" />
            <h3 className="text-lg font-medium mb-2">Search for businesses</h3>
            <p className="text-sm text-muted-foreground max-w-md">
              Enter a search query above to find businesses. Include a location for better results
              (e.g., &quot;plumbers in Austin TX&quot;).
            </p>
          </div>
        ) : (
          <div className="flex flex-col h-full p-6 gap-4">
            {/* Import Result Banner */}
            {importResult && (
              <Card className="border-success/20 bg-success/10">
                <CardContent className="p-4">
                  <div className="flex items-center gap-4">
                    <CheckCircle2 className="h-8 w-8 text-success" />
                    <div className="flex-1">
                      <p className="font-medium">
                        Successfully imported {importResult.imported} leads
                      </p>
                      <div className="flex gap-4 text-sm text-muted-foreground">
                        {importResult.skipped_duplicates > 0 && (
                          <span>{importResult.skipped_duplicates} duplicates skipped</span>
                        )}
                        {importResult.skipped_no_phone > 0 && (
                          <span>{importResult.skipped_no_phone} skipped (no phone)</span>
                        )}
                      </div>
                    </div>
                    <Button variant="outline" size="sm" asChild>
                      <Link href="/contacts">View Contacts</Link>
                    </Button>
                  </div>
                </CardContent>
              </Card>
            )}

            <LeadFilters
              filters={filters}
              onFiltersChange={setFilters}
              filteredCount={filteredResults.length}
              totalCount={results.length}
              showNoWebsite
              showHideTollFree
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
              <Button
                onClick={handleImport}
                disabled={selectedCount === 0 || importMutation.isPending}
                className="gap-2"
              >
                {importMutation.isPending ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Users className="h-4 w-4" />
                )}
                Import {selectedCount} Lead{selectedCount !== 1 ? "s" : ""}
              </Button>
            </div>

            <LeadResultsList
              results={filteredResults}
              selectedIds={selectedIds}
              onToggleSelect={toggleSelect}
            />
          </div>
        )}
      </div>
    </div>
  );
}
