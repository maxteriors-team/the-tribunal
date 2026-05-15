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
  Sparkles,
  Linkedin,
  Clock,
  XCircle,
  Megaphone,
} from "lucide-react";

import {
  findLeadsAIApi,
  type BusinessResult,
  type AIImportLeadsResponse,
} from "@/lib/api/find-leads-ai";
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
  const normalized = digits.startsWith("1") && digits.length === 11 ? digits.slice(1) : digits;
  return TOLL_FREE_PREFIXES.some((prefix) => normalized.startsWith(prefix));
}

interface Filters {
  hasPhone: boolean;
  hasWebsite: boolean;
  hideTollFree: boolean;
  minRating: number | null;
}

export function FindLeadsAIPage() {
  const queryClient = useQueryClient();
  const workspaceId = useWorkspaceId();

  const [query, setQuery] = useState("");
  const [results, setResults] = useState<BusinessResult[]>([]);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [filters, setFilters] = useState<Filters>({
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
        data.results
          .filter((r) => r.has_phone && r.has_website)
          .map((r) => r.place_id)
      );
      setSelectedIds(withPhoneAndWebsite);
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
      return findLeadsAIApi.importLeads(workspaceId, {
        leads: selectedLeads,
        default_status: defaultStatus,
        enable_enrichment: enableEnrichment,
        min_lead_score: minLeadScore,
      });
    },
    onSuccess: (data) => {
      setImportResult(data);
      queryClient.invalidateQueries({ queryKey: queryKeys.contacts.bare(workspaceId ?? "") });
      if (data.imported > 0) {
        const rejectedMsg = data.rejected_low_score > 0
          ? ` (${data.rejected_low_score} rejected below quality threshold)`
          : "";
        toast.success(`Successfully imported ${data.imported} leads${rejectedMsg}`);
      } else {
        const reasons = [];
        if (data.rejected_low_score > 0) reasons.push(`${data.rejected_low_score} below quality threshold`);
        if (data.enrichment_failed > 0) reasons.push(`${data.enrichment_failed} enrichment failed`);
        if (data.skipped_duplicates > 0) reasons.push(`${data.skipped_duplicates} duplicates`);
        if (data.skipped_no_phone > 0) reasons.push(`${data.skipped_no_phone} no phone`);
        toast.error(`No leads imported: ${reasons.join(", ")}`);
      }
    },
    onError: (error) => {
      toast.error(getApiErrorMessage(error, "Failed to import leads"));
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
    if (filters.hasWebsite && !r.has_website) return false;
    if (filters.hideTollFree && isTollFreeNumber(r.phone_number)) return false;
    if (filters.minRating && (!r.rating || r.rating < filters.minRating)) return false;
    return true;
  });

  const selectedCount = [...selectedIds].filter((id) =>
    filteredResults.some((r) => r.place_id === id)
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
            {/* Import Result Banner */}
            {importResult && (
              <Card className={importResult.imported > 0 ? "border-success/20 bg-success/10" : "border-warning/20 bg-warning/10"}>
                <CardContent className="p-4">
                  <div className="flex items-center gap-4">
                    {importResult.imported > 0 ? (
                      <CheckCircle2 className="h-8 w-8 text-success" />
                    ) : (
                      <AlertCircle className="h-8 w-8 text-warning" />
                    )}
                    <div className="flex-1">
                      <p className="font-medium">
                        {importResult.imported > 0
                          ? `Successfully imported ${importResult.imported} leads`
                          : "No leads imported"}
                      </p>
                      <div className="flex gap-4 text-sm text-muted-foreground flex-wrap">
                        {importResult.rejected_low_score > 0 && (
                          <span className="flex items-center gap-1">
                            <XCircle className="h-3 w-3" />
                            {importResult.rejected_low_score} rejected below quality threshold
                          </span>
                        )}
                        {importResult.enrichment_failed > 0 && (
                          <span>{importResult.enrichment_failed} enrichment failed</span>
                        )}
                        {importResult.skipped_duplicates > 0 && (
                          <span>{importResult.skipped_duplicates} duplicates skipped</span>
                        )}
                        {importResult.skipped_no_phone > 0 && (
                          <span>{importResult.skipped_no_phone} skipped (no phone)</span>
                        )}
                      </div>
                    </div>
                    {importResult.imported > 0 && (
                      <Button variant="outline" size="sm" asChild>
                        <Link href="/contacts">View Contacts</Link>
                      </Button>
                    )}
                  </div>
                </CardContent>
                {importResult.lead_details && importResult.lead_details.length > 0 && (
                  <div className="border-t px-4 pb-4">
                    <Button
                      variant="ghost"
                      size="sm"
                      className="w-full mt-2 text-xs"
                      onClick={() => setShowDetails(!showDetails)}
                    >
                      {showDetails ? "Hide" : "Show"} details ({importResult.lead_details.length} leads)
                    </Button>
                    {showDetails && (
                      <div className="mt-2 max-h-64 overflow-y-auto space-y-1">
                        {importResult.lead_details.map((detail, i) => (
                          <div
                            key={i}
                            className={cn(
                              "flex items-center justify-between text-xs px-2 py-1.5 rounded",
                              detail.status === "imported" && "bg-success/10 text-success",
                              detail.status === "rejected_low_score" && "bg-warning/10 text-warning",
                              detail.status === "enrichment_failed" && "bg-destructive/10 text-destructive",
                              detail.status === "skipped_duplicate" && "bg-muted text-muted-foreground",
                              detail.status === "skipped_no_phone" && "bg-muted text-muted-foreground",
                            )}
                          >
                            <div className="flex items-center gap-2 min-w-0">
                              {detail.status === "imported" && <CheckCircle2 className="h-3 w-3 shrink-0" />}
                              {detail.status === "rejected_low_score" && <XCircle className="h-3 w-3 shrink-0" />}
                              {detail.status === "enrichment_failed" && <AlertCircle className="h-3 w-3 shrink-0" />}
                              <span className="truncate font-medium">{detail.name}</span>
                              {detail.decision_maker_name && (
                                <span className="text-muted-foreground truncate">
                                  ({detail.decision_maker_title || "Owner"}: {detail.decision_maker_name})
                                </span>
                              )}
                            </div>
                            <div className="flex items-center gap-2 shrink-0">
                              {detail.revenue_tier && (
                                <Badge variant="outline" className="text-[10px] px-1 py-0">
                                  {detail.revenue_tier}
                                </Badge>
                              )}
                              {detail.lead_score != null && (
                                <Badge
                                  variant="outline"
                                  className={cn(
                                    "text-[10px] px-1 py-0 font-semibold",
                                    detail.lead_score >= 100
                                      ? "text-success bg-success/10 border-success/20"
                                      : detail.lead_score >= 80
                                        ? "text-info bg-info/10 border-info/20"
                                        : "text-warning bg-warning/10 border-warning/20"
                                  )}
                                >
                                  Score: {detail.lead_score}
                                </Badge>
                              )}
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}
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
                  checked={filters.hasWebsite}
                  onCheckedChange={(checked) =>
                    setFilters({ ...filters, hasWebsite: checked === true })
                  }
                />
                <Label htmlFor="filter-website" className="text-sm cursor-pointer flex items-center gap-1">
                  Has website
                  <Badge variant="secondary" className="text-[10px] px-1 py-0">
                    AI
                  </Badge>
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
                <Select value={minLeadScore.toString()} onValueChange={(v) => setMinLeadScore(parseInt(v))}>
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
                          {/* Enrichment indicator */}
                          {result.has_website && enableEnrichment && (
                            <Badge variant="secondary" className="shrink-0 gap-1 text-xs">
                              <Sparkles className="h-3 w-3" />
                              AI
                            </Badge>
                          )}
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

// Enrichment status badge component for contact cards (can be used elsewhere)
export function EnrichmentStatusBadge({ status }: { status: string | null | undefined }) {
  if (!status) return null;

  const statusConfig = {
    pending: { icon: Clock, label: "Enriching...", className: "text-warning bg-warning/10" },
    enriched: { icon: CheckCircle2, label: "Enriched", className: "text-success bg-success/10" },
    failed: { icon: XCircle, label: "Failed", className: "text-destructive bg-destructive/10" },
    skipped: { icon: null, label: "No website", className: "text-muted-foreground bg-muted" },
  };

  const config = statusConfig[status as keyof typeof statusConfig];
  if (!config) return null;

  const Icon = config.icon;

  return (
    <Badge variant="outline" className={cn("gap-1 text-xs", config.className)}>
      {Icon && <Icon className="h-3 w-3" />}
      {config.label}
    </Badge>
  );
}

export function LeadScoreBadge({ score }: { score: number | null | undefined }) {
  if (score == null) return null;

  const color =
    score >= 80
      ? "text-success bg-success/10 border-success/20"
      : score >= 40
        ? "text-warning bg-warning/10 border-warning/20"
        : "text-muted-foreground bg-muted border-border";

  return (
    <Badge variant="outline" className={cn("gap-1 text-xs font-semibold", color)}>
      <Sparkles className="h-3 w-3" />
      {score}
    </Badge>
  );
}

export function AdPixelBadges({ adPixels }: { adPixels?: { meta_pixel?: boolean; google_ads?: boolean } }) {
  if (!adPixels) return null;
  const badges: { label: string; active: boolean }[] = [
    { label: "Meta Ads", active: !!adPixels.meta_pixel },
    { label: "Google Ads", active: !!adPixels.google_ads },
  ];
  const activeBadges = badges.filter((b) => b.active);
  if (activeBadges.length === 0) return null;

  return (
    <>
      {activeBadges.map((badge) => (
        <Badge
          key={badge.label}
          variant="outline"
          className="text-xs text-primary bg-primary/10 border-primary/20 gap-1"
        >
          <Megaphone className="h-3 w-3" />
          {badge.label}
        </Badge>
      ))}
    </>
  );
}
