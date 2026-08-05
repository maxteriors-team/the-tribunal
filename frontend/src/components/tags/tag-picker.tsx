"use client";

import { Check, Plus, Loader2 } from "lucide-react";
import { useState } from "react";

import { TagBadge } from "@/components/tags/tag-badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { ScrollArea } from "@/components/ui/scroll-area";
import { useTags, useCreateTag } from "@/hooks/useTags";
import { TAG_COLORS } from "@/lib/tag-colors";
import { cn } from "@/lib/utils";
import type { Tag } from "@/types";

interface TagPickerProps {
  workspaceId: string;
  selectedTagIds: string[];
  /**
   * The `tags` argument carries the full records for the selected ids,
   * including one created a moment ago. Callers that need anything but the id
   * (a name, a colour) have to read it from here: the tag list query has not
   * refetched yet, so a brand-new id resolves to nothing in the list.
   */
  onSelectionChange: (tagIds: string[], tags: Tag[]) => void;
  allowCreate?: boolean;
  children?: React.ReactNode;
}

export function TagPicker({
  workspaceId,
  selectedTagIds,
  onSelectionChange,
  allowCreate = true,
  children,
}: TagPickerProps) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const { data: tagsData, isPending } = useTags(workspaceId);
  const createTag = useCreateTag(workspaceId);

  const tags = tagsData?.items ?? [];
  const filteredTags = search.trim()
    ? tags.filter((t) => t.name.toLowerCase().includes(search.toLowerCase()))
    : tags;

  const exactMatch = tags.find(
    (t) => t.name.toLowerCase() === search.trim().toLowerCase()
  );

  /** Report ids plus the records behind them, `justCreated` included. */
  const emitSelection = (tagIds: string[], justCreated?: Tag) => {
    const byId = new Map(
      (justCreated ? [...tags, justCreated] : tags).map((tag) => [tag.id, tag])
    );
    onSelectionChange(
      tagIds,
      tagIds.map((id) => byId.get(id)).filter((tag): tag is Tag => Boolean(tag))
    );
  };

  const handleToggle = (tagId: string) => {
    if (selectedTagIds.includes(tagId)) {
      emitSelection(selectedTagIds.filter((id) => id !== tagId));
    } else {
      emitSelection([...selectedTagIds, tagId]);
    }
  };

  const handleCreateTag = async () => {
    if (!search.trim() || exactMatch) return;
    const randomColor =
      TAG_COLORS[Math.floor(Math.random() * TAG_COLORS.length)];
    const newTag = await createTag.mutateAsync({
      name: search.trim(),
      color: randomColor,
    });
    emitSelection([...selectedTagIds, newTag.id], newTag);
    setSearch("");
  };

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        {children ?? (
          <Button variant="outline" size="sm" className="gap-2">
            <Plus className="h-4 w-4" />
            Tags
          </Button>
        )}
      </PopoverTrigger>
      <PopoverContent className="w-64 p-0" align="start">
        <div className="p-2 border-b">
          <Input
            placeholder="Search or create tag..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="h-8"
            onKeyDown={(e) => {
              if (e.key !== "Enter") return;
              // This picker is used inside form dialogs; without this, Enter
              // would submit the surrounding form instead of creating a tag.
              e.preventDefault();
              if (search.trim() && !exactMatch && allowCreate) {
                handleCreateTag();
              }
            }}
          />
        </div>
        <ScrollArea className="max-h-[200px]">
          {isPending ? (
            <div className="flex items-center justify-center py-4">
              <Loader2 className="h-4 w-4 animate-spin" />
            </div>
          ) : (
            <div className="p-1">
              {filteredTags.map((tag: Tag) => (
                <button
                  key={tag.id}
                  type="button"
                  onClick={() => handleToggle(tag.id)}
                  className={cn(
                    "w-full flex items-center gap-2 px-2 py-1.5 rounded-md text-sm hover:bg-accent transition-colors",
                    selectedTagIds.includes(tag.id) && "bg-accent"
                  )}
                >
                  <div
                    className="h-3 w-3 rounded-full shrink-0"
                    style={{ backgroundColor: tag.color }}
                  />
                  <span className="flex-1 text-left truncate">{tag.name}</span>
                  {selectedTagIds.includes(tag.id) && (
                    <Check className="h-4 w-4 text-primary shrink-0" />
                  )}
                </button>
              ))}
              {filteredTags.length === 0 && !search.trim() && (
                <p className="text-sm text-muted-foreground text-center py-4">
                  No tags yet
                </p>
              )}
              {search.trim() && !exactMatch && allowCreate && (
                <button
                  type="button"
                  onClick={handleCreateTag}
                  disabled={createTag.isPending}
                  className="w-full flex items-center gap-2 px-2 py-1.5 rounded-md text-sm hover:bg-accent transition-colors text-primary"
                >
                  {createTag.isPending ? (
                    <Loader2 className="h-3 w-3 animate-spin" />
                  ) : (
                    <Plus className="h-3 w-3" />
                  )}
                  <span>Create &quot;{search.trim()}&quot;</span>
                </button>
              )}
            </div>
          )}
        </ScrollArea>

        {/* Show selected tags below */}
        {selectedTagIds.length > 0 && (
          <div className="border-t p-2">
            <div className="flex flex-wrap gap-1">
              {selectedTagIds.map((tagId) => {
                const tag = tags.find((t) => t.id === tagId);
                if (!tag) return null;
                return (
                  <TagBadge
                    key={tag.id}
                    name={tag.name}
                    color={tag.color}
                    onRemove={() => handleToggle(tag.id)}
                  />
                );
              })}
            </div>
          </div>
        )}
      </PopoverContent>
    </Popover>
  );
}
