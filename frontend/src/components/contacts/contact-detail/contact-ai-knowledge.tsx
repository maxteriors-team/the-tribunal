"use client";

import {
  AlertTriangle,
  BrainCircuit,
  Clock3,
  Database,
  Pencil,
  ShieldCheck,
  Sparkles,
  Trash2,
} from "lucide-react";
import { type MouseEvent, useState } from "react";
import { toast } from "sonner";

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
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { PageEmptyState, PageErrorState, PageLoadingState } from "@/components/ui/page-state";
import { Textarea } from "@/components/ui/textarea";
import {
  useContactAIKnowledge,
  useUpdateContactAIMemoryFact,
  useUpdateContactAIMemorySummary,
} from "@/hooks/useContacts";
import type { ContactAIMemoryFact, ContactAIMemorySummary } from "@/lib/api/contacts";
import { formatDateTime, formatRelative } from "@/lib/utils/date";

interface ContactAIKnowledgeProps {
  workspaceId: string;
  contactId: number;
  canEditMemory: boolean;
}

type MemoryTarget =
  | { kind: "summary"; label: string; value: string }
  | { kind: "fact"; factId: string; label: string; value: string };

function Freshness({ date, prefix }: { date: string; prefix: string }) {
  return (
    <time dateTime={date} title={formatDateTime(date)}>
      {prefix} {formatRelative(date)}
    </time>
  );
}

function MemoryMetadata({ memory }: { memory: ContactAIMemorySummary | ContactAIMemoryFact }) {
  return (
    <p className="text-muted-foreground mt-2 flex flex-wrap items-center gap-x-1.5 gap-y-1 text-xs">
      <span>{memory.source}</span>
      <span aria-hidden="true">·</span>
      <Freshness date={memory.observed_at} prefix="Learned" />
      {memory.expires_at ? (
        <>
          <span aria-hidden="true">·</span>
          <Freshness date={memory.expires_at} prefix="Expires" />
        </>
      ) : null}
    </p>
  );
}

function MemoryActions({
  label,
  onCorrect,
  onRemove,
}: {
  label: string;
  onCorrect: (event: MouseEvent<HTMLButtonElement>) => void;
  onRemove: (event: MouseEvent<HTMLButtonElement>) => void;
}) {
  return (
    <div className="flex shrink-0 items-center gap-1">
      <Button
        type="button"
        variant="ghost"
        size="icon"
        className="h-8 w-8"
        aria-label={`Correct generated memory: ${label}`}
        onClick={onCorrect}
      >
        <Pencil className="h-4 w-4" aria-hidden="true" />
      </Button>
      <Button
        type="button"
        variant="ghost"
        size="icon"
        className="text-destructive hover:text-destructive h-8 w-8"
        aria-label={`Remove generated memory: ${label}`}
        onClick={onRemove}
      >
        <Trash2 className="h-4 w-4" aria-hidden="true" />
      </Button>
    </div>
  );
}

export function ContactAIKnowledge({
  workspaceId,
  contactId,
  canEditMemory,
}: ContactAIKnowledgeProps) {
  const knowledgeQuery = useContactAIKnowledge(workspaceId, contactId);
  const summaryMutation = useUpdateContactAIMemorySummary(workspaceId, contactId);
  const factMutation = useUpdateContactAIMemoryFact(workspaceId, contactId);
  const [editTarget, setEditTarget] = useState<MemoryTarget | null>(null);
  const [removeTarget, setRemoveTarget] = useState<MemoryTarget | null>(null);
  const [draft, setDraft] = useState("");
  const [editTrigger, setEditTrigger] = useState<HTMLButtonElement | null>(null);
  const [removeTrigger, setRemoveTrigger] = useState<HTMLButtonElement | null>(null);

  const isSaving = summaryMutation.isPending || factMutation.isPending;

  const restoreFocus = (target: "edit" | "remove") => {
    const trigger = target === "edit" ? editTrigger : removeTrigger;
    window.requestAnimationFrame(() => {
      if (trigger?.isConnected) {
        trigger.focus();
      } else {
        document.getElementById("generated-memory-title")?.focus();
      }
    });
  };

  const closeEditor = () => {
    setEditTarget(null);
    restoreFocus("edit");
  };

  const closeRemoval = () => {
    setRemoveTarget(null);
    restoreFocus("remove");
  };

  const openEditor = (event: MouseEvent<HTMLButtonElement>, target: MemoryTarget) => {
    setEditTrigger(event.currentTarget);
    setDraft(target.value);
    setEditTarget(target);
  };

  const openRemoval = (event: MouseEvent<HTMLButtonElement>, target: MemoryTarget) => {
    setRemoveTrigger(event.currentTarget);
    setRemoveTarget(target);
  };

  const saveCorrection = async () => {
    if (!editTarget || !draft.trim()) return;
    try {
      if (editTarget.kind === "summary") {
        await summaryMutation.mutateAsync(draft.trim());
      } else {
        await factMutation.mutateAsync({ factId: editTarget.factId, value: draft.trim() });
      }
      toast.success("AI memory corrected");
      closeEditor();
    } catch {
      toast.error("AI memory could not be corrected");
    }
  };

  const removeMemory = async () => {
    if (!removeTarget) return;
    try {
      if (removeTarget.kind === "summary") {
        await summaryMutation.mutateAsync(null);
      } else {
        await factMutation.mutateAsync({ factId: removeTarget.factId, value: null });
      }
      toast.success("Generated memory removed");
      closeRemoval();
    } catch {
      toast.error("Generated memory could not be removed");
    }
  };

  const knowledge = knowledgeQuery.data;
  const structuredFacts = knowledge?.structured_facts ?? [];
  const memoryFacts = knowledge?.memory_facts ?? [];
  const conflicts = knowledge?.conflicts ?? [];
  const hasGeneratedMemory = Boolean(knowledge?.memory_summary) || memoryFacts.length > 0;

  return (
    <>
      <Card>
        <section aria-labelledby="contact-ai-knowledge-title">
          <CardHeader className="border-b pb-4">
            <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-start">
              <div className="flex gap-3">
                <div className="bg-primary/10 text-primary flex h-9 w-9 shrink-0 items-center justify-center rounded-lg">
                  <BrainCircuit className="h-5 w-5" aria-hidden="true" />
                </div>
                <div>
                  <CardTitle>
                    <h2 id="contact-ai-knowledge-title">What AI knows</h2>
                  </CardTitle>
                  <CardDescription className="mt-1">
                    Current CRM context and generated memory used for this contact.
                  </CardDescription>
                </div>
              </div>
              <Badge variant="outline" className="w-fit gap-1.5 whitespace-nowrap">
                <ShieldCheck className="h-3.5 w-3.5" aria-hidden="true" />
                CRM facts are read-only
              </Badge>
            </div>
            <p className="text-muted-foreground text-xs">
              Corrections here change generated AI memory only. Contact details, pipeline,
              appointments, quotes, and invoices stay unchanged.
            </p>
          </CardHeader>

          <CardContent className="pt-5">
            {knowledgeQuery.isLoading ? (
              <PageLoadingState
                className="min-h-[220px]"
                message="Loading AI knowledge"
                aria-label="Loading AI knowledge"
              />
            ) : knowledgeQuery.isError ? (
              <PageErrorState
                className="min-h-[220px]"
                message="AI knowledge could not load. The contact is still available; retry this section."
                retryLabel="Retry"
                onRetry={() => void knowledgeQuery.refetch()}
              />
            ) : knowledge ? (
              <div className="space-y-6">
                <p className="text-muted-foreground flex items-center gap-1.5 text-xs">
                  <Clock3 className="h-3.5 w-3.5" aria-hidden="true" />
                  <Freshness date={knowledge.generated_at} prefix="Context refreshed" />
                </p>

                {conflicts.length > 0 ? (
                  <section
                    aria-labelledby="ai-conflicts-title"
                    className="border-warning/40 bg-warning/5 rounded-lg border p-4"
                  >
                    <div className="flex items-start gap-2.5">
                      <AlertTriangle
                        className="text-warning mt-0.5 h-4 w-4 shrink-0"
                        aria-hidden="true"
                      />
                      <div className="min-w-0 flex-1">
                        <h3 id="ai-conflicts-title" className="text-sm font-medium">
                          Conflicts need review
                        </h3>
                        <p className="text-muted-foreground mt-1 text-xs">
                          Current CRM values take priority over generated memory.
                        </p>
                        <ul className="mt-3 space-y-3">
                          {conflicts.map((conflict) => (
                            <li
                              key={conflict.fact_id}
                              className="bg-background rounded-md border p-3"
                            >
                              <div className="flex items-start justify-between gap-3">
                                <div className="min-w-0">
                                  <p className="text-sm font-medium">{conflict.label}</p>
                                  <dl className="mt-2 grid gap-1 text-xs sm:grid-cols-2">
                                    <div>
                                      <dt className="text-muted-foreground">Current CRM</dt>
                                      <dd className="mt-0.5 break-words font-medium">
                                        {conflict.authoritative_value}
                                      </dd>
                                    </div>
                                    <div>
                                      <dt className="text-muted-foreground">Generated memory</dt>
                                      <dd className="mt-0.5 break-words">
                                        {conflict.generated_value}
                                      </dd>
                                    </div>
                                  </dl>
                                </div>
                                {canEditMemory
                                  ? (() => {
                                      const fact = memoryFacts.find(
                                        (memoryFact) => memoryFact.id === conflict.fact_id,
                                      );
                                      return fact ? (
                                        <Button
                                          type="button"
                                          variant="outline"
                                          size="sm"
                                          aria-label={`Correct conflict: ${conflict.label}`}
                                          onClick={(event) =>
                                            openEditor(event, {
                                              kind: "fact",
                                              factId: fact.id,
                                              label: fact.label,
                                              value: fact.value,
                                            })
                                          }
                                        >
                                          Correct
                                        </Button>
                                      ) : null;
                                    })()
                                  : null}
                              </div>
                            </li>
                          ))}
                        </ul>
                      </div>
                    </div>
                  </section>
                ) : null}

                <div className="grid gap-5 lg:grid-cols-2">
                  <section aria-labelledby="structured-facts-title">
                    <div className="mb-3 flex items-center gap-2">
                      <Database className="text-muted-foreground h-4 w-4" aria-hidden="true" />
                      <h3 id="structured-facts-title" className="text-sm font-medium">
                        Current structured facts
                      </h3>
                    </div>
                    {structuredFacts.length > 0 ? (
                      <dl className="divide-y rounded-lg border px-4">
                        {structuredFacts.map((fact) => (
                          <div key={fact.key} className="py-3">
                            <dt className="text-muted-foreground text-xs">{fact.label}</dt>
                            <dd className="mt-0.5 break-words text-sm font-medium">{fact.value}</dd>
                            <p className="text-muted-foreground mt-1 text-xs">
                              {fact.source}
                              <span aria-hidden="true"> · </span>
                              <Freshness date={fact.observed_at} prefix="Updated" />
                            </p>
                          </div>
                        ))}
                      </dl>
                    ) : (
                      <PageEmptyState
                        className="min-h-0 py-8"
                        icon={<Database className="size-8" aria-hidden="true" />}
                        title="No structured facts yet"
                        description="CRM activity will appear here when it is available."
                      />
                    )}
                  </section>

                  <section aria-labelledby="next-action-title">
                    <div className="mb-3 flex items-center gap-2">
                      <Sparkles className="text-muted-foreground h-4 w-4" aria-hidden="true" />
                      <h3 id="next-action-title" className="text-sm font-medium">
                        Next action
                      </h3>
                    </div>
                    {knowledge.next_action ? (
                      <div className="bg-muted/30 rounded-lg border p-4">
                        <p className="font-medium">{knowledge.next_action.value}</p>
                        <p className="text-muted-foreground mt-2 text-xs">
                          {knowledge.next_action.source}
                          <span aria-hidden="true"> · </span>
                          <Freshness
                            date={knowledge.next_action.observed_at}
                            prefix="Based on data updated"
                          />
                          {knowledge.next_action.due_at ? (
                            <>
                              <span aria-hidden="true"> · </span>
                              <Freshness date={knowledge.next_action.due_at} prefix="Due" />
                            </>
                          ) : null}
                        </p>
                      </div>
                    ) : (
                      <PageEmptyState
                        className="min-h-0 py-8"
                        icon={<Sparkles className="size-8" aria-hidden="true" />}
                        title="No next action"
                        description="There is no current CRM event requiring action."
                      />
                    )}
                  </section>
                </div>

                <section aria-labelledby="generated-memory-title" className="border-t pt-5">
                  <div className="mb-3 flex items-center gap-2">
                    <BrainCircuit className="text-muted-foreground h-4 w-4" aria-hidden="true" />
                    <h3
                      id="generated-memory-title"
                      className="text-sm font-medium"
                      tabIndex={-1}
                    >
                      Generated memory
                    </h3>
                  </div>

                  {!hasGeneratedMemory ? (
                    <PageEmptyState
                      className="min-h-0 py-8"
                      icon={<BrainCircuit className="size-8" aria-hidden="true" />}
                      title="No generated memory yet"
                      description="AI-learned summaries and facts will appear after eligible conversations."
                    />
                  ) : (
                    <div className="space-y-3">
                      {knowledge.memory_summary ? (
                        <article className="bg-muted/30 rounded-lg border p-4">
                          <div className="flex items-start justify-between gap-3">
                            <div className="min-w-0">
                              <p className="text-xs font-medium tracking-wide uppercase">
                                Memory summary
                              </p>
                              <p className="mt-2 whitespace-pre-wrap break-words text-sm">
                                {knowledge.memory_summary.value}
                              </p>
                              <MemoryMetadata memory={knowledge.memory_summary} />
                            </div>
                            {canEditMemory ? (
                              <MemoryActions
                                label="Memory summary"
                                onCorrect={(event) =>
                                  openEditor(event, {
                                    kind: "summary",
                                    label: "Memory summary",
                                    value: knowledge.memory_summary?.value ?? "",
                                  })
                                }
                                onRemove={(event) =>
                                  openRemoval(event, {
                                    kind: "summary",
                                    label: "Memory summary",
                                    value: knowledge.memory_summary?.value ?? "",
                                  })
                                }
                              />
                            ) : null}
                          </div>
                        </article>
                      ) : null}

                      {memoryFacts.length > 0 ? (
                        <ul className="grid gap-3 sm:grid-cols-2">
                          {memoryFacts.map((fact) => (
                            <li key={fact.id} className="rounded-lg border p-4">
                              <div className="flex items-start justify-between gap-3">
                                <div className="min-w-0">
                                  <div className="flex flex-wrap items-center gap-2">
                                    <p className="text-sm font-medium">{fact.label}</p>
                                    <Badge variant="secondary" className="font-normal">
                                      {Math.round(fact.confidence * 100)}% confidence
                                    </Badge>
                                  </div>
                                  <p className="mt-2 whitespace-pre-wrap break-words text-sm">
                                    {fact.value}
                                  </p>
                                  <MemoryMetadata memory={fact} />
                                </div>
                                {canEditMemory ? (
                                  <MemoryActions
                                    label={fact.label}
                                    onCorrect={(event) =>
                                      openEditor(event, {
                                        kind: "fact",
                                        factId: fact.id,
                                        label: fact.label,
                                        value: fact.value,
                                      })
                                    }
                                    onRemove={(event) =>
                                      openRemoval(event, {
                                        kind: "fact",
                                        factId: fact.id,
                                        label: fact.label,
                                        value: fact.value,
                                      })
                                    }
                                  />
                                ) : null}
                              </div>
                            </li>
                          ))}
                        </ul>
                      ) : null}
                    </div>
                  )}
                </section>
              </div>
            ) : (
              <PageEmptyState
                className="min-h-[220px]"
                icon={<BrainCircuit className="size-8" aria-hidden="true" />}
                title="No AI knowledge available"
                description="This contact has no context snapshot yet."
              />
            )}
          </CardContent>
        </section>
      </Card>

      <Dialog
        open={editTarget !== null}
        onOpenChange={(open) => {
          if (!open) closeEditor();
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Correct {editTarget?.label ?? "generated memory"}</DialogTitle>
            <DialogDescription>
              This changes generated AI memory only. It does not edit the contact or any other CRM
              record.
            </DialogDescription>
          </DialogHeader>
          <form
            onSubmit={(event) => {
              event.preventDefault();
              void saveCorrection();
            }}
          >
            <div className="space-y-2">
              <Label htmlFor="ai-memory-correction">Corrected memory</Label>
              <Textarea
                id="ai-memory-correction"
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                maxLength={1000}
                rows={5}
                aria-describedby="ai-memory-correction-help"
              />
              <p id="ai-memory-correction-help" className="text-muted-foreground text-xs">
                Use only context the AI should remember; update authoritative details elsewhere.
              </p>
            </div>
            <DialogFooter className="mt-5">
              <Button type="button" variant="outline" onClick={closeEditor} disabled={isSaving}>
                Cancel
              </Button>
              <Button type="submit" disabled={isSaving || !draft.trim()}>
                {isSaving ? "Saving…" : "Save correction"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <AlertDialog
        open={removeTarget !== null}
        onOpenChange={(open) => {
          if (!open) closeRemoval();
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Remove {removeTarget?.label ?? "generated memory"}?</AlertDialogTitle>
            <AlertDialogDescription>
              This removes generated AI memory only. Contact details, pipeline, appointments,
              quotes, invoices, and other authoritative CRM records stay unchanged.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={isSaving}>Keep memory</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              disabled={isSaving}
              onClick={() => void removeMemory()}
            >
              {isSaving ? "Removing…" : "Remove generated memory"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
