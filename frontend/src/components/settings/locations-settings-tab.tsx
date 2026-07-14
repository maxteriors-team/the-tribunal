"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Building2, Loader2, Pencil, Plus, Trash2 } from "lucide-react";
import { useState } from "react";

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
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
import { Switch } from "@/components/ui/switch";
import { useCapabilities } from "@/hooks/useCapabilities";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import {
  businessLocationsApi,
  type BusinessLocation,
  type BusinessLocationCreateRequest,
  type BusinessLocationUpdateRequest,
} from "@/lib/api/locations";
import { queryKeys } from "@/lib/query-keys";

interface LocationFormData {
  name: string;
  timezone: string;
  phone: string;
  address_line1: string;
  city: string;
  state: string;
  postal_code: string;
  is_active: boolean;
}

function emptyForm(): LocationFormData {
  return {
    name: "",
    timezone: "UTC",
    phone: "",
    address_line1: "",
    city: "",
    state: "",
    postal_code: "",
    is_active: true,
  };
}

function LocationDialog({
  open,
  onOpenChange,
  location,
  workspaceId,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  location: BusinessLocation | null;
  workspaceId: string;
}) {
  const queryClient = useQueryClient();
  const isEditing = !!location;

  const [form, setForm] = useState<LocationFormData>(() =>
    location
      ? {
          name: location.name,
          timezone: location.timezone,
          phone: location.phone ?? "",
          address_line1: location.address_line1 ?? "",
          city: location.city ?? "",
          state: location.state ?? "",
          postal_code: location.postal_code ?? "",
          is_active: location.is_active,
        }
      : emptyForm(),
  );

  const invalidate = () =>
    queryClient.invalidateQueries({
      queryKey: queryKeys.locations.all(workspaceId),
    });

  const createMutation = useMutation({
    mutationFn: (data: BusinessLocationCreateRequest) =>
      businessLocationsApi.create(workspaceId, data),
    onSuccess: () => {
      invalidate();
      onOpenChange(false);
    },
  });

  const updateMutation = useMutation({
    mutationFn: (data: BusinessLocationUpdateRequest) =>
      businessLocationsApi.update(workspaceId, location!.id, data),
    onSuccess: () => {
      invalidate();
      onOpenChange(false);
    },
  });

  const handleSubmit = () => {
    const payload = {
      name: form.name.trim(),
      timezone: form.timezone.trim() || "UTC",
      phone: form.phone.trim() || null,
      address_line1: form.address_line1.trim() || null,
      city: form.city.trim() || null,
      state: form.state.trim() || null,
      postal_code: form.postal_code.trim() || null,
    };
    if (isEditing) {
      updateMutation.mutate({ ...payload, is_active: form.is_active });
    } else {
      createMutation.mutate({ ...payload, country: "US", is_active: true });
    }
  };

  const isPending = createMutation.isPending || updateMutation.isPending;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>
            {isEditing ? "Edit Location" : "Add Location"}
          </DialogTitle>
          <DialogDescription>
            A location is one of your business&apos;s branches. Staff and jobs
            can be assigned to it so you can filter and report by branch.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="loc-name">Name</Label>
            <Input
              id="loc-name"
              placeholder="e.g. Austin Branch"
              value={form.name}
              onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-2">
              <Label htmlFor="loc-timezone">Timezone</Label>
              <Input
                id="loc-timezone"
                placeholder="America/Chicago"
                value={form.timezone}
                onChange={(e) =>
                  setForm((f) => ({ ...f, timezone: e.target.value }))
                }
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="loc-phone">Phone</Label>
              <Input
                id="loc-phone"
                placeholder="+1 512 555 0100"
                value={form.phone}
                onChange={(e) =>
                  setForm((f) => ({ ...f, phone: e.target.value }))
                }
              />
            </div>
          </div>

          <div className="space-y-2">
            <Label htmlFor="loc-address">Street address</Label>
            <Input
              id="loc-address"
              placeholder="123 Main St"
              value={form.address_line1}
              onChange={(e) =>
                setForm((f) => ({ ...f, address_line1: e.target.value }))
              }
            />
          </div>

          <div className="grid grid-cols-3 gap-3">
            <div className="space-y-2">
              <Label htmlFor="loc-city">City</Label>
              <Input
                id="loc-city"
                value={form.city}
                onChange={(e) =>
                  setForm((f) => ({ ...f, city: e.target.value }))
                }
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="loc-state">State</Label>
              <Input
                id="loc-state"
                value={form.state}
                onChange={(e) =>
                  setForm((f) => ({ ...f, state: e.target.value }))
                }
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="loc-postal">Postal code</Label>
              <Input
                id="loc-postal"
                value={form.postal_code}
                onChange={(e) =>
                  setForm((f) => ({ ...f, postal_code: e.target.value }))
                }
              />
            </div>
          </div>

          {isEditing && (
            <div className="flex items-center justify-between">
              <Label>Active</Label>
              <Switch
                checked={form.is_active}
                onCheckedChange={(checked) =>
                  setForm((f) => ({ ...f, is_active: checked }))
                }
              />
            </div>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={handleSubmit} disabled={!form.name.trim() || isPending}>
            {isPending && <Loader2 className="mr-2 size-4 animate-spin" />}
            {isEditing ? "Save Changes" : "Create"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function LocationsSettingsTab() {
  const workspaceId = useWorkspaceId();
  const queryClient = useQueryClient();
  const { can } = useCapabilities();
  const canManage = can("locations:manage");

  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<BusinessLocation | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<BusinessLocation | null>(null);

  const { data, isPending } = useQuery({
    queryKey: queryKeys.locations.all(workspaceId ?? ""),
    queryFn: () => businessLocationsApi.list(workspaceId!),
    enabled: !!workspaceId,
  });

  const locations = data?.items ?? [];

  const deleteMutation = useMutation({
    mutationFn: (id: string) => businessLocationsApi.delete(workspaceId!, id),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: queryKeys.locations.all(workspaceId ?? ""),
      });
      setDeleteTarget(null);
    },
  });

  const toggleMutation = useMutation({
    mutationFn: ({ id, isActive }: { id: string; isActive: boolean }) =>
      businessLocationsApi.update(workspaceId!, id, { is_active: isActive }),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: queryKeys.locations.all(workspaceId ?? ""),
      });
    },
  });

  const handleCreate = () => {
    setEditing(null);
    setDialogOpen(true);
  };

  const handleEdit = (location: BusinessLocation) => {
    setEditing(location);
    setDialogOpen(true);
  };

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle>Locations</CardTitle>
              <CardDescription>
                Manage your business&apos;s branches. Assign staff and jobs to a
                location to filter and report by branch.
              </CardDescription>
            </div>
            {canManage && (
              <Button onClick={handleCreate}>
                <Plus className="mr-2 size-4" />
                Add Location
              </Button>
            )}
          </div>
        </CardHeader>
        <CardContent>
          {isPending ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="size-6 animate-spin text-muted-foreground" />
            </div>
          ) : locations.length === 0 ? (
            <div className="text-center py-12 text-muted-foreground">
              <Building2 className="mx-auto size-10 mb-3 opacity-50" />
              <p className="font-medium">No locations yet</p>
              <p className="text-sm mt-1">
                {canManage
                  ? "Add a location to start organizing staff and jobs by branch."
                  : "No business locations have been set up yet."}
              </p>
            </div>
          ) : (
            <div className="space-y-3">
              {locations.map((location) => (
                <div
                  key={location.id}
                  className="flex items-start justify-between gap-4 rounded-lg border p-4"
                >
                  <div className="flex-1 min-w-0 space-y-1.5">
                    <div className="flex items-center gap-2">
                      <h4 className="font-medium">{location.name}</h4>
                      <Badge
                        variant={location.is_active ? "default" : "secondary"}
                        className="text-xs"
                      >
                        {location.is_active ? "Active" : "Inactive"}
                      </Badge>
                      <Badge variant="outline" className="text-xs">
                        {location.timezone}
                      </Badge>
                    </div>
                    {(location.address_line1 || location.city) && (
                      <p className="text-sm text-muted-foreground truncate">
                        {[
                          location.address_line1,
                          location.city,
                          location.state,
                          location.postal_code,
                        ]
                          .filter(Boolean)
                          .join(", ")}
                      </p>
                    )}
                    {location.phone && (
                      <p className="text-sm text-muted-foreground">
                        {location.phone}
                      </p>
                    )}
                  </div>

                  {canManage && (
                    <div className="flex items-center gap-1">
                      <Switch
                        checked={location.is_active}
                        onCheckedChange={(checked) =>
                          toggleMutation.mutate({
                            id: location.id,
                            isActive: checked,
                          })
                        }
                        aria-label="Toggle active"
                      />
                      <Button
                        variant="ghost"
                        size="icon"
                        className="size-8"
                        onClick={() => handleEdit(location)}
                        aria-label="Edit location"
                      >
                        <Pencil className="size-3.5" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="size-8 text-destructive hover:text-destructive"
                        onClick={() => setDeleteTarget(location)}
                        aria-label="Delete location"
                      >
                        <Trash2 className="size-3.5" />
                      </Button>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {dialogOpen && workspaceId && (
        <LocationDialog
          open={dialogOpen}
          onOpenChange={setDialogOpen}
          location={editing}
          workspaceId={workspaceId}
        />
      )}

      <AlertDialog
        open={!!deleteTarget}
        onOpenChange={(open) => !open && setDeleteTarget(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete Location</AlertDialogTitle>
            <AlertDialogDescription>
              Are you sure you want to delete &quot;{deleteTarget?.name}&quot;?
              Staff and jobs assigned to it will become unassigned. Consider
              deactivating instead to keep history.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              onClick={() =>
                deleteTarget && deleteMutation.mutate(deleteTarget.id)
              }
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
