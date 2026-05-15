"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  Phone,
  Search,
  Loader2,
  MessageSquare,
  Mic,
  Trash2,
  RefreshCw,
  Plus,
  Check,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { formatPhoneNumber } from "@/lib/utils/phone";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
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
import { Separator } from "@/components/ui/separator";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  PageEmptyState,
  PageErrorState,
  PageLoadingState,
} from "@/components/ui/page-state";
import { useWorkspaceId } from "@/hooks/use-workspace-id";
import { queryKeys } from "@/lib/query-keys";
import {
  phoneNumbersApi,
  type PhoneNumberSearchResult,
} from "@/lib/api/phone-numbers";
import type { PhoneNumber } from "@/types";

const COUNTRIES = [
  { code: "US", name: "United States" },
  { code: "CA", name: "Canada" },
  { code: "GB", name: "United Kingdom" },
  { code: "AU", name: "Australia" },
];

export type PhoneNumbersTableVariant = "section" | "page";

export interface PhoneNumbersTableProps {
  variant: PhoneNumbersTableVariant;
}

export function PhoneNumbersTable({ variant }: PhoneNumbersTableProps) {
  const workspaceId = useWorkspaceId();
  const queryClient = useQueryClient();

  // Search state
  const [country, setCountry] = useState("US");
  const [areaCode, setAreaCode] = useState("");
  const [searchResults, setSearchResults] = useState<PhoneNumberSearchResult[]>(
    []
  );
  const [hasSearched, setHasSearched] = useState(false);

  // Fetch current phone numbers
  const {
    data: phoneNumbersData,
    isPending: isLoadingNumbers,
    error: numbersError,
  } = useQuery({
    queryKey: queryKeys.phoneNumbers.activeOnlyFalse(workspaceId ?? ""),
    queryFn: () => {
      if (!workspaceId) throw new Error("Workspace not loaded");
      return phoneNumbersApi.list(workspaceId, { active_only: false });
    },
    enabled: !!workspaceId,
  });

  // Search for available numbers
  const searchMutation = useMutation({
    mutationFn: () => {
      if (!workspaceId) throw new Error("Workspace not loaded");
      return phoneNumbersApi.search(workspaceId, {
        country,
        area_code: areaCode || undefined,
        limit: 10,
      });
    },
    onSuccess: (data) => {
      setSearchResults(data);
      setHasSearched(true);
      if (data.length === 0) {
        toast.info("No numbers found matching your criteria");
      }
    },
    onError: (error: Error) => {
      toast.error(error.message || "Failed to search for numbers");
      setSearchResults([]);
      setHasSearched(true);
    },
  });

  // Purchase a phone number
  const purchaseMutation = useMutation({
    mutationFn: (phoneNumber: string) => {
      if (!workspaceId) throw new Error("Workspace not loaded");
      return phoneNumbersApi.purchase(workspaceId, {
        phone_number: phoneNumber,
      });
    },
    onSuccess: (data) => {
      toast.success(`Successfully purchased ${data.phone_number}`);
      queryClient.invalidateQueries({
        queryKey: queryKeys.phoneNumbers.bare(workspaceId ?? ""),
      });
      setSearchResults((prev) =>
        prev.filter((r) => r.phone_number !== data.phone_number)
      );
    },
    onError: (error: Error) => {
      toast.error(error.message || "Failed to purchase number");
    },
  });

  // Release a phone number
  const releaseMutation = useMutation({
    mutationFn: (phoneNumberId: string) => {
      if (!workspaceId) throw new Error("Workspace not loaded");
      return phoneNumbersApi.release(workspaceId, phoneNumberId);
    },
    onSuccess: () => {
      toast.success("Phone number released successfully");
      queryClient.invalidateQueries({
        queryKey: queryKeys.phoneNumbers.bare(workspaceId ?? ""),
      });
    },
    onError: (error: Error) => {
      toast.error(error.message || "Failed to release number");
    },
  });

  // Sync phone numbers from Telnyx
  const syncMutation = useMutation({
    mutationFn: () => {
      if (!workspaceId) throw new Error("Workspace not loaded");
      return phoneNumbersApi.sync(workspaceId);
    },
    onSuccess: (data) => {
      if (data.synced > 0) {
        toast.success(`Synced ${data.synced} phone number(s) from Telnyx`);
      } else {
        toast.info("No new phone numbers to sync");
      }
      queryClient.invalidateQueries({
        queryKey: queryKeys.phoneNumbers.bare(workspaceId ?? ""),
      });
    },
    onError: (error: Error) => {
      toast.error(error.message || "Failed to sync phone numbers");
    },
  });

  const phoneNumbers = Array.isArray(phoneNumbersData?.items)
    ? phoneNumbersData.items
    : [];

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    searchMutation.mutate();
  };

  const renderReleaseDialog = (number: PhoneNumber, trigger: React.ReactNode) => (
    <AlertDialog>
      <AlertDialogTrigger asChild>{trigger}</AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Release Phone Number</AlertDialogTitle>
          <AlertDialogDescription>
            Are you sure you want to release{" "}
            {formatPhoneNumber(number.phone_number)}? This action cannot be
            undone and you may not be able to get this number back.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>Cancel</AlertDialogCancel>
          <AlertDialogAction
            className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            onClick={() => releaseMutation.mutate(number.id)}
          >
            Release Number
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );

  const syncButton = (
    <Button
      variant={variant === "section" ? "outline" : "default"}
      size={variant === "section" ? "sm" : "default"}
      onClick={() => syncMutation.mutate()}
      disabled={syncMutation.isPending}
    >
      {syncMutation.isPending ? (
        <Loader2 className="mr-2 size-4 animate-spin" />
      ) : (
        <RefreshCw className="mr-2 size-4" />
      )}
      Sync from Telnyx
    </Button>
  );

  const searchForm = (
    <form onSubmit={handleSearch} className="flex gap-3">
      <div className={variant === "section" ? "w-40" : "w-48"}>
        <Label htmlFor="country" className="sr-only">
          Country
        </Label>
        <Select value={country} onValueChange={setCountry}>
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
          onChange={(e) => setAreaCode(e.target.value)}
          maxLength={3}
        />
      </div>
      <Button type="submit" disabled={searchMutation.isPending}>
        {searchMutation.isPending ? (
          <Loader2 className="mr-2 size-4 animate-spin" />
        ) : (
          <Search className="mr-2 size-4" />
        )}
        Search
      </Button>
    </form>
  );

  // ──────────────────────────────────────────────────────────────────────
  // Owned phone numbers list
  // ──────────────────────────────────────────────────────────────────────

  const ownedNumbersContent = (() => {
    if (isLoadingNumbers) {
      return (
        <PageLoadingState
          className={variant === "section" ? "min-h-0 py-8" : undefined}
        />
      );
    }

    if (numbersError) {
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
          {phoneNumbers.map((number: PhoneNumber) => (
            <div
              key={number.id}
              className="flex items-center justify-between p-3 rounded-lg border"
            >
              <div className="flex items-center gap-3">
                <div className="flex size-8 items-center justify-center rounded-full bg-green-500/10">
                  <Phone className="size-4 text-green-500" />
                </div>
                <div>
                  <p className="font-medium">
                    {formatPhoneNumber(number.phone_number)}
                  </p>
                  <div className="flex items-center gap-2 mt-0.5">
                    {number.friendly_name && (
                      <span className="text-xs text-muted-foreground">
                        {number.friendly_name}
                      </span>
                    )}
                  </div>
                </div>
              </div>
              <div className="flex items-center gap-3">
                <div className="flex items-center gap-1.5">
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
                {number.assigned_agent_id && (
                  <Badge variant="secondary">Assigned to Agent</Badge>
                )}
                {renderReleaseDialog(
                  number,
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    className="text-destructive hover:text-destructive hover:bg-destructive/10"
                  >
                    <Trash2 className="size-4" />
                  </Button>
                )}
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
            <TableHead>Label</TableHead>
            <TableHead>Capabilities</TableHead>
            <TableHead>Status</TableHead>
            <TableHead className="text-right">Actions</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {phoneNumbers.map((number: PhoneNumber) => (
            <TableRow key={number.id}>
              <TableCell className="font-medium">
                {formatPhoneNumber(number.phone_number)}
              </TableCell>
              <TableCell>
                {number.friendly_name || (
                  <span className="text-muted-foreground">-</span>
                )}
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
                {number.is_active ? (
                  <Badge className="bg-green-500/10 text-green-600 border-green-500/20">
                    Active
                  </Badge>
                ) : (
                  <Badge variant="secondary">Inactive</Badge>
                )}
              </TableCell>
              <TableCell className="text-right">
                {renderReleaseDialog(
                  number,
                  <Button
                    variant="ghost"
                    size="sm"
                    className="text-destructive hover:text-destructive hover:bg-destructive/10"
                  >
                    <Trash2 className="size-4" />
                  </Button>
                )}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    );
  })();

  // ──────────────────────────────────────────────────────────────────────
  // Search results
  // ──────────────────────────────────────────────────────────────────────

  const searchResultsContent = hasSearched ? (
    <div className={variant === "section" ? "space-y-2" : "space-y-4"}>
      {searchResults.length === 0 ? (
        <div
          className={`text-center ${variant === "section" ? "py-6" : "py-8"} border rounded-lg border-dashed`}
        >
          <p
            className={
              variant === "section"
                ? "text-sm text-muted-foreground"
                : "text-muted-foreground"
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
                    <p className="font-medium">
                      {formatPhoneNumber(result.phone_number)}
                    </p>
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
                  onClick={() =>
                    purchaseMutation.mutate(result.phone_number)
                  }
                  disabled={purchaseMutation.isPending}
                >
                  {purchaseMutation.isPending ? (
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
  ) : null;

  // ──────────────────────────────────────────────────────────────────────
  // Variant render
  // ──────────────────────────────────────────────────────────────────────

  if (variant === "section") {
    return (
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="flex size-10 items-center justify-center rounded-lg bg-green-500/10">
                <Phone className="size-5 text-green-500" />
              </div>
              <div>
                <CardTitle className="text-base">Phone Numbers</CardTitle>
                <CardDescription>
                  Manage your Telnyx phone numbers for SMS and voice
                </CardDescription>
              </div>
            </div>
            {syncButton}
          </div>
        </CardHeader>
        <CardContent className="space-y-6">
          <div className="space-y-3">
            <h4 className="text-sm font-medium">Your Phone Numbers</h4>
            {ownedNumbersContent}
          </div>

          <Separator />

          <div className="space-y-4">
            <h4 className="text-sm font-medium">Search for New Numbers</h4>
            {searchForm}
            {searchResultsContent}
          </div>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Phone Numbers</h1>
          <p className="text-muted-foreground">
            Manage your Telnyx phone numbers for SMS and voice calls
          </p>
        </div>
        {syncButton}
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Phone className="size-5" />
            Your Phone Numbers
          </CardTitle>
          <CardDescription>
            Phone numbers currently provisioned in your workspace
          </CardDescription>
        </CardHeader>
        <CardContent>{ownedNumbersContent}</CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Search className="size-5" />
            Search for New Numbers
          </CardTitle>
          <CardDescription>
            Find and purchase new phone numbers from Telnyx
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          {searchForm}
          {searchResultsContent}
        </CardContent>
      </Card>
    </div>
  );
}
