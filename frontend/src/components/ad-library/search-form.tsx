"use client";

import { Loader2, Search } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import type { AdLibrarySearchRequest } from "@/lib/api/ad-library";

export interface AdLibrarySearchValues {
  platform: "meta" | "google";
  country: string;
  searchTerms: string;
  pageName: string;
  /** ICP toggles — surface the "consistent but not testing" signal in the UI. */
  longRunner: boolean;
  lowDiversity: boolean;
  noTesting: boolean;
}

const DEFAULT_VALUES: AdLibrarySearchValues = {
  platform: "meta",
  country: "US",
  searchTerms: "",
  pageName: "",
  longRunner: true,
  lowDiversity: true,
  noTesting: true,
};

/** Translate the ICP toggles into threshold overrides for the search request. */
export function toSearchRequest(values: AdLibrarySearchValues): AdLibrarySearchRequest {
  const icp: NonNullable<AdLibrarySearchRequest["icp_thresholds"]> = {};
  if (values.longRunner) icp.min_longest_running_days = 60;
  if (values.lowDiversity) icp.max_distinct_creatives = 6;
  if (values.noTesting) icp.max_creative_refresh_rate = 2;

  return {
    platform: values.platform,
    country: values.country.toUpperCase().slice(0, 2),
    search_terms: values.searchTerms.trim() || null,
    page_name: values.pageName.trim() || null,
    sort_by: "longest_running",
    max_results: 50,
    use_thirdparty_fallback: false,
    icp_thresholds: Object.keys(icp).length > 0 ? icp : null,
  };
}

interface SearchFormProps {
  onSubmit: (values: AdLibrarySearchValues) => void;
  isSubmitting?: boolean;
}

export function AdLibrarySearchForm({ onSubmit, isSubmitting = false }: SearchFormProps) {
  const [values, setValues] = useState<AdLibrarySearchValues>(DEFAULT_VALUES);

  const canSubmit =
    values.searchTerms.trim().length > 0 || values.pageName.trim().length > 0;

  function update<K extends keyof AdLibrarySearchValues>(
    key: K,
    value: AdLibrarySearchValues[K],
  ) {
    setValues((prev) => ({ ...prev, [key]: value }));
  }

  return (
    <Card>
      <CardContent className="space-y-4 pt-6">
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-2">
            <Label htmlFor="ad-search-terms">Keyword</Label>
            <Input
              id="ad-search-terms"
              placeholder="e.g. roofing contractors"
              value={values.searchTerms}
              onChange={(e) => update("searchTerms", e.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="ad-page-name">Or a specific page</Label>
            <Input
              id="ad-page-name"
              placeholder="e.g. Acme Roofing"
              value={values.pageName}
              onChange={(e) => update("pageName", e.target.value)}
            />
          </div>
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-2">
            <Label htmlFor="ad-platform">Platform</Label>
            <Select
              value={values.platform}
              onValueChange={(v) => update("platform", v as "meta" | "google")}
            >
              <SelectTrigger id="ad-platform">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="meta">Meta Ad Library</SelectItem>
                <SelectItem value="google">Google Ads Transparency</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-2">
            <Label htmlFor="ad-country">Country</Label>
            <Input
              id="ad-country"
              maxLength={2}
              value={values.country}
              onChange={(e) => update("country", e.target.value)}
            />
          </div>
        </div>

        <div className="space-y-3 rounded-md border p-4">
          <p className="text-sm font-medium">
            Find advertisers who run consistently but don&apos;t test creatives
          </p>
          <IcpToggle
            id="icp-long-runner"
            label="Long-runner"
            description="Same ad running 60+ days"
            checked={values.longRunner}
            onChange={(v) => update("longRunner", v)}
          />
          <IcpToggle
            id="icp-low-diversity"
            label="Low creative diversity"
            description="Few distinct creatives — excludes prolific testers"
            checked={values.lowDiversity}
            onChange={(v) => update("lowDiversity", v)}
          />
          <IcpToggle
            id="icp-no-testing"
            label="No testing"
            description="Rarely introduces new creatives"
            checked={values.noTesting}
            onChange={(v) => update("noTesting", v)}
          />
        </div>

        <Button
          className="w-full"
          disabled={!canSubmit || isSubmitting}
          onClick={() => onSubmit(values)}
        >
          {isSubmitting ? (
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          ) : (
            <Search className="mr-2 h-4 w-4" />
          )}
          Search ad library
        </Button>
      </CardContent>
    </Card>
  );
}

interface IcpToggleProps {
  id: string;
  label: string;
  description: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
}

function IcpToggle({ id, label, description, checked, onChange }: IcpToggleProps) {
  return (
    <div className="flex items-center justify-between gap-4">
      <div className="space-y-0.5">
        <Label htmlFor={id}>{label}</Label>
        <p className="text-xs text-muted-foreground">{description}</p>
      </div>
      <Switch id={id} checked={checked} onCheckedChange={onChange} />
    </div>
  );
}
