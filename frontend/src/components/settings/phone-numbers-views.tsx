"use client";

import {
  Bot,
  Check,
  Loader2,
  MessageSquare,
  Mic,
  Pencil,
  Phone,
  Plus,
  RefreshCw,
  Search,
  Trash2,
} from "lucide-react";
import { useState } from "react";

import {
  CampaignPicker,
  LeadSourcePicker,
  sourceTypeLabel,
} from "@/components/lead-sources/source-pickers";
import { InboundCallingDialog } from "@/components/settings/inbound-calling-dialog";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
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
import type { PhoneNumberSearchResult, PhoneNumberUpdateRequest } from "@/lib/api/phone-numbers";
import { formatPhoneNumber } from "@/lib/utils/phone";
import type { PhoneNumber } from "@/types";

export type PhoneNumbersTableVariant = "section" | "page";

const COUNTRIES = [
  { code: "US", name: "United States" },
  { code: "CA", name: "Canada" },
  { code: "GB", name: "United Kingdom" },
  { code: "AU", name: "Australia" },
];

export function SyncFromTelnyxButton({
  variant,
  isSyncing,
  onSync,
}: {
  variant: PhoneNumbersTableVariant;
  isSyncing: boolean;
  onSync: () => void;
}) {
  return (
    <Button
      variant={variant === "section" ? "outline" : "default"}
      size={variant === "section" ? "sm" : "default"}
      onClick={onSync}
      disabled={isSyncing}
    >
      {isSyncing ? (
        <Loader2 className="mr-2 size-4 animate-spin" />
      ) : (
        <RefreshCw className="mr-2 size-4" />
      )}
      Sync from Telnyx
    </Button>
  );
}

export function ReleaseNumberDialog({
  number,
  trigger,
  onRelease,
}: {
  number: PhoneNumber;
  trigger: React.ReactNode;
  onRelease: (phoneNumberId: string) => void;
}) {
  return (
    <AlertDialog>
      <AlertDialogTrigger asChild>{trigger}</AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Release Phone Number</AlertDialogTitle>
          <AlertDialogDescription>
            Are you sure you want to release {formatPhoneNumber(number.phone_number)}? This action
            cannot be undone and you may not be able to get this number back.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>Cancel</AlertDialogCancel>
          <AlertDialogAction
            className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            onClick={() => onRelease(number.id)}
          >
            Release Number
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

function TrackingAttributionSummary({ number }: { number: PhoneNumber }) {
  if (!number.lead_source) {
    return <span className="text-xs text-muted-foreground">Unmapped</span>;
  }

  return (
    <div className="space-y-1">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="text-sm font-medium">{number.lead_source.name}</span>
        <Badge variant="outline" className="text-xs font-normal">
          {sourceTypeLabel(number.lead_source.source_type)}
        </Badge>
      </div>
      {number.lead_source_campaign && (
        <p className="text-xs text-muted-foreground">
          Campaign: {number.lead_source_campaign.name}
        </p>
      )}
    </div>
  );
}

export function TrackingAttributionDialog({
  workspaceId,
  number,
  trigger,
  isUpdating,
  onUpdate,
}: {
  workspaceId: string;
  number: PhoneNumber;
  trigger: React.ReactNode;
  isUpdating: boolean;
  onUpdate: (phoneNumberId: string, data: PhoneNumberUpdateRequest) => Promise<PhoneNumber>;
}) {
  const [open, setOpen] = useState(false);
  const [leadSourceId, setLeadSourceId] = useState<string | undefined>(
    number.lead_source_id ?? undefined,
  );
  const [campaignId, setCampaignId] = useState<string | undefined>(
    number.lead_source_campaign_id ?? undefined,
  );
  const [trackingLabel, setTrackingLabel] = useState(number.tracking_label ?? "");

  const resetForm = () => {
    setLeadSourceId(number.lead_source_id ?? undefined);
    setCampaignId(number.lead_source_campaign_id ?? undefined);
    setTrackingLabel(number.tracking_label ?? "");
  };

  const handleOpenChange = (nextOpen: boolean) => {
    if (nextOpen) resetForm();
    setOpen(nextOpen);
  };

  const handleSave = async () => {
    try {
      await onUpdate(number.id, {
        lead_source_id: leadSourceId ?? null,
        lead_source_campaign_id: campaignId ?? null,
        tracking_label: trackingLabel.trim() || null,
      });
      setOpen(false);
    } catch {
      // The mutation displays the API error and keeps the form open for retry.
    }
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogTrigger asChild>{trigger}</DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Edit Call Tracking</DialogTitle>
          <DialogDescription>
            Attribute inbound calls to the source and optional campaign promoted with{" "}
            {formatPhoneNumber(number.phone_number)}.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4 py-2">
          <div className="space-y-2">
            <Label htmlFor={`tracking-label-${number.id}`}>Tracking label</Label>
            <Input
              id={`tracking-label-${number.id}`}
              value={trackingLabel}
              onChange={(event) => setTrackingLabel(event.target.value)}
              placeholder="e.g. Westside truck wrap"
              maxLength={120}
            />
            <p className="text-xs text-muted-foreground">
              Use a label that identifies where this number appears.
            </p>
          </div>
          <div className="space-y-2">
            <Label htmlFor={`lead-source-${number.id}`}>Lead source</Label>
            <LeadSourcePicker
              id={`lead-source-${number.id}`}
              workspaceId={workspaceId}
              value={leadSourceId}
              allowClear
              onClear={() => {
                setLeadSourceId(undefined);
                setCampaignId(undefined);
              }}
              onChange={(sourceId) => {
                setLeadSourceId(sourceId);
                setCampaignId(undefined);
              }}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor={`lead-campaign-${number.id}`}>Campaign</Label>
            <CampaignPicker
              id={`lead-campaign-${number.id}`}
              workspaceId={workspaceId}
              leadSourceId={leadSourceId}
              value={campaignId}
              allowClear
              onClear={() => setCampaignId(undefined)}
              onChange={setCampaignId}
            />
          </div>
        </div>
        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            onClick={() => setOpen(false)}
            disabled={isUpdating}
          >
            Cancel
          </Button>
          <Button
            type="button"
            onClick={() => void handleSave()}
            disabled={isUpdating || !workspaceId}
          >
            {isUpdating && <Loader2 className="mr-2 size-4 animate-spin" />}
            Save mapping
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function SearchNumbersForm({
  variant,
  country,
  onCountryChange,
  areaCode,
  onAreaCodeChange,
  isSearching,
  onSubmit,
}: {
  variant: PhoneNumbersTableVariant;
  country: string;
  onCountryChange: (country: string) => void;
  areaCode: string;
  onAreaCodeChange: (areaCode: string) => void;
  isSearching: boolean;
  onSubmit: (event: React.FormEvent) => void;
}) {
  return (
    <form onSubmit={onSubmit} className="flex gap-3">
      <div className={variant === "section" ? "w-40" : "w-48"}>
        <Label htmlFor="country" className="sr-only">
          Country
        </Label>
        <Select value={country} onValueChange={onCountryChange}>
          <SelectTrigger id="country">
            <SelectValue placeholder="Country" />
          </SelectTrigger>
          <SelectContent>
            {COUNTRIES.map((c) => (
              <SelectItem key={c.code} value={c.code}>
                {c.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <div className={variant === "section" ? "flex-1" : "flex-1 max-w-xs"}>
        <Label htmlFor="areaCode" className="sr-only">
          Area Code
        </Label>
        <Input
          id="areaCode"
          placeholder="Area code (optional, e.g. 415)"
          value={areaCode}
          onChange={(e) => onAreaCodeChange(e.target.value)}
          maxLength={3}
        />
      </div>
      <Button type="submit" disabled={isSearching}>
        {isSearching ? (
          <Loader2 className="mr-2 size-4 animate-spin" />
        ) : (
          <Search className="mr-2 size-4" />
        )}
        Search
      </Button>
    </form>
  );
}

export function OwnedNumbersContent({
  variant,
  workspaceId,
  phoneNumbers,
  isLoading,
  hasError,
  isUpdating,
  onUpdate,
  onRelease,
}: {
  variant: PhoneNumbersTableVariant;
  workspaceId: string;
  phoneNumbers: PhoneNumber[];
  isLoading: boolean;
  hasError: boolean;
  isUpdating: boolean;
  onUpdate: (phoneNumberId: string, data: PhoneNumberUpdateRequest) => Promise<PhoneNumber>;
  onRelease: (phoneNumberId: string) => void;
}) {
  if (isLoading) {
    return <PageLoadingState className={variant === "section" ? "min-h-0 py-8" : undefined} />;
  }

  if (hasError) {
    return (
      <PageErrorState
        message="Failed to load phone numbers"
        className={variant === "section" ? "min-h-0 py-8" : undefined}
      />
    );
  }

  if (phoneNumbers.length === 0) {
    if (variant === "section") {
      return (
        <div className="text-center py-8 border rounded-lg border-dashed">
          <Phone className="size-8 mx-auto text-muted-foreground mb-2" />
          <p className="text-sm text-muted-foreground">
            No phone numbers yet. Search and purchase one below.
          </p>
        </div>
      );
    }
    return (
      <PageEmptyState
        icon={<Phone className="size-12" />}
        title="No phone numbers yet"
        description="Search and purchase a number below, or sync existing numbers from your Telnyx account."
        className="border rounded-lg border-dashed"
      />
    );
  }

  if (variant === "section") {
    return (
      <div className="space-y-2">
        {phoneNumbers.map((number) => (
          <div
            key={number.id}
            className="flex items-center justify-between gap-4 rounded-lg border p-3"
          >
            <div className="flex min-w-0 items-center gap-3">
              <div className="flex size-8 shrink-0 items-center justify-center rounded-full bg-green-500/10">
                <Phone className="size-4 text-green-500" />
              </div>
              <div className="min-w-0 space-y-1">
                <p className="font-medium">{formatPhoneNumber(number.phone_number)}</p>
                {(number.tracking_label || number.friendly_name) && (
                  <p className="truncate text-xs text-muted-foreground">
                    {number.tracking_label || number.friendly_name}
                  </p>
                )}
                <TrackingAttributionSummary number={number} />
                {number.inbound_ai_enabled && <Badge className="md:hidden">AI answers</Badge>}
              </div>
            </div>
            <div className="flex shrink-0 items-center gap-2">
              <div className="hidden items-center gap-1.5 md:flex">
                {number.sms_enabled && (
                  <Badge
                    variant="outline"
                    className="bg-blue-500/10 text-blue-500 border-blue-500/20"
                  >
                    <MessageSquare className="size-3 mr-1" />
                    SMS
                  </Badge>
                )}
                {number.voice_enabled && (
                  <Badge
                    variant="outline"
                    className="bg-purple-500/10 text-purple-500 border-purple-500/20"
                  >
                    <Mic className="size-3 mr-1" />
                    Voice
                  </Badge>
                )}
              </div>
              <InboundCallingDialog
                workspaceId={workspaceId}
                number={number}
                trigger={
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    aria-label={`Configure AI inbound answering for ${formatPhoneNumber(number.phone_number)}`}
                  >
                    <Bot className="size-4" />
                  </Button>
                }
              />
              <TrackingAttributionDialog
                workspaceId={workspaceId}
                number={number}
                isUpdating={isUpdating}
                onUpdate={onUpdate}
                trigger={
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    aria-label={`Edit call tracking for ${formatPhoneNumber(number.phone_number)}`}
                  >
                    <Pencil className="size-4" />
                  </Button>
                }
              />
              <ReleaseNumberDialog
                number={number}
                onRelease={onRelease}
                trigger={
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    aria-label={`Release ${formatPhoneNumber(number.phone_number)}`}
                    className="text-destructive hover:text-destructive hover:bg-destructive/10"
                  >
                    <Trash2 className="size-4" />
                  </Button>
                }
              />
            </div>
          </div>
        ))}
      </div>
    );
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Phone Number</TableHead>
          <TableHead>Tracking Label</TableHead>
          <TableHead>Attribution</TableHead>
          <TableHead>Capabilities</TableHead>
          <TableHead>Status</TableHead>
          <TableHead className="text-right">Actions</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {phoneNumbers.map((number) => (
          <TableRow key={number.id}>
            <TableCell>
              <p className="font-medium">{formatPhoneNumber(number.phone_number)}</p>
              {number.friendly_name && (
                <p className="text-xs text-muted-foreground">{number.friendly_name}</p>
              )}
            </TableCell>
            <TableCell>
              {number.tracking_label || <span className="text-muted-foreground">—</span>}
            </TableCell>
            <TableCell>
              <TrackingAttributionSummary number={number} />
            </TableCell>
            <TableCell>
              <div className="flex items-center gap-1.5">
                {number.sms_enabled && (
                  <Badge
                    variant="outline"
                    className="bg-blue-500/10 text-blue-600 border-blue-500/20"
                  >
                    <MessageSquare className="size-3 mr-1" />
                    SMS
                  </Badge>
                )}
                {number.voice_enabled && (
                  <Badge
                    variant="outline"
                    className="bg-purple-500/10 text-purple-600 border-purple-500/20"
                  >
                    <Mic className="size-3 mr-1" />
                    Voice
                  </Badge>
                )}
              </div>
            </TableCell>
            <TableCell>
              <div className="flex flex-wrap gap-1.5">
                {number.is_active ? (
                  <Badge className="bg-green-500/10 text-green-600 border-green-500/20">
                    Active
                  </Badge>
                ) : (
                  <Badge variant="secondary">Inactive</Badge>
                )}
                {number.inbound_ai_enabled && <Badge>AI answers</Badge>}
              </div>
            </TableCell>
            <TableCell className="text-right">
              <div className="flex justify-end gap-1">
                <InboundCallingDialog
                  workspaceId={workspaceId}
                  number={number}
                  trigger={
                    <Button variant="ghost" size="sm">
                      <Bot className="mr-2 size-4" />
                      AI calls
                    </Button>
                  }
                />
                <TrackingAttributionDialog
                  workspaceId={workspaceId}
                  number={number}
                  isUpdating={isUpdating}
                  onUpdate={onUpdate}
                  trigger={
                    <Button variant="ghost" size="sm">
                      <Pencil className="mr-2 size-4" />
                      Edit tracking
                    </Button>
                  }
                />
                <ReleaseNumberDialog
                  number={number}
                  onRelease={onRelease}
                  trigger={
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      aria-label={`Release ${formatPhoneNumber(number.phone_number)}`}
                      className="text-destructive hover:text-destructive hover:bg-destructive/10"
                    >
                      <Trash2 className="size-4" />
                    </Button>
                  }
                />
              </div>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

export function SearchResultsContent({
  variant,
  hasSearched,
  searchResults,
  isPurchasing,
  onPurchase,
}: {
  variant: PhoneNumbersTableVariant;
  hasSearched: boolean;
  searchResults: PhoneNumberSearchResult[];
  isPurchasing: boolean;
  onPurchase: (phoneNumber: string) => void;
}) {
  if (!hasSearched) return null;

  return (
    <div className={variant === "section" ? "space-y-2" : "space-y-4"}>
      {searchResults.length === 0 ? (
        <div
          className={`text-center ${variant === "section" ? "py-6" : "py-8"} border rounded-lg border-dashed`}
        >
          <p
            className={
              variant === "section" ? "text-sm text-muted-foreground" : "text-muted-foreground"
            }
          >
            No available numbers found. Try a different area code.
          </p>
        </div>
      ) : (
        <>
          <p className="text-sm text-muted-foreground">
            {searchResults.length} number(s) available
          </p>
          <div
            className={
              variant === "section"
                ? "space-y-2 max-h-64 overflow-y-auto"
                : "grid gap-3 md:grid-cols-2"
            }
          >
            {searchResults.map((result) => (
              <div
                key={result.id}
                className={`flex items-center justify-between ${variant === "section" ? "p-3" : "p-4"} rounded-lg border bg-muted/30`}
              >
                <div className="flex items-center gap-3">
                  <div
                    className={`flex ${variant === "section" ? "size-8" : "size-10"} items-center justify-center rounded-full bg-primary/10`}
                  >
                    <Phone
                      className={`${variant === "section" ? "size-4" : "size-5"} text-primary`}
                    />
                  </div>
                  <div>
                    <p className="font-medium">{formatPhoneNumber(result.phone_number)}</p>
                    <div
                      className={`flex items-center ${variant === "section" ? "gap-1.5" : "gap-2"} mt-0.5`}
                    >
                      {result.capabilities?.sms && (
                        <span className="text-xs text-muted-foreground flex items-center gap-0.5">
                          <Check className="size-3 text-green-500" />
                          SMS
                        </span>
                      )}
                      {result.capabilities?.voice && (
                        <span className="text-xs text-muted-foreground flex items-center gap-0.5">
                          <Check className="size-3 text-green-500" />
                          Voice
                        </span>
                      )}
                      {result.capabilities?.mms && (
                        <span className="text-xs text-muted-foreground flex items-center gap-0.5">
                          <Check className="size-3 text-green-500" />
                          MMS
                        </span>
                      )}
                    </div>
                  </div>
                </div>
                <Button
                  size="sm"
                  onClick={() => onPurchase(result.phone_number)}
                  disabled={isPurchasing}
                >
                  {isPurchasing ? (
                    <Loader2 className="mr-2 size-4 animate-spin" />
                  ) : (
                    <Plus className="mr-2 size-4" />
                  )}
                  Purchase
                </Button>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
