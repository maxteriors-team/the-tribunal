"use client";

import { useState } from "react";
import Link from "next/link";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  Search,
  Phone,
  Globe,
  Star,
  MapPin,
  CheckCircle2,
  AlertCircle,
  Loader2,
  Users,
} from "lucide-react";

import {
  scrapingApi,
  type BusinessResult,
  type ImportLeadsResponse,
} from "@/lib/api/scraping";
import { useWorkspaceId } from "@/hooks/use-workspace-id";
import { queryKeys } from "@/lib/query-keys";
import { getApiErrorMessage } from "@/lib/utils/errors";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { cn } from "@/lib/utils";

const TOLL_FREE_PREFIXES = ["800", "888", "877", "866", "855", "844", "833"];

function isTollFreeNumber(phone: string | null): boolean {
  if (!phone) return false;
  const digits = phone.replace(/\D/g, "");
  // Strip leading country code "1" for US numbers
  const normalized = digits.startsWith("1") && digits.length === 11 ? digits.slice(1) : digits;
  return TOLL_FREE_PREFIXES.some((prefix) => normalized.startsWith(prefix));
}

interface Filters {
  hasPhone: boolean;
  noWebsite: boolean;
  hideTollFree: boolean;
  minRating: number | null;
}

export function FindLeadsPage() {
  const queryClient = useQueryClient();
  const workspaceId = useWorkspaceId();

  const [query, setQuery] = useState("");
  const [results, setResults] = useState<BusinessResult[]>([]);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [filters, setFilters] = useState<Filters>({
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
      toast.error(getApiErrorMessage(error, "Failed to search. Please check your API key configuration."));
    },
  });

  const importMutation = useMutation({
    mutationFn: async () => {
      if (!workspaceId) throw new Error("No workspace");
      const selectedLeads = results.filter((r) => selectedIds.has(r.place_id));
      return scrapingApi.importLeads(workspaceId, {
        leads: selectedLeads,
        default_status: defaultStatus,
      });
    },
    onSuccess: (data) => {
      setImportResult(data);
      queryClient.invalidateQueries({ queryKey: queryKeys.contacts.bare(workspaceId ?? "") });
      if (data.imported > 0) {
        toast.success(`Successfully imported ${data.imported} leads`);
      }
    },
    onError: (error) => {
      toast.error(getApiErrorMessage(error, "Failed to import leads"));
    },
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
    importMutation.mutate();
  };

  const toggleSelect = (placeId: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(placeId)) {
        next.delete(placeId);
      } else {
        next.add(placeId);
      }
      return next;
    });
  };

  const toggleSelectAll = () => {
    const filtered = filteredResults;
    const allSelected = filtered.every((r) => selectedIds.has(r.place_id));
    if (allSelected) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(filtered.map((r) => r.place_id)));
    }
  };

  const filteredResults = results.filter((r) => {
    if (filters.hasPhone && !r.has_phone) return false;
    if (filters.noWebsite && r.has_website) return false;
    if (filters.hideTollFree && isTollFreeNumber(r.phone_number)) return false;
    if (filters.minRating && (!r.rating || r.rating < filters.minRating)) return false;
    return true;
  });

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

            {/* Filters & Actions */}
            <div className="flex flex-wrap items-center gap-4 p-3 bg-muted/50 rounded-lg">
              <div className="flex items-center gap-2">
                <Checkbox
                  id="filter-phone"
                  checked={filters.hasPhone}
                  onCheckedChange={(checked) =>
                    setFilters({ ...filters, hasPhone: checked === true })
                  }
                />
                <Label htmlFor="filter-phone" className="text-sm cursor-pointer">
                  Has phone
                </Label>
              </div>
              <div className="flex items-center gap-2">
                <Checkbox
                  id="filter-website"
                  checked={filters.noWebsite}
                  onCheckedChange={(checked) =>
                    setFilters({ ...filters, noWebsite: checked === true })
                  }
                />
                <Label htmlFor="filter-website" className="text-sm cursor-pointer">
                  No website
                </Label>
              </div>
              <div className="flex items-center gap-2">
                <Checkbox
                  id="filter-toll-free"
                  checked={filters.hideTollFree}
                  onCheckedChange={(checked) =>
                    setFilters({ ...filters, hideTollFree: checked === true })
                  }
                />
                <Label htmlFor="filter-toll-free" className="text-sm cursor-pointer">
                  Hide 800 numbers
                </Label>
              </div>
              <div className="flex items-center gap-2">
                <Label className="text-sm">Min rating:</Label>
                <Select
                  value={filters.minRating?.toString() || "any"}
                  onValueChange={(v) =>
                    setFilters({ ...filters, minRating: v === "any" ? null : parseFloat(v) })
                  }
                >
                  <SelectTrigger className="w-20 h-8">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="any">Any</SelectItem>
                    <SelectItem value="3">3+</SelectItem>
                    <SelectItem value="4">4+</SelectItem>
                    <SelectItem value="4.5">4.5+</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="flex-1" />
              <span className="text-sm text-muted-foreground">
                {filteredResults.length} of {results.length} shown
              </span>
            </div>

            {/* Selection bar */}
            <div className="flex items-center gap-3">
              <Checkbox
                checked={filteredResults.length > 0 && filteredResults.every((r) => selectedIds.has(r.place_id))}
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

            {/* Results Grid */}
            <ScrollArea className="flex-1 min-h-0">
              {filteredResults.length === 0 ? (
                <div className="py-16 text-center text-muted-foreground">
                  <AlertCircle className="h-12 w-12 mx-auto mb-4 opacity-50" />
                  <p>No results match your filters</p>
                </div>
              ) : (
                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 pr-4">
                  {filteredResults.map((result) => (
                    <Card
                      key={result.place_id}
                      className={cn(
                        "cursor-pointer transition-all",
                        selectedIds.has(result.place_id)
                          ? "ring-2 ring-primary border-primary"
                          : "hover:border-primary/50"
                      )}
                      onClick={() => toggleSelect(result.place_id)}
                    >
                      <CardHeader className="p-4 pb-2">
                        <div className="flex items-start gap-3">
                          <Checkbox
                            checked={selectedIds.has(result.place_id)}
                            onCheckedChange={() => toggleSelect(result.place_id)}
                            className="mt-1"
                            onClick={(e) => e.stopPropagation()}
                          />
                          <div className="flex-1 min-w-0">
                            <CardTitle className="text-base truncate">
                              {result.name}
                            </CardTitle>
                            {result.rating && (
                              <div className="flex items-center gap-1 mt-1">
                                <Star className="h-3 w-3 fill-warning text-warning" />
                                <span className="text-sm">{result.rating}</span>
                                {result.review_count > 0 && (
                                  <span className="text-xs text-muted-foreground">
                                    ({result.review_count})
                                  </span>
                                )}
                              </div>
                            )}
                          </div>
                        </div>
                      </CardHeader>
                      <CardContent className="p-4 pt-0">
                        {result.address && (
                          <CardDescription className="flex items-start gap-1 mb-2">
                            <MapPin className="h-3 w-3 mt-0.5 shrink-0" />
                            <span className="line-clamp-2">{result.address}</span>
                          </CardDescription>
                        )}
                        <div className="flex items-center gap-4 text-sm">
                          <div
                            className={cn(
                              "flex items-center gap-1",
                              result.has_phone ? "text-success" : "text-muted-foreground"
                            )}
                          >
                            <Phone className="h-3 w-3" />
                            <span className="truncate max-w-[120px]">
                              {result.phone_number || "No phone"}
                            </span>
                          </div>
                          <div
                            className={cn(
                              "flex items-center gap-1",
                              result.has_website ? "text-info" : "text-muted-foreground"
                            )}
                          >
                            <Globe className="h-3 w-3" />
                            {result.has_website ? "Website" : "None"}
                          </div>
                        </div>
                        {result.types.length > 0 && (
                          <div className="flex flex-wrap gap-1 mt-2">
                            {result.types.slice(0, 2).map((type) => (
                              <Badge key={type} variant="outline" className="text-xs">
                                {type.replace(/_/g, " ")}
                              </Badge>
                            ))}
                          </div>
                        )}
                      </CardContent>
                    </Card>
                  ))}
                </div>
              )}
            </ScrollArea>
          </div>
        )}
      </div>
    </div>
  );
}
