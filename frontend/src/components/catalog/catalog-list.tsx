"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Boxes, MoreHorizontal, Pencil, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  PageEmptyState,
  PageErrorState,
  PageLoadingState,
} from "@/components/ui/page-state";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import { catalogApi } from "@/lib/api/catalog";
import { queryKeys } from "@/lib/query-keys";
import { POLL_60S } from "@/lib/query-options";
import { getApiErrorMessage } from "@/lib/utils/errors";
import { formatCurrency } from "@/lib/utils/number";
import type { CatalogItem } from "@/types";

import { CatalogItemDialog } from "./catalog-item-dialog";

export function CatalogList() {
  const workspaceId = useWorkspaceId();
  const queryClient = useQueryClient();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<CatalogItem | null>(null);

  const query = useQuery({
    queryKey: queryKeys.catalogItems.list(workspaceId ?? "", {
      include_inactive: true,
    }),
    queryFn: () =>
      catalogApi.list(workspaceId ?? "", {
        page_size: 200,
        include_inactive: true,
      }),
    enabled: Boolean(workspaceId),
    ...POLL_60S,
  });

  const invalidate = () => {
    if (workspaceId) {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.catalogItems.all(workspaceId),
      });
    }
  };

  const deleteMutation = useMutation({
    mutationFn: (id: string) => catalogApi.delete(workspaceId ?? "", id),
    onSuccess: () => {
      toast.success("Item deleted");
      invalidate();
    },
    onError: (err: unknown) =>
      toast.error(getApiErrorMessage(err, "Failed to delete item")),
  });

  const openCreate = () => {
    setEditing(null);
    setDialogOpen(true);
  };

  const openEdit = (item: CatalogItem) => {
    setEditing(item);
    setDialogOpen(true);
  };

  const newItemButton = (
    <Button onClick={openCreate} size="sm">
      <Plus className="mr-1.5 h-4 w-4" />
      New item
    </Button>
  );

  let body: React.ReactNode;
  if (!workspaceId || query.isLoading) {
    body = <PageLoadingState message="Loading price book..." />;
  } else if (query.isError) {
    body = (
      <PageErrorState
        message={getApiErrorMessage(query.error, "Failed to load price book")}
        onRetry={() => void query.refetch()}
      />
    );
  } else {
    const items = query.data?.items ?? [];
    if (items.length === 0) {
      body = (
        <PageEmptyState
          icon={<Boxes className="size-8" />}
          title="No price book items yet"
          description="Add reusable services and products to autofill quotes and invoices."
          action={newItemButton}
        />
      );
    } else {
      body = (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Type</TableHead>
              <TableHead>Code</TableHead>
              <TableHead className="text-right">Unit price</TableHead>
              <TableHead>Tax</TableHead>
              <TableHead className="w-10" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {items.map((item) => (
              <TableRow key={item.id} className={item.is_active ? "" : "opacity-50"}>
                <TableCell className="font-medium">
                  <div className="flex items-center gap-2">
                    {item.name}
                    {!item.is_active && (
                      <Badge variant="outline">archived</Badge>
                    )}
                  </div>
                  {item.description && (
                    <div className="max-w-[28rem] truncate text-xs text-muted-foreground">
                      {item.description}
                    </div>
                  )}
                </TableCell>
                <TableCell>
                  <Badge variant="secondary">{item.kind}</Badge>
                </TableCell>
                <TableCell className="text-muted-foreground">
                  {item.sku || "—"}
                </TableCell>
                <TableCell className="text-right">
                  {formatCurrency(item.unit_price)}
                </TableCell>
                <TableCell className="text-muted-foreground">
                  {item.taxable ? "Yes" : "No"}
                </TableCell>
                <TableCell>
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button
                        variant="ghost"
                        size="icon"
                        disabled={deleteMutation.isPending}
                        aria-label="Actions"
                      >
                        <MoreHorizontal className="h-4 w-4" />
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end">
                      <DropdownMenuItem onClick={() => openEdit(item)}>
                        <Pencil className="mr-2 h-4 w-4" />
                        Edit
                      </DropdownMenuItem>
                      <DropdownMenuItem
                        variant="destructive"
                        onClick={() => deleteMutation.mutate(item.id)}
                      >
                        <Trash2 className="mr-2 h-4 w-4" />
                        Delete
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      );
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-end">{newItemButton}</div>
      {body}
      <CatalogItemDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        item={editing}
      />
    </div>
  );
}
