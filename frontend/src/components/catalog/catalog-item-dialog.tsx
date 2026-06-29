"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { useEffect } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import * as z from "zod";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import { catalogApi } from "@/lib/api/catalog";
import { queryKeys } from "@/lib/query-keys";
import { getApiErrorMessage } from "@/lib/utils/errors";
import type { CatalogItem, CatalogItemKind } from "@/types";

const moneyString = z
  .string()
  .trim()
  .refine((v) => v === "" || (!Number.isNaN(Number(v)) && Number(v) >= 0), {
    error: "Enter a valid amount",
  });

const itemSchema = z.object({
  name: z.string().trim().min(1, { error: "Name is required" }),
  kind: z.enum(["service", "product"]),
  unit_price: moneyString,
  sku: z.string(),
  description: z.string(),
  taxable: z.boolean(),
  is_active: z.boolean(),
});

type ItemFormValues = z.infer<typeof itemSchema>;

const DEFAULT_VALUES: ItemFormValues = {
  name: "",
  kind: "service",
  unit_price: "",
  sku: "",
  description: "",
  taxable: true,
  is_active: true,
};

interface CatalogItemDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** When present the dialog edits this item; otherwise it creates a new one. */
  item?: CatalogItem | null;
}

export function CatalogItemDialog({
  open,
  onOpenChange,
  item,
}: CatalogItemDialogProps) {
  const workspaceId = useWorkspaceId();
  const queryClient = useQueryClient();
  const isEdit = Boolean(item);

  const form = useForm<ItemFormValues>({
    resolver: zodResolver(itemSchema),
    defaultValues: DEFAULT_VALUES,
  });

  useEffect(() => {
    if (!open) return;
    form.reset(
      item
        ? {
            name: item.name,
            kind: item.kind,
            unit_price: String(item.unit_price),
            sku: item.sku ?? "",
            description: item.description ?? "",
            taxable: item.taxable,
            is_active: item.is_active,
          }
        : DEFAULT_VALUES
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, item]);

  const saveMutation = useMutation({
    mutationFn: async (values: ItemFormValues): Promise<CatalogItem> => {
      if (!workspaceId) throw new Error("No workspace selected");
      const payload = {
        name: values.name.trim(),
        kind: values.kind as CatalogItemKind,
        unit_price: values.unit_price === "" ? 0 : Number(values.unit_price),
        sku: values.sku.trim() || undefined,
        description: values.description.trim() || undefined,
        taxable: values.taxable,
        is_active: values.is_active,
      };
      if (item) {
        return catalogApi.update(workspaceId, item.id, payload);
      }
      return catalogApi.create(workspaceId, payload);
    },
    onSuccess: (saved) => {
      toast.success(isEdit ? `Updated ${saved.name}` : `Added ${saved.name}`);
      if (workspaceId) {
        void queryClient.invalidateQueries({
          queryKey: queryKeys.catalogItems.all(workspaceId),
        });
      }
      onOpenChange(false);
    },
    onError: (err: unknown) =>
      toast.error(getApiErrorMessage(err, "Failed to save catalog item")),
  });

  const handleOpenChange = (next: boolean) => {
    if (!next && saveMutation.isPending) return;
    onOpenChange(next);
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{isEdit ? "Edit item" : "New item"}</DialogTitle>
          <DialogDescription>
            Price book items autofill name and price on quotes and invoices.
          </DialogDescription>
        </DialogHeader>

        <Form {...form}>
          <form
            onSubmit={form.handleSubmit((values) => saveMutation.mutate(values))}
            className="space-y-4"
          >
            <FormField
              control={form.control}
              name="name"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Name</FormLabel>
                  <FormControl>
                    <Input placeholder="e.g. Standard service call" {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <div className="grid grid-cols-2 gap-3">
              <FormField
                control={form.control}
                name="kind"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Type</FormLabel>
                    <Select onValueChange={field.onChange} value={field.value}>
                      <FormControl>
                        <SelectTrigger>
                          <SelectValue />
                        </SelectTrigger>
                      </FormControl>
                      <SelectContent>
                        <SelectItem value="service">Service</SelectItem>
                        <SelectItem value="product">Product</SelectItem>
                      </SelectContent>
                    </Select>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <FormField
                control={form.control}
                name="unit_price"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Unit price</FormLabel>
                    <FormControl>
                      <Input
                        type="number"
                        min="0"
                        step="0.01"
                        inputMode="decimal"
                        placeholder="0.00"
                        {...field}
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
            </div>

            <FormField
              control={form.control}
              name="sku"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Code / SKU (optional)</FormLabel>
                  <FormControl>
                    <Input placeholder="e.g. SVC-001" {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="description"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Description (optional)</FormLabel>
                  <FormControl>
                    <Textarea
                      placeholder="What's included..."
                      className="min-h-[60px]"
                      {...field}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <div className="flex items-center gap-6">
              <FormField
                control={form.control}
                name="taxable"
                render={({ field }) => (
                  <FormItem className="flex items-center gap-2 space-y-0">
                    <FormControl>
                      <Switch
                        checked={field.value}
                        onCheckedChange={field.onChange}
                      />
                    </FormControl>
                    <FormLabel className="!mt-0">Taxable</FormLabel>
                  </FormItem>
                )}
              />
              <FormField
                control={form.control}
                name="is_active"
                render={({ field }) => (
                  <FormItem className="flex items-center gap-2 space-y-0">
                    <FormControl>
                      <Switch
                        checked={field.value}
                        onCheckedChange={field.onChange}
                      />
                    </FormControl>
                    <FormLabel className="!mt-0">Active</FormLabel>
                  </FormItem>
                )}
              />
            </div>

            <DialogFooter className="gap-2">
              <Button
                type="button"
                variant="outline"
                onClick={() => handleOpenChange(false)}
                disabled={saveMutation.isPending}
              >
                Cancel
              </Button>
              <Button type="submit" disabled={saveMutation.isPending}>
                {saveMutation.isPending && (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                )}
                {isEdit ? "Save changes" : "Add item"}
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  );
}
