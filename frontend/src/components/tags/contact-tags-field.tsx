"use client";

/**
 * Tag editor for the contact form.
 *
 * The contact API speaks tag *names* (it creates any name it hasn't seen), while
 * the workspace tag list is keyed by id. This bridges the two: the form value
 * stays a comma-separated name list, the operator gets the real workspace tags
 * with their colours, and a name that isn't a workspace tag yet is preserved
 * rather than dropped — including while the tag list is still loading.
 *
 * Typing a new name and creating it registers a real workspace tag (with a
 * colour) up front, so it shows up in filters and the tag manager immediately
 * instead of being invented at save time.
 */

import { Tag as TagIcon } from "lucide-react";

import { TagBadge } from "@/components/tags/tag-badge";
import { TagPicker } from "@/components/tags/tag-picker";
import { Button } from "@/components/ui/button";
import { useTags } from "@/hooks/useTags";
import { DEFAULT_TAG_COLOR } from "@/lib/tag-colors";
import type { Tag } from "@/types";

/** Split the stored `"vip, priority"` value into trimmed, de-duplicated names. */
export function splitTagNames(value: string): string[] {
  const seen = new Set<string>();
  const names: string[] = [];
  for (const raw of value.split(",")) {
    const name = raw.trim();
    if (!name) continue;
    const key = name.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    names.push(name);
  }
  return names;
}

interface ContactTagsFieldProps {
  workspaceId: string;
  /** Comma-separated tag names, as stored on the form. */
  value: string;
  onChange: (value: string) => void;
}

export function ContactTagsField({ workspaceId, value, onChange }: ContactTagsFieldProps) {
  const { data: tagsData } = useTags(workspaceId);
  const tags = tagsData?.items ?? [];

  const names = splitTagNames(value);
  const byName = new Map(tags.map((tag) => [tag.name.toLowerCase(), tag]));

  const selectedTagIds = names
    .map((name) => byName.get(name.toLowerCase())?.id)
    .filter((id): id is string => Boolean(id));
  // Names with no workspace tag behind them yet — kept verbatim so a slow tag
  // query or a legacy free-text tag can't silently erase what was there.
  const unresolvedNames = names.filter((name) => !byName.has(name.toLowerCase()));

  const emit = (nextNames: string[]) => onChange(nextNames.join(", "));

  // The picker hands back the tag records, not just ids — a tag created a
  // moment ago has no entry in the list query yet, and resolving it by id would
  // silently drop it from the contact on save.
  const handleSelectionChange = (_tagIds: string[], selectedTags: Tag[]) => {
    emit([...unresolvedNames, ...selectedTags.map((tag) => tag.name)]);
  };

  const removeName = (name: string) => {
    emit(names.filter((existing) => existing !== name));
  };

  return (
    <div className="space-y-2">
      <TagPicker
        workspaceId={workspaceId}
        selectedTagIds={selectedTagIds}
        onSelectionChange={handleSelectionChange}
        allowCreate
      >
        {/* A stable action label: what is selected is shown by the chips below,
            so the button doesn't need to double as a counter. */}
        <Button type="button" variant="outline" size="sm" className="w-full justify-start gap-2">
          <TagIcon aria-hidden="true" className="h-4 w-4" />
          Add tags
        </Button>
      </TagPicker>

      {names.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {names.map((name) => (
            <TagBadge
              key={name}
              name={name}
              color={byName.get(name.toLowerCase())?.color ?? DEFAULT_TAG_COLOR}
              onRemove={() => removeName(name)}
            />
          ))}
        </div>
      )}
    </div>
  );
}
