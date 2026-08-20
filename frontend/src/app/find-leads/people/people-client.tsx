"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Mail, Phone, Search, Sparkles } from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { ProviderNotConfiguredBanner } from "@/components/shared/provider-not-configured-banner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { PageEmptyState, PageErrorState, PageLoadingState } from "@/components/ui/page-state";
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
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import { apiGet } from "@/lib/api";
import {
  peopleApi,
  peopleQueryOptions,
  type PeopleSearchRequest,
  type PersonResult,
} from "@/lib/api/people";
import { queryKeys } from "@/lib/query-keys";
import {
  getApiErrorMessage,
  isProviderConfigurationError,
  shouldThrowProviderError,
} from "@/lib/utils/errors";

const SIGNAL_CHIPS: { value: string; label: string }[] = [
  { value: "running_ads", label: "Running ads" },
  { value: "ad_tech", label: "Ad tech installed" },
  { value: "hiring", label: "Hiring" },
  { value: "funding", label: "Funding" },
];

const SIGNAL_LABELS: Record<string, string> = Object.fromEntries(
  SIGNAL_CHIPS.map((c) => [c.value, c.label]),
);

interface MissionOption {
  id: string;
  name: string;
}

const EMPTY_REQUEST: PeopleSearchRequest = {
  page: 1,
  page_size: 25,
  min_score: 0,
  min_signal_strength: 0,
};

export function PeopleSearchClient() {
  const workspaceId = useWorkspaceId();
  const queryClient = useQueryClient();

  // Draft filters (form) vs. committed request (what we actually query).
  const [keywords, setKeywords] = useState("");
  const [title, setTitle] = useState("");
  const [location, setLocation] = useState("");
  const [hasEmailOnly, setHasEmailOnly] = useState(false);
  const [signalTypes, setSignalTypes] = useState<Set<string>>(new Set());
  const [request, setRequest] = useState<PeopleSearchRequest | null>(null);

  // Discovery + selection state.
  const [discoveryInput, setDiscoveryInput] = useState("");
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [missionId, setMissionId] = useState<string>("");
  const [providerNotConfigured, setProviderNotConfigured] = useState(false);

  const toggleSignal = (value: string) => {
    setSignalTypes((prev) => {
      const next = new Set(prev);
      if (next.has(value)) next.delete(value);
      else next.add(value);
      return next;
    });
  };

  const toggleSelect = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const runSearch = () => {
    setRequest({
      ...EMPTY_REQUEST,
      keywords: keywords.trim() || null,
      title: title.trim() || null,
      location: location.trim() || null,
      has_email: hasEmailOnly ? true : null,
      signal_types: Array.from(signalTypes),
    });
  };

  const searchQuery = useQuery({
    ...peopleQueryOptions.search(workspaceId ?? "", request ?? EMPTY_REQUEST),
    enabled: Boolean(workspaceId) && request !== null,
  });
  const people = searchQuery.data?.items ?? [];

  const missionsQuery = useQuery({
    queryKey: queryKeys.people.missions(workspaceId ?? ""),
    queryFn: () =>
      apiGet<{ items: MissionOption[] }>(`/api/v1/workspaces/${workspaceId}/outbound-missions`),
    enabled: Boolean(workspaceId),
  });
  const missions = missionsQuery.data?.items ?? [];

  const discoveryMutation = useMutation({
    mutationFn: () => {
      if (!workspaceId) throw new Error("No workspace");
      const value = discoveryInput.trim();
      const looksLikeDomain = value.includes(".") && !value.includes(" ");
      return peopleApi.launchDiscovery(workspaceId, {
        domain: looksLikeDomain ? value : null,
        query: looksLikeDomain ? null : value || null,
        domains: [],
        max_results: 25,
      });
    },
    throwOnError: shouldThrowProviderError,
    onSuccess: () => {
      setProviderNotConfigured(false);
      toast.success("People crawl started — results appear as enrichment runs.");
      setDiscoveryInput("");
    },
    onError: (error) => {
      if (isProviderConfigurationError(error)) {
        setProviderNotConfigured(true);
        return;
      }
      setProviderNotConfigured(false);
      toast.error(getApiErrorMessage(error, "Couldn't start the people crawl"));
    },
  });

  const revealMutation = useMutation({
    mutationFn: (prospectId: string) => {
      if (!workspaceId) throw new Error("No workspace");
      return peopleApi.revealEmail(workspaceId, prospectId);
    },
    onSuccess: (result) => {
      if (result.email) {
        toast.success(`${result.email} (${result.verification_status})`);
      } else {
        toast.message("No email could be inferred for this person.");
      }
      if (workspaceId && request) {
        queryClient.invalidateQueries({
          queryKey: queryKeys.people.search(workspaceId, {
            ...request,
          } as Record<string, unknown>),
        });
      }
    },
    onError: (error) => toast.error(getApiErrorMessage(error, "Couldn't reveal email")),
  });

  const revealPhoneMutation = useMutation({
    mutationFn: (prospectId: string) => {
      if (!workspaceId) throw new Error("No workspace");
      return peopleApi.revealPhone(workspaceId, prospectId);
    },
    onSuccess: (result) => {
      if (result.phone_number) {
        toast.success(`${result.phone_number} (business line, ${result.source})`);
      } else {
        toast.message("No business line could be found on the company site.");
      }
      if (workspaceId && request) {
        queryClient.invalidateQueries({
          queryKey: queryKeys.people.search(workspaceId, {
            ...request,
          } as Record<string, unknown>),
        });
      }
    },
    onError: (error) => toast.error(getApiErrorMessage(error, "Couldn't reveal phone")),
  });

  const addToMissionMutation = useMutation({
    mutationFn: () => {
      if (!workspaceId) throw new Error("No workspace");
      if (!missionId) throw new Error("Pick a mission first");
      return peopleApi.addToMission(workspaceId, {
        mission_id: missionId,
        prospect_ids: Array.from(selectedIds),
      });
    },
    onSuccess: (result) => {
      toast.success(`Added ${result.added}, skipped ${result.skipped}`);
      setSelectedIds(new Set());
    },
    onError: (error) =>
      toast.error(getApiErrorMessage(error, "Couldn't add people to the mission")),
  });

  const total = searchQuery.data?.total ?? 0;
  const hasFilters = useMemo(
    () => Boolean(keywords || title || location || hasEmailOnly || signalTypes.size),
    [keywords, title, location, hasEmailOnly, signalTypes],
  );

  return (
    <div className="mx-auto w-full max-w-5xl space-y-6 p-4 sm:p-6">
      <div className="space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight">People Search</h1>
        <p className="text-sm text-muted-foreground">
          Find named decision-makers at companies, see their buying signals (already running ads,
          ad-tech installed), reveal verified emails, and push them into an outbound mission.
        </p>
      </div>

      {providerNotConfigured ? (
        <ProviderNotConfiguredBanner
          title="People discovery needs a search provider"
          description="Connect the people-search provider in Settings, then retry discovery."
          restrictedDescription="Ask a workspace owner or admin to connect the people-search provider."
          settingsLabel="Set up people search"
        />
      ) : null}

      {/* Discovery launcher */}
      <Card>
        <CardContent className="flex flex-col gap-3 pt-6 sm:flex-row sm:items-end">
          <div className="flex-1 space-y-1.5">
            <Label htmlFor="people-discovery">Crawl a company for people</Label>
            <Input
              id="people-discovery"
              placeholder="acme.com  —  or  —  roofing companies in Austin"
              value={discoveryInput}
              onChange={(e) => setDiscoveryInput(e.target.value)}
            />
          </div>
          <Button
            onClick={() => discoveryMutation.mutate()}
            disabled={discoveryMutation.isPending || !discoveryInput.trim()}
          >
            {discoveryMutation.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Sparkles className="h-4 w-4" />
            )}
            Find people
          </Button>
        </CardContent>
      </Card>

      {/* Filter panel */}
      <Card>
        <CardContent className="space-y-4 pt-6">
          <div className="grid gap-3 sm:grid-cols-3">
            <div className="space-y-1.5">
              <Label htmlFor="f-keywords">Keywords</Label>
              <Input
                id="f-keywords"
                placeholder="name, company…"
                value={keywords}
                onChange={(e) => setKeywords(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && runSearch()}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="f-title">Title / seniority</Label>
              <Input
                id="f-title"
                placeholder="Head of Marketing, CEO…"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && runSearch()}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="f-location">Location</Label>
              <Input
                id="f-location"
                placeholder="Austin, TX"
                value={location}
                onChange={(e) => setLocation(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && runSearch()}
              />
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm text-muted-foreground">Signals:</span>
            {SIGNAL_CHIPS.map((chip) => {
              const active = signalTypes.has(chip.value);
              return (
                <button
                  key={chip.value}
                  type="button"
                  onClick={() => toggleSignal(chip.value)}
                  className="focus:outline-none"
                >
                  <Badge variant={active ? "default" : "outline"}>{chip.label}</Badge>
                </button>
              );
            })}
          </div>

          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-2 text-sm">
              <Checkbox
                id="has-email-only"
                checked={hasEmailOnly}
                onCheckedChange={(v) => setHasEmailOnly(v === true)}
              />
              <Label htmlFor="has-email-only" className="font-normal">
                Has email only
              </Label>
            </div>
            <Button onClick={runSearch} disabled={!workspaceId}>
              <Search className="h-4 w-4" />
              Search people
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Bulk actions */}
      {selectedIds.size > 0 && (
        <Card>
          <CardContent className="flex flex-wrap items-center gap-3 pt-6">
            <span className="text-sm font-medium">{selectedIds.size} selected</span>
            <Select value={missionId} onValueChange={setMissionId}>
              <SelectTrigger className="w-64">
                <SelectValue placeholder="Add to mission…" />
              </SelectTrigger>
              <SelectContent>
                {missions.map((m) => (
                  <SelectItem key={m.id} value={m.id}>
                    {m.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Button
              onClick={() => addToMissionMutation.mutate()}
              disabled={!missionId || addToMissionMutation.isPending}
            >
              {addToMissionMutation.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
              Add to mission
            </Button>
          </CardContent>
        </Card>
      )}

      {/* Results */}
      <section className="space-y-3">
        {request === null ? (
          <PageEmptyState
            title="Search for people"
            description={
              hasFilters
                ? "Hit “Search people” to run your filters."
                : "Crawl a company above, or set filters and search across everyone you've discovered."
            }
          />
        ) : searchQuery.isLoading ? (
          <PageLoadingState message="Searching people…" />
        ) : searchQuery.isError ? (
          <PageErrorState message="Couldn't search people." onRetry={() => searchQuery.refetch()} />
        ) : people.length === 0 ? (
          <PageEmptyState
            title="No people match"
            description="Try loosening filters, or crawl more companies for people."
          />
        ) : (
          <>
            <p className="text-sm text-muted-foreground">
              {total} {total === 1 ? "person" : "people"}
            </p>
            <div className="rounded-md border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-10" />
                    <TableHead>Person</TableHead>
                    <TableHead>Company</TableHead>
                    <TableHead>Signals</TableHead>
                    <TableHead>Email</TableHead>
                    <TableHead>Phone</TableHead>
                    <TableHead className="text-right">Score</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {people.map((person) => (
                    <PersonRow
                      key={person.id}
                      person={person}
                      selected={selectedIds.has(person.id)}
                      onToggle={() => toggleSelect(person.id)}
                      onReveal={() => revealMutation.mutate(person.id)}
                      revealing={revealMutation.isPending && revealMutation.variables === person.id}
                      onRevealPhone={() => revealPhoneMutation.mutate(person.id)}
                      revealingPhone={
                        revealPhoneMutation.isPending && revealPhoneMutation.variables === person.id
                      }
                    />
                  ))}
                </TableBody>
              </Table>
            </div>
          </>
        )}
      </section>
    </div>
  );
}

function PersonRow({
  person,
  selected,
  onToggle,
  onReveal,
  revealing,
  onRevealPhone,
  revealingPhone,
}: {
  person: PersonResult;
  selected: boolean;
  onToggle: () => void;
  onReveal: () => void;
  revealing: boolean;
  onRevealPhone: () => void;
  revealingPhone: boolean;
}) {
  return (
    <TableRow data-state={selected ? "selected" : undefined}>
      <TableCell>
        <Checkbox checked={selected} onCheckedChange={onToggle} />
      </TableCell>
      <TableCell>
        <div className="font-medium">{person.full_name ?? "Unknown"}</div>
        {person.title && <div className="text-xs text-muted-foreground">{person.title}</div>}
        {person.location_label && (
          <div className="text-xs text-muted-foreground">{person.location_label}</div>
        )}
      </TableCell>
      <TableCell>
        <div className="text-sm">{person.company_name ?? person.website_host ?? "—"}</div>
      </TableCell>
      <TableCell>
        <div className="flex flex-wrap gap-1">
          {(person.signals ?? []).length === 0 ? (
            <span className="text-xs text-muted-foreground">—</span>
          ) : (
            (person.signals ?? []).map((signal) => (
              <Badge key={signal.id} variant="secondary" title={`strength ${signal.strength}`}>
                {SIGNAL_LABELS[signal.signal_type] ?? signal.signal_type}
              </Badge>
            ))
          )}
        </div>
      </TableCell>
      <TableCell>
        {person.has_email && person.email ? (
          <span className="text-sm">{person.email}</span>
        ) : (
          <Button size="sm" variant="outline" onClick={onReveal} disabled={revealing}>
            {revealing ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Mail className="h-3.5 w-3.5" />
            )}
            Reveal
          </Button>
        )}
      </TableCell>
      <TableCell>
        {person.has_phone && person.phone_number ? (
          <span className="text-sm" title="Business line">
            {person.phone_number}
          </span>
        ) : (
          <Button
            size="sm"
            variant="outline"
            onClick={onRevealPhone}
            disabled={revealingPhone}
            title="Scrape the company site for a business line"
          >
            {revealingPhone ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Phone className="h-3.5 w-3.5" />
            )}
            Reveal
          </Button>
        )}
      </TableCell>
      <TableCell className="text-right tabular-nums">{person.lead_score}</TableCell>
    </TableRow>
  );
}
