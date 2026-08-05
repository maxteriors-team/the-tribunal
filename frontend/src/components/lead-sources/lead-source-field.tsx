"use client";

/**
 * Lead-source picker with inline creation.
 *
 * Attribution only stays honest if recording it is never a detour. An operator
 * entering a lead who heard about the business through a channel nobody set up
 * yet would otherwise have to abandon the contact form, open Settings, create
 * the source, and start over — so in practice they pick "close enough" and the
 * ROI report quietly rots. Creating the source here keeps them in the form.
 *
 * The inline panel is markup, not a nested `<form>` (which HTML forbids), so
 * Enter and the create button are wired by hand to never submit the contact
 * form underneath.
 */

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2, Plus } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { LeadSourcePicker, SourceTypePicker } from "@/components/lead-sources/source-pickers";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import {
  leadSourcesApi,
  type LeadSource,
  type LeadSourceType,
} from "@/lib/api/lead-sources";
import { queryKeys } from "@/lib/query-keys";

interface LeadSourceFieldProps {
  workspaceId: string;
  value: string | undefined;
  onChange: (leadSourceId: string) => void;
  onClear: () => void;
  allowClear?: boolean;
  id?: string;
  "aria-label"?: string;
}

export function LeadSourceField({
  workspaceId,
  value,
  onChange,
  onClear,
  allowClear = false,
  id,
  "aria-label": ariaLabel = "Lead source",
}: LeadSourceFieldProps) {
  const queryClient = useQueryClient();
  const activeWorkspaceId = useWorkspaceId();
  const [isCreating, setIsCreating] = useState(false);
  const [name, setName] = useState("");
  const [sourceType, setSourceType] = useState<LeadSourceType>("other");
  const nameInputRef = useRef<HTMLInputElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);

  // Focus follows the explicit "New lead source" activation, so the operator can
  // start typing straight away. Focus alone would scroll just the input into
  // view and leave the panel's own Add button below the fold, so the whole panel
  // is scrolled in afterwards.
  useEffect(() => {
    if (!isCreating) return;
    nameInputRef.current?.focus({ preventScroll: true });
    panelRef.current?.scrollIntoView({ block: "nearest" });
  }, [isCreating]);

  const createMutation = useMutation({
    mutationFn: (): Promise<LeadSource> =>
      leadSourcesApi.create(workspaceId, {
        name: name.trim(),
        // The web-capture settings (allowed domains, post-capture automation)
        // belong to the Settings screen; a source created mid-contact only has
        // to be nameable and attributable.
        allowed_domains: [],
        source_type: sourceType,
        action: "collect",
      }),
    onSuccess: async (created) => {
      await queryClient.invalidateQueries({
        queryKey: queryKeys.leadSources.all(activeWorkspaceId ?? workspaceId),
      });
      onChange(created.id);
      closePanel();
      toast.success(`Added lead source "${created.name}"`);
    },
    onError: () => toast.error("Could not create that lead source"),
  });

  const closePanel = () => {
    setIsCreating(false);
    setName("");
    setSourceType("other");
  };

  const submitNewSource = () => {
    if (!name.trim() || createMutation.isPending) return;
    createMutation.mutate();
  };

  return (
    <div className="space-y-2">
      <LeadSourcePicker
        workspaceId={workspaceId}
        value={value}
        onChange={(leadSourceId) => onChange(leadSourceId)}
        onClear={onClear}
        allowClear={allowClear}
        id={id}
        aria-label={ariaLabel}
      />

      {isCreating ? (
        <div ref={panelRef} className="bg-muted/40 space-y-3 rounded-md border p-3">
          <div className="space-y-1.5">
            <Label htmlFor="new-lead-source-name">New lead source name</Label>
            <Input
              id="new-lead-source-name"
              ref={nameInputRef}
              placeholder="e.g. Nextdoor post"
              value={name}
              onChange={(event) => setName(event.target.value)}
              onKeyDown={(event) => {
                if (event.key !== "Enter") return;
                // Without this, Enter submits the contact form instead.
                event.preventDefault();
                submitNewSource();
              }}
            />
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="new-lead-source-channel">Channel</Label>
            <SourceTypePicker
              id="new-lead-source-channel"
              value={sourceType}
              onChange={setSourceType}
              aria-label="Channel for the new lead source"
            />
            <p className="text-muted-foreground text-xs">
              Groups this source in lead-source ROI reporting.
            </p>
          </div>

          <div className="flex justify-end gap-2">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              // The dialog's own Cancel is on screen at the same time; two
              // controls both announced as "Cancel" is ambiguous to anyone
              // navigating by button name.
              aria-label="Cancel new lead source"
              onClick={closePanel}
              disabled={createMutation.isPending}
            >
              Cancel
            </Button>
            <Button
              type="button"
              size="sm"
              onClick={submitNewSource}
              disabled={!name.trim() || createMutation.isPending}
            >
              {createMutation.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              {createMutation.isPending ? "Adding..." : "Add source"}
            </Button>
          </div>
        </div>
      ) : (
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="text-muted-foreground hover:text-foreground h-auto px-0 py-0 hover:bg-transparent"
          onClick={() => setIsCreating(true)}
        >
          <Plus aria-hidden="true" className="mr-1 h-3.5 w-3.5" />
          New lead source
        </Button>
      )}
    </div>
  );
}
