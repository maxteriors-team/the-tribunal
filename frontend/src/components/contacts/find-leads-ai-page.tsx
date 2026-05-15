"use client";

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  Globe,
  Linkedin,
  Loader2,
  Search,
  Sparkles,
  Users,
} from "lucide-react";

import {
  findLeadsAIApi,
  type AIImportLeadsResponse,
  type BusinessResult,
} from "@/lib/api/find-leads-ai";
import { useWorkspaceId } from "@/hooks/use-workspace-id";
import { useLeadImport } from "@/hooks/useLeadImport";
import { getApiErrorMessage } from "@/lib/utils/errors";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { AIImportResultBanner } from "@/components/contacts/shared/ai-import-result-banner";
import {
  applyLeadFilters,
  LeadFilters,
  type LeadFilterState,
} from "@/components/contacts/shared/lead-filters";
import { LeadResultsList } from "@/components/contacts/shared/lead-results-list";

// Re-export status badges for callers that historically imported them from this module.
export {
  AdPixelBadges,
  EnrichmentStatusBadge,
  LeadScoreBadge,
} from "@/components/contacts/shared/lead-status-badges";

export function FindLeadsAIPage() {
  const workspaceId = useWorkspaceId();

  const [query, setQuery] = useState("");
  const [results, setResults] = useState<BusinessResult[]>([]);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [filters, setFilters] = useState<LeadFilterState>({
    hasPhone: true,
    hasWebsite: true,
    hideTollFree: true,
    minRating: null,
  });
  const [maxResults, setMaxResults] = useState(60);
  const [defaultStatus, setDefaultStatus] = useState("new");
  const [enableEnrichment, setEnableEnrichment] = useState(true);
  const [minLeadScore, setMinLeadScore] = useState(80);
  const [importResult, setImportResult] = useState<AIImportLeadsResponse | null>(null);
  const [hasSearched, setHasSearched] = useState(false);
  const [showDetails, setShowDetails] = useState(false);

  const searchMutation = useMutation({
    mutationFn: async (searchQuery?: string) => {
      if (!workspaceId) throw new Error("No workspace");
      return findLeadsAIApi.search(workspaceId, searchQuery || query, maxResults);
    },
    onSuccess: (data) => {
      setResults(data.results);
      setHasSearched(true);
      setImportResult(null);
      // Auto-select businesses with phone AND website (enrichable)
      const withPhoneAndWebsite = new Set(
        data.results.filter((r) => r.has_phone && r.has_website).map((r) => r.place_id),
      );
      setSelectedIds(withPhoneAndWebsite);
      toast.success(`Found ${data.results.length} businesses`);
    },
    onError: (error) => {
      toast.error(
        getApiErrorMessage(error, "Failed to search. Please check your API key configuration."),
      );
    },
  });

  const importMutation = useLeadImport({
    importFn: findLeadsAIApi.importLeads,
    onSuccess: setImportResult,
    successToast: (data) => {
      if (data.imported > 0) {
        const rejectedMsg =
          data.rejected_low_score > 0
            ? ` (${data.rejected_low_score} rejected below quality threshold)`
            : "";
        return {
          type: "success",
          message: `Successfully imported ${data.imported} leads${rejectedMsg}`,
        };
      }
      const reasons: string[] = [];
      if (data.rejected_low_score > 0)
        reasons.push(`${data.rejected_low_score} below quality threshold`);
      if (data.enrichment_failed > 0) reasons.push(`${data.enrichment_failed} enrichment failed`);
      if (data.skipped_duplicates > 0) reasons.push(`${data.skipped_duplicates} duplicates`);
      if (data.skipped_no_phone > 0) reasons.push(`${data.skipped_no_phone} no phone`);
      return { type: "error", message: `No leads imported: ${reasons.join(", ")}` };
    },
  });

  const handleSearch = (searchQuery?: string) => {
    const q = searchQuery || query;
    if (!q.trim()) {
      toast.error("Please enter a search query");
      return;
    }
    if (searchQuery) setQuery(searchQuery);
    searchMutation.mutate(searchQuery);
  };

  const handleImport = () => {
    if (selectedIds.size === 0) {
      toast.error("Please select at least one lead to import");
      return;
    }
    const selectedLeads = results.filter((r) => selectedIds.has(r.place_id));
    importMutation.mutate({
      leads: selectedLeads,
      default_status: defaultStatus,
      enable_enrichment: enableEnrichment,
      min_lead_score: minLeadScore,
    });
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

  const enrichableCount = [...selectedIds].filter((id) => {
    const result = filteredResults.find((r) => r.place_id === id);
    return result?.has_website;
  }).length;

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Header */}
      <div className="shrink-0 p-6 border-b space-y-4">
        <div className="flex items-center gap-3">
          <Sparkles className="h-6 w-6 text-primary" />
          <div>
            <h1 className="text-2xl font-bold">Find Leads AI</h1>
            <p className="text-sm text-muted-foreground">
              AI-powered lead enrichment with social media discovery
            </p>
          </div>
        </div>

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
            onClick={() => handleSearch()}
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
            <Sparkles className="h-16 w-16 text-muted-foreground/50 mb-4" />
            <h3 className="text-lg font-medium mb-2">AI-Enhanced Lead Discovery</h3>
            <p className="text-sm text-muted-foreground max-w-md mb-4">
              Search for businesses and we&apos;ll automatically enrich them with social media
              profiles (LinkedIn, Facebook, etc.) for personalized AI messaging.
            </p>
            <div className="flex flex-wrap gap-2 justify-center text-xs text-muted-foreground">
              <Badge variant="outline" className="gap-1">
                <Linkedin className="h-3 w-3" /> LinkedIn Discovery
              </Badge>
              <Badge variant="outline" className="gap-1">
                <Globe className="h-3 w-3" /> Website Scraping
              </Badge>
              <Badge variant="outline" className="gap-1">
                <Sparkles className="h-3 w-3" /> AI Personalization
              </Badge>
            </div>
            <div className="flex flex-wrap gap-2 justify-center mt-4">
              {[
                "Roofing companies in Dallas TX",
                "Roofing companies in Houston TX",
                "HVAC companies in Phoenix AZ",
                "Plumbers in Miami FL",
              ].map((suggestion) => (
                <Button
                  key={suggestion}
                  variant="outline"
                  size="sm"
                  className="text-xs"
                  onClick={() => handleSearch(suggestion)}
                >
                  {suggestion}
                </Button>
              ))}
            </div>
          </div>
        ) : (
          <div className="flex flex-col h-full p-6 gap-4">
            {importResult && (
              <AIImportResultBanner
                result={importResult}
                showDetails={showDetails}
                onToggleDetails={() => setShowDetails(!showDetails)}
              />
            )}

            <LeadFilters
              filters={filters}
              onFiltersChange={setFilters}
              filteredCount={filteredResults.length}
              totalCount={results.length}
              showHasWebsite
              showHideTollFree
              websiteBadge
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
              {enableEnrichment && enrichableCount > 0 && (
                <Badge variant="secondary" className="gap-1">
                  <Sparkles className="h-3 w-3" />
                  {enrichableCount} enrichable
                </Badge>
              )}
              <div className="flex-1" />
              <div className="flex items-center gap-2">
                <Checkbox
                  id="enable-enrichment"
                  checked={enableEnrichment}
                  onCheckedChange={(checked) => setEnableEnrichment(checked === true)}
                />
                <Label htmlFor="enable-enrichment" className="text-sm cursor-pointer">
                  AI Enrichment
                </Label>
              </div>
              <div className="flex items-center gap-2">
                <Label className="text-sm">Min quality:</Label>
                <Select
                  value={minLeadScore.toString()}
                  onValueChange={(v) => setMinLeadScore(parseInt(v))}
                >
                  <SelectTrigger className="w-28 h-8">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="0">Any (0+)</SelectItem>
                    <SelectItem value="40">Low (40+)</SelectItem>
                    <SelectItem value="80">Medium (80+)</SelectItem>
                    <SelectItem value="100">High (100+)</SelectItem>
                    <SelectItem value="120">Elite (120+)</SelectItem>
                  </SelectContent>
                </Select>
              </div>
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
              renderCardBadge={(result) =>
                result.has_website && enableEnrichment ? (
                  <Badge variant="secondary" className="shrink-0 gap-1 text-xs">
                    <Sparkles className="h-3 w-3" />
                    AI
                  </Badge>
                ) : null
              }
            />
          </div>
        )}
      </div>
    </div>
  );
}
