"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2, Plus, Trash2, BookOpen, FileText } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import * as z from "zod";

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
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
import { Textarea } from "@/components/ui/textarea";
import { useCapabilities } from "@/hooks/useCapabilities";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import { knowledgeDocumentsApi } from "@/lib/api/knowledge-documents";
import { queryKeys } from "@/lib/query-keys";
import { formatRelative } from "@/lib/utils/date";
import { getApiErrorMessage } from "@/lib/utils/errors";
import { formatNumber } from "@/lib/utils/number";
import type { KnowledgeDocumentCreate } from "@/types/knowledge-document";

const DOC_TYPES = [
  { value: "general", label: "General" },
  { value: "faq", label: "FAQ" },
  { value: "policy", label: "Policy" },
  { value: "script", label: "Script" },
  { value: "product", label: "Product Info" },
  { value: "persona", label: "Persona" },
] as const;

const DOC_TYPE_STYLES: Record<string, string> = {
  general: "bg-gray-100 text-gray-800 dark:bg-gray-800 dark:text-gray-200",
  faq: "bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200",
  policy: "bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-200",
  script: "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200",
  product: "bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-200",
  persona: "bg-pink-100 text-pink-800 dark:bg-pink-900 dark:text-pink-200",
};

const docFormSchema = z.object({
  title: z.string().min(1, { error: "Title is required" }).max(255),
  content: z.string().min(1, { error: "Content is required" }),
  doc_type: z.enum(["general", "faq", "policy", "script", "product", "persona"]),
  priority: z
    .number()
    .int()
    .min(0, { error: "Priority must be at least 0" })
    .max(100, { error: "Priority must be at most 100" }),
});

type DocFormValues = z.infer<typeof docFormSchema>;

const defaultDocValues: DocFormValues = {
  title: "",
  content: "",
  doc_type: "general",
  priority: 0,
};

interface KnowledgeBaseTabProps {
  agentId: string;
}

export function KnowledgeBaseTab({ agentId }: KnowledgeBaseTabProps) {
  const workspaceId = useWorkspaceId();
  const { can } = useCapabilities();
  const canManageKnowledge = can("workspace:manage");
  const queryClient = useQueryClient();
  const [showAddDialog, setShowAddDialog] = useState(false);

  const form = useForm<DocFormValues>({
    resolver: zodResolver(docFormSchema),
    defaultValues: defaultDocValues,
  });

  const { data: docList, isPending } = useQuery({
    queryKey: queryKeys.agents.knowledgeDocs(workspaceId ?? "", agentId),
    queryFn: () => {
      if (!workspaceId) throw new Error("No workspace");
      return knowledgeDocumentsApi.list(workspaceId, agentId);
    },
    enabled: !!workspaceId,
  });

  const createMutation = useMutation({
    mutationFn: (data: KnowledgeDocumentCreate) => {
      if (!workspaceId) throw new Error("No workspace");
      return knowledgeDocumentsApi.create(workspaceId, agentId, data);
    },
    onSuccess: () => {
      toast.success("Document added");
      void queryClient.invalidateQueries({
        queryKey: queryKeys.agents.knowledgeDocs(workspaceId ?? "", agentId),
      });
      closeDialog();
    },
    onError: (err: unknown) => toast.error(getApiErrorMessage(err, "Failed to add document")),
  });

  const deleteMutation = useMutation({
    mutationFn: (documentId: string) => {
      if (!workspaceId) throw new Error("No workspace");
      return knowledgeDocumentsApi.remove(workspaceId, agentId, documentId);
    },
    onSuccess: () => {
      toast.success("Document deleted");
      void queryClient.invalidateQueries({
        queryKey: queryKeys.agents.knowledgeDocs(workspaceId ?? "", agentId),
      });
    },
    onError: (err: unknown) => toast.error(getApiErrorMessage(err, "Failed to delete document")),
  });

  const closeDialog = () => {
    setShowAddDialog(false);
    form.reset(defaultDocValues);
  };

  const handleCreate = (data: DocFormValues) => {
    if (!canManageKnowledge) return;
    createMutation.mutate({
      title: data.title,
      content: data.content,
      doc_type: data.doc_type,
      priority: data.priority,
    });
  };

  if (isPending) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="size-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  const totalTokens = docList?.total_tokens ?? 0;
  const tokenBudget = docList?.token_budget ?? 128000;
  const tokenPercent = tokenBudget > 0 ? Math.min((totalTokens / tokenBudget) * 100, 100) : 0;

  return (
    <div className="space-y-6">
      {/* Token Budget */}
      <Card>
        <CardHeader>
          <div className="flex flex-col items-start gap-4 sm:flex-row sm:items-center sm:justify-between">
            <div className="min-w-0">
              <CardTitle>Knowledge Base</CardTitle>
              <CardDescription>
                Documents that give your agent context and expertise
              </CardDescription>
            </div>
            <Button
              className="w-full sm:w-auto"
              onClick={() => setShowAddDialog(true)}
              disabled={!canManageKnowledge}
            >
              <Plus className="mr-2 h-4 w-4" />
              Add Document
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          <div className="space-y-2">
            <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
              <span className="text-muted-foreground">Token usage</span>
              <span className="font-medium">
                {formatNumber(totalTokens)} / {formatNumber(tokenBudget)} tokens
              </span>
            </div>
            <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
              <div
                className={`h-full rounded-full transition-all ${
                  tokenPercent > 90
                    ? "bg-red-500"
                    : tokenPercent > 70
                      ? "bg-yellow-500"
                      : "bg-green-500"
                }`}
                style={{ width: `${tokenPercent}%` }}
              />
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Document List */}
      {!docList?.items.length ? (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-12 text-center">
            <BookOpen className="mb-4 h-12 w-12 text-muted-foreground" />
            <h3 className="mb-2 text-lg font-semibold">No Documents</h3>
            <p className="max-w-sm text-sm text-muted-foreground">
              Add documents to give your agent knowledge about your business, products, and
              processes.
            </p>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-3">
          {docList.items.map((doc) => (
            <Card key={doc.id}>
              <CardContent className="flex items-start gap-4 p-4">
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-muted">
                  <FileText className="h-5 w-5 text-muted-foreground" />
                </div>
                <div className="min-w-0 flex-1 space-y-1">
                  <div className="flex flex-col items-start gap-2 sm:flex-row sm:justify-between">
                    <h3 className="break-words font-medium leading-tight">{doc.title}</h3>
                    <div className="flex max-w-full flex-wrap items-center gap-1.5">
                      <Badge
                        className={`text-xs ${DOC_TYPE_STYLES[doc.doc_type] || DOC_TYPE_STYLES.general}`}
                      >
                        {doc.doc_type}
                      </Badge>
                      <Badge variant="outline" className="text-xs">
                        {formatNumber(doc.token_count)} tokens
                      </Badge>
                      {doc.priority > 0 && (
                        <Badge variant="secondary" className="text-xs">
                          Priority: {doc.priority}
                        </Badge>
                      )}
                    </div>
                  </div>
                  <p className="line-clamp-2 text-sm text-muted-foreground">{doc.content}</p>
                  <p className="text-xs text-muted-foreground">
                    Added {formatRelative(doc.created_at)}
                  </p>
                </div>
                <AlertDialog>
                  <AlertDialogTrigger asChild>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-8 w-8 shrink-0 text-muted-foreground hover:text-destructive"
                      disabled={!canManageKnowledge}
                      aria-label={`Delete ${doc.title}`}
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </AlertDialogTrigger>
                  <AlertDialogContent>
                    <AlertDialogHeader>
                      <AlertDialogTitle>Delete document?</AlertDialogTitle>
                      <AlertDialogDescription>
                        This will permanently remove &ldquo;{doc.title}&rdquo; from the knowledge
                        base.
                      </AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                      <AlertDialogCancel>Cancel</AlertDialogCancel>
                      <AlertDialogAction
                        onClick={() => deleteMutation.mutate(doc.id)}
                        disabled={!canManageKnowledge || deleteMutation.isPending}
                        className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
                      >
                        Delete
                      </AlertDialogAction>
                    </AlertDialogFooter>
                  </AlertDialogContent>
                </AlertDialog>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {/* Add Document Dialog */}
      <Dialog
        open={canManageKnowledge && showAddDialog}
        onOpenChange={(open) => {
          if (!open) closeDialog();
          else setShowAddDialog(true);
        }}
      >
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>Add Knowledge Document</DialogTitle>
            <DialogDescription>
              Add a document to your agent&apos;s knowledge base. This content will be available
              during conversations.
            </DialogDescription>
          </DialogHeader>
          <Form {...form}>
            <form onSubmit={form.handleSubmit(handleCreate)} className="space-y-4">
              <FormField
                control={form.control}
                name="title"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Title</FormLabel>
                    <FormControl>
                      <Input placeholder="e.g. Company FAQ" {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <div className="grid grid-cols-2 gap-4">
                <FormField
                  control={form.control}
                  name="doc_type"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Document Type</FormLabel>
                      <Select value={field.value} onValueChange={field.onChange}>
                        <FormControl>
                          <SelectTrigger aria-label="Document type">
                            <SelectValue />
                          </SelectTrigger>
                        </FormControl>
                        <SelectContent>
                          {DOC_TYPES.map((dt) => (
                            <SelectItem key={dt.value} value={dt.value}>
                              {dt.label}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                      <FormMessage />
                    </FormItem>
                  )}
                />
                <FormField
                  control={form.control}
                  name="priority"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Priority (0 = default)</FormLabel>
                      <FormControl>
                        <Input
                          type="number"
                          min={0}
                          max={100}
                          value={field.value}
                          onChange={(e) => {
                            const val = parseInt(e.target.value, 10);
                            field.onChange(isNaN(val) ? 0 : val);
                          }}
                        />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              </div>
              <FormField
                control={form.control}
                name="content"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Content</FormLabel>
                    <FormControl>
                      <Textarea placeholder="Enter the document content..." rows={10} {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <DialogFooter>
                <Button type="button" variant="outline" onClick={closeDialog}>
                  Cancel
                </Button>
                <Button type="submit" disabled={!canManageKnowledge || createMutation.isPending}>
                  {createMutation.isPending ? (
                    <>
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                      Adding...
                    </>
                  ) : (
                    "Add Document"
                  )}
                </Button>
              </DialogFooter>
            </form>
          </Form>
        </DialogContent>
      </Dialog>
    </div>
  );
}
