"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Wand2, Loader2, Sparkles } from "lucide-react";

import { improvementSuggestionsApi } from "@/lib/api/improvement-suggestions";
import { useWorkspaceId } from "@/hooks/use-workspace-id";
import { queryKeys } from "@/lib/query-keys";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Slider } from "@/components/ui/slider";
import { SuggestionsQueue } from "@/components/suggestions/suggestions-queue";

interface PromptImprovementDialogProps {
  agentId: string;
  agentName: string;
}

export function PromptImprovementDialog({
  agentId,
  agentName,
}: PromptImprovementDialogProps) {
  const workspaceId = useWorkspaceId();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [numSuggestions, setNumSuggestions] = useState(3);
  const [hasGenerated, setHasGenerated] = useState(false);

  const generateMutation = useMutation({
    mutationFn: () => {
      if (!workspaceId) throw new Error("No workspace");
      return improvementSuggestionsApi.generateForAgent(
        workspaceId,
        agentId,
        numSuggestions
      );
    },
    onSuccess: (suggestions) => {
      toast.success(`Generated ${suggestions.length} improvement suggestions`);
      setHasGenerated(true);
      void queryClient.invalidateQueries({ queryKey: queryKeys.improvementSuggestions.root() });
    },
    onError: (error: Error) => {
      toast.error(error.message || "Failed to generate suggestions");
    },
  });

  const handleOpenChange = (newOpen: boolean) => {
    setOpen(newOpen);
    if (!newOpen) {
      setHasGenerated(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm">
          <Wand2 className="mr-2 h-4 w-4" />
          Improve with AI
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Sparkles className="h-5 w-5 text-amber-500" />
            AI Prompt Improvement
          </DialogTitle>
          <DialogDescription>
            Generate AI-powered improvements for {agentName}&apos;s prompt based on call
            performance analysis.
          </DialogDescription>
        </DialogHeader>

        {!hasGenerated ? (
          <div className="space-y-6 py-4">
            <div className="space-y-4">
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <Label>Number of Suggestions</Label>
                  <span className="text-sm font-medium">{numSuggestions}</span>
                </div>
                <Slider
                  value={[numSuggestions]}
                  onValueChange={([v]) => setNumSuggestions(v)}
                  min={1}
                  max={5}
                  step={1}
                  className="w-full"
                />
                <p className="text-xs text-muted-foreground">
                  Generate between 1 and 5 different improvement suggestions
                </p>
              </div>

              <div className="rounded-lg border bg-muted/50 p-4">
                <h4 className="mb-2 font-medium">How it works</h4>
                <ul className="space-y-2 text-sm text-muted-foreground">
                  <li className="flex items-start gap-2">
                    <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-medium text-primary">
                      1
                    </span>
                    AI analyzes your recent call outcomes to identify patterns
                  </li>
                  <li className="flex items-start gap-2">
                    <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-medium text-primary">
                      2
                    </span>
                    Identifies strengths, weaknesses, and areas for improvement
                  </li>
                  <li className="flex items-start gap-2">
                    <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-medium text-primary">
                      3
                    </span>
                    Generates targeted prompt variations to test via A/B testing
                  </li>
                </ul>
              </div>
            </div>

            <Button
              onClick={() => generateMutation.mutate()}
              disabled={generateMutation.isPending}
              className="w-full"
            >
              {generateMutation.isPending ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Analyzing performance...
                </>
              ) : (
                <>
                  <Wand2 className="mr-2 h-4 w-4" />
                  Generate Suggestions
                </>
              )}
            </Button>
          </div>
        ) : (
          <div className="space-y-4 py-4">
            <div className="rounded-lg border border-success/20 bg-success/10 p-4">
              <p className="text-sm text-success">
                Suggestions generated! Review them below or from the Suggestions page.
              </p>
            </div>

            <SuggestionsQueue agentId={agentId} statusFilter="pending" compact />

            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={() => setHasGenerated(false)}>
                Generate More
              </Button>
              <Button onClick={() => setOpen(false)}>Done</Button>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
