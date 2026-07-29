"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { useEffect, useId } from "react";
import { useForm, useWatch } from "react-hook-form";
import { toast } from "sonner";
import * as z from "zod";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
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
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
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
import { Textarea } from "@/components/ui/textarea";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import { catalogApi } from "@/lib/api/catalog";
import { SERVICE_CATEGORY_OPTIONS } from "@/lib/constants";
import { queryKeys } from "@/lib/query-keys";
import { getApiErrorMessage } from "@/lib/utils/errors";
import type { CatalogItem, CatalogItemKind } from "@/types";

// Radix Select forbids an empty-string value, so "no category" and "type your
// own" need sentinels. Categories are free-form on the backend on purpose, so
// the picker offers the shared defaults plus an escape hatch.
const NO_CATEGORY = "__none__";
const CUSTOM_CATEGORY = "__custom__";
const CATEGORY_VALUES: readonly string[] = SERVICE_CATEGORY_OPTIONS.map(
  (option) => option.value
);

const categoryLabel = (value: string) =>
  SERVICE_CATEGORY_OPTIONS.find((option) => option.value === value)?.label ??
  value;

const moneyString = z
  .string()
  .trim()
  .refine((v) => v === "" || (!Number.isNaN(Number(v)) && Number(v) >= 0), {
    error: "Enter a valid amount",
  });

const itemSchema = z
  .object({
    name: z.string().trim().min(1, { error: "Name is required" }),
    kind: z.enum(["service", "product"]),
    unit_price: moneyString,
    sku: z.string(),
    description: z.string(),
    taxable: z.boolean(),
    is_active: z.boolean(),
    service_category: z.string(),
    custom_category: z.string().trim().max(60, {
      error: "Keep the category under 60 characters",
    }),
    is_attachable: z.boolean(),
    attach_targets: z.array(z.string()),
  })
  .refine(
    (v) => v.service_category !== CUSTOM_CATEGORY || v.custom_category !== "",
    { error: "Name the category", path: ["custom_category"] }
  );

type ItemFormValues = z.infer<typeof itemSchema>;

const DEFAULT_VALUES: ItemFormValues = {
  name: "",
  kind: "service",
  unit_price: "",
  sku: "",
  description: "",
  taxable: true,
  is_active: true,
  service_category: NO_CATEGORY,
  custom_category: "",
  is_attachable: false,
  attach_targets: [],
};

/** Resolve the select + free-text pair back into the stored category. */
function resolveCategory(values: ItemFormValues): string | null {
  if (values.service_category === NO_CATEGORY) return null;
  if (values.service_category === CUSTOM_CATEGORY) {
    return values.custom_category.trim() || null;
  }
  return values.service_category;
}

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

  const targetFieldId = useId();

  const form = useForm<ItemFormValues>({
    resolver: zodResolver(itemSchema),
    defaultValues: DEFAULT_VALUES,
  });

  // `useWatch` rather than `form.watch()`: the latter returns a fresh function
  // every render, which makes the React Compiler skip memoizing this dialog.
  const control = form.control;
  const isCustomCategory =
    useWatch({ control, name: "service_category" }) === CUSTOM_CATEGORY;
  const isAttachable = useWatch({ control, name: "is_attachable" });
  const attachTargets = useWatch({ control, name: "attach_targets" });
  // Defaults, plus any target this item already carries (a workspace's own
  // category) so editing an item never silently drops a saved target.
  const attachTargetOptions = [
    ...CATEGORY_VALUES,
    ...attachTargets.filter((value) => !CATEGORY_VALUES.includes(value)),
  ];

  useEffect(() => {
    if (!open) return;
    if (!item) {
      form.reset(DEFAULT_VALUES);
      return;
    }
    // A saved category outside the shared defaults (a workspace's own trade)
    // reopens as "Custom" so editing an item never silently drops it.
    const saved = item.service_category ?? "";
    const isCustom = saved !== "" && !CATEGORY_VALUES.includes(saved);
    form.reset({
      name: item.name,
      kind: item.kind,
      unit_price: String(item.unit_price),
      sku: item.sku ?? "",
      description: item.description ?? "",
      taxable: item.taxable,
      is_active: item.is_active,
      service_category:
        saved === "" ? NO_CATEGORY : isCustom ? CUSTOM_CATEGORY : saved,
      custom_category: isCustom ? saved : "",
      is_attachable: item.is_attachable,
      attach_targets: item.attach_targets ?? [],
    });
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
        service_category: resolveCategory(values),
        is_attachable: values.is_attachable,
        // Targets only mean something for an attachable item; clear them
        // otherwise so a toggled-off item stops matching attach-rate reports.
        attach_targets: values.is_attachable ? values.attach_targets : [],
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
              name="service_category"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Service category</FormLabel>
                  <Select onValueChange={field.onChange} value={field.value}>
                    <FormControl>
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      <SelectItem value={NO_CATEGORY}>Uncategorized</SelectItem>
                      {SERVICE_CATEGORY_OPTIONS.map((option) => (
                        <SelectItem key={option.value} value={option.value}>
                          {option.label}
                        </SelectItem>
                      ))}
                      <SelectItem value={CUSTOM_CATEGORY}>Custom…</SelectItem>
                    </SelectContent>
                  </Select>
                  <FormDescription>
                    Groups the price book by service line, so attach-rate
                    reporting can tell a roof from gutters.
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

            {isCustomCategory && (
              <FormField
                control={form.control}
                name="custom_category"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Category name</FormLabel>
                    <FormControl>
                      <Input
                        placeholder="e.g. holiday lighting"
                        maxLength={60}
                        {...field}
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
            )}

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

            <div className="space-y-3 rounded-md border p-3">
              <FormField
                control={form.control}
                name="is_attachable"
                render={({ field }) => (
                  <FormItem className="flex items-center gap-2 space-y-0">
                    <FormControl>
                      <Switch
                        checked={field.value}
                        onCheckedChange={field.onChange}
                      />
                    </FormControl>
                    <FormLabel className="!mt-0">
                      Can be attached to other jobs
                    </FormLabel>
                  </FormItem>
                )}
              />

              {isAttachable && (
                <FormField
                  control={form.control}
                  name="attach_targets"
                  render={({ field }) => (
                    <FormItem className="space-y-2">
                      <FormLabel>Attaches to</FormLabel>
                      <div className="grid grid-cols-2 gap-2">
                        {attachTargetOptions.map((value) => {
                          const checkboxId = `${targetFieldId}-${value}`;
                          return (
                            <div
                              key={value}
                              className="flex items-center gap-2"
                            >
                              <Checkbox
                                id={checkboxId}
                                checked={field.value.includes(value)}
                                onCheckedChange={(checked) =>
                                  field.onChange(
                                    checked === true
                                      ? [...field.value, value]
                                      : field.value.filter((v) => v !== value)
                                  )
                                }
                              />
                              <Label
                                htmlFor={checkboxId}
                                className="font-normal"
                              >
                                {categoryLabel(value)}
                              </Label>
                            </div>
                          );
                        })}
                      </div>
                      <FormDescription>
                        Categories this add-on rides along with — pick Roof for a
                        gutter add-on. Leave empty for no restriction.
                      </FormDescription>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              )}
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
