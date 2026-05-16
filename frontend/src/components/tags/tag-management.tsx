"use client";

import { useState } from "react";
import { Plus, Pencil, Trash2, Loader2, Tags } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
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
import { TagBadge } from "@/components/tags/tag-badge";
import { useTags, useCreateTag, useUpdateTag, useDeleteTag } from "@/hooks/useTags";
import { useWorkspaceId } from "@/hooks/use-workspace-id";
import { TAG_COLORS, DEFAULT_TAG_COLOR } from "@/lib/tag-colors";
import type { Tag } from "@/types";

export function TagManagement() {
  const workspaceId = useWorkspaceId() ?? "";
  const { data: tagsData, isPending } = useTags(workspaceId);
  const createTag = useCreateTag(workspaceId);
  const updateTag = useUpdateTag(workspaceId);
  const deleteTag = useDeleteTag(workspaceId);

  const [createOpen, setCreateOpen] = useState(false);
  const [editTag, setEditTag] = useState<Tag | null>(null);
  const [deleteConfirmTag, setDeleteConfirmTag] = useState<Tag | null>(null);
  const [name, setName] = useState("");
  const [color, setColor] = useState(DEFAULT_TAG_COLOR);

  const tags = tagsData?.items ?? [];

  const handleCreate = async () => {
    if (!name.trim()) return;
    try {
      await createTag.mutateAsync({ name: name.trim(), color });
      toast.success("Tag created");
      setCreateOpen(false);
      setName("");
      setColor(DEFAULT_TAG_COLOR);
    } catch {
      toast.error("Failed to create tag");
    }
  };

  const handleUpdate = async () => {
    if (!editTag || !name.trim()) return;
    try {
      await updateTag.mutateAsync({
        id: editTag.id,
        data: { name: name.trim(), color },
      });
      toast.success("Tag updated");
      setEditTag(null);
      setName("");
      setColor(DEFAULT_TAG_COLOR);
    } catch {
      toast.error("Failed to update tag");
    }
  };

  const handleDelete = async () => {
    if (!deleteConfirmTag) return;
    try {
      await deleteTag.mutateAsync(deleteConfirmTag.id);
      toast.success("Tag deleted");
      setDeleteConfirmTag(null);
    } catch {
      toast.error("Failed to delete tag");
    }
  };

  const openEdit = (tag: Tag) => {
    setEditTag(tag);
    setName(tag.name);
    setColor(tag.color);
  };

  const openCreate = () => {
    setName("");
    setColor(DEFAULT_TAG_COLOR);
    setCreateOpen(true);
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Tags className="h-5 w-5 text-muted-foreground" />
          <h3 className="font-medium">Tags</h3>
          <span className="text-sm text-muted-foreground">
            ({tags.length})
          </span>
        </div>
        <Button size="sm" onClick={openCreate} className="gap-2">
          <Plus className="h-4 w-4" />
          New Tag
        </Button>
      </div>

      {isPending ? (
        <div className="flex items-center justify-center py-8">
          <Loader2 className="h-6 w-6 animate-spin" />
        </div>
      ) : tags.length === 0 ? (
        <div className="text-center py-8 text-muted-foreground">
          <Tags className="h-12 w-12 mx-auto mb-2 opacity-50" />
          <p>No tags yet. Create your first tag to start organizing contacts.</p>
        </div>
      ) : (
        <div className="border rounded-lg divide-y">
          {tags.map((tag) => (
            <div
              key={tag.id}
              className="flex items-center gap-3 px-4 py-3 hover:bg-muted/50 transition-colors"
            >
              <TagBadge name={tag.name} color={tag.color} />
              <span className="text-sm text-muted-foreground ml-auto">
                {tag.contact_count} contact{tag.contact_count !== 1 ? "s" : ""}
              </span>
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8"
                onClick={() => openEdit(tag)}
                aria-label="Edit tag"
              >
                <Pencil className="h-4 w-4" />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8 text-destructive hover:text-destructive"
                onClick={() => setDeleteConfirmTag(tag)}
                aria-label="Delete tag"
              >
                <Trash2 className="h-4 w-4" />
              </Button>
            </div>
          ))}
        </div>
      )}

      {/* Create Tag Dialog */}
      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle>Create Tag</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <Input
              placeholder="Tag name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") handleCreate();
              }}
            />
            <div>
              <p className="text-sm text-muted-foreground mb-2">Color</p>
              <div className="flex flex-wrap gap-2">
                {TAG_COLORS.map((c) => (
                  <button
                    key={c}
                    type="button"
                    onClick={() => setColor(c)}
                    className="h-7 w-7 rounded-full border-2 transition-all"
                    style={{
                      backgroundColor: c,
                      borderColor: color === c ? "#000" : "transparent",
                    }}
                    aria-label={`Select color ${c}`}
                    aria-pressed={color === c}
                  />
                ))}
              </div>
            </div>
            {name.trim() && (
              <div>
                <p className="text-sm text-muted-foreground mb-1">Preview</p>
                <TagBadge name={name.trim()} color={color} />
              </div>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCreateOpen(false)}>
              Cancel
            </Button>
            <Button
              onClick={handleCreate}
              disabled={!name.trim() || createTag.isPending}
            >
              {createTag.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin mr-2" />
              ) : null}
              Create
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Edit Tag Dialog */}
      <Dialog open={!!editTag} onOpenChange={(open) => !open && setEditTag(null)}>
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle>Edit Tag</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <Input
              placeholder="Tag name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") handleUpdate();
              }}
            />
            <div>
              <p className="text-sm text-muted-foreground mb-2">Color</p>
              <div className="flex flex-wrap gap-2">
                {TAG_COLORS.map((c) => (
                  <button
                    key={c}
                    type="button"
                    onClick={() => setColor(c)}
                    className="h-7 w-7 rounded-full border-2 transition-all"
                    style={{
                      backgroundColor: c,
                      borderColor: color === c ? "#000" : "transparent",
                    }}
                    aria-label={`Select color ${c}`}
                    aria-pressed={color === c}
                  />
                ))}
              </div>
            </div>
            {name.trim() && (
              <div>
                <p className="text-sm text-muted-foreground mb-1">Preview</p>
                <TagBadge name={name.trim()} color={color} />
              </div>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setEditTag(null)}>
              Cancel
            </Button>
            <Button
              onClick={handleUpdate}
              disabled={!name.trim() || updateTag.isPending}
            >
              {updateTag.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin mr-2" />
              ) : null}
              Save
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete Confirmation */}
      <AlertDialog
        open={!!deleteConfirmTag}
        onOpenChange={(open) => !open && setDeleteConfirmTag(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete Tag</AlertDialogTitle>
            <AlertDialogDescription>
              Are you sure you want to delete the tag &quot;{deleteConfirmTag?.name}&quot;?
              This will remove it from all contacts.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleDelete}
              disabled={deleteTag.isPending}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              {deleteTag.isPending ? "Deleting..." : "Delete"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
