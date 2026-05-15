"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  Phone,
  Search,
  Loader2,
  AlertCircle,
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
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
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

export function PhoneNumbersPage() {
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
      return phoneNumbersApi.purchase(workspaceId, { phone_number: phoneNumber });
    },
    onSuccess: (data) => {
      toast.success(`Successfully purchased ${data.phone_number}`);
      queryClient.invalidateQueries({ queryKey: queryKeys.phoneNumbers.bare(workspaceId ?? "") });
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
      queryClient.invalidateQueries({ queryKey: queryKeys.phoneNumbers.bare(workspaceId ?? "") });
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
      queryClient.invalidateQueries({ queryKey: queryKeys.phoneNumbers.bare(workspaceId ?? "") });
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

  const formatPhoneNumber = (number: string) => {
    const cleaned = number.replace(/\D/g, "");
    if (cleaned.length === 11 && cleaned.startsWith("1")) {
      const match = cleaned.match(/^1(\d{3})(\d{3})(\d{4})$/);
      if (match) {
        return `+1 (${match[1]}) ${match[2]}-${match[3]}`;
      }
    }
    return number;
  };

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Phone Numbers</h1>
          <p className="text-muted-foreground">
            Manage your Telnyx phone numbers for SMS and voice calls
          </p>
        </div>
        <Button
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
      </div>

      {/* Current Phone Numbers */}
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
        <CardContent>
          {isLoadingNumbers ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="size-8 animate-spin text-muted-foreground" />
            </div>
          ) : numbersError ? (
            <div className="flex flex-col items-center justify-center py-12 gap-2">
              <AlertCircle className="size-8 text-destructive" />
              <p className="text-muted-foreground">
                Failed to load phone numbers
              </p>
            </div>
          ) : phoneNumbers.length === 0 ? (
            <div className="text-center py-12 border rounded-lg border-dashed">
              <Phone className="size-12 mx-auto text-muted-foreground mb-3" />
              <h3 className="font-medium text-lg mb-1">No phone numbers yet</h3>
              <p className="text-muted-foreground mb-4">
                Search and purchase a number below, or sync existing numbers from
                your Telnyx account.
              </p>
            </div>
          ) : (
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
                      <AlertDialog>
                        <AlertDialogTrigger asChild>
                          <Button
                            variant="ghost"
                            size="sm"
                            className="text-destructive hover:text-destructive hover:bg-destructive/10"
                          >
                            <Trash2 className="size-4" />
                          </Button>
                        </AlertDialogTrigger>
                        <AlertDialogContent>
                          <AlertDialogHeader>
                            <AlertDialogTitle>
                              Release Phone Number
                            </AlertDialogTitle>
                            <AlertDialogDescription>
                              Are you sure you want to release{" "}
                              {formatPhoneNumber(number.phone_number)}? This
                              action cannot be undone and you may not be able to
                              get this number back.
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
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {/* Search for New Numbers */}
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
          <form onSubmit={handleSearch} className="flex gap-3">
            <div className="w-48">
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
            <div className="flex-1 max-w-xs">
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

          {/* Search Results */}
          {hasSearched && (
            <div className="space-y-4">
              {searchResults.length === 0 ? (
                <div className="text-center py-8 border rounded-lg border-dashed">
                  <p className="text-muted-foreground">
                    No available numbers found. Try a different area code.
                  </p>
                </div>
              ) : (
                <>
                  <p className="text-sm text-muted-foreground">
                    {searchResults.length} number(s) available
                  </p>
                  <div className="grid gap-3 md:grid-cols-2">
                    {searchResults.map((result) => (
                      <div
                        key={result.id}
                        className="flex items-center justify-between p-4 rounded-lg border bg-muted/30"
                      >
                        <div className="flex items-center gap-3">
                          <div className="flex size-10 items-center justify-center rounded-full bg-primary/10">
                            <Phone className="size-5 text-primary" />
                          </div>
                          <div>
                            <p className="font-medium">
                              {formatPhoneNumber(result.phone_number)}
                            </p>
                            <div className="flex items-center gap-2 mt-0.5">
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
          )}
        </CardContent>
      </Card>
    </div>
  );
}
