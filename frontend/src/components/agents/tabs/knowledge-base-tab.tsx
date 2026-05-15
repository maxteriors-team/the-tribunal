"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { formatRelative } from "@/lib/utils/date";
import { formatNumber } from "@/lib/utils/number";
import { Loader2, Plus, Trash2, BookOpen, FileText } from "lucide-react";

import { knowledgeDocumentsApi } from "@/lib/api/knowledge-documents";
import type { KnowledgeDocumentCreate } from "@/types/knowledge-document";
import { useWorkspaceId } from "@/hooks/use-workspace-id";
import { queryKeys } from "@/lib/query-keys";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
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
import { getApiErrorMessage } from "@/lib/utils/errors";

const DOC_TYPES = [
  { value: "general", label: "General" },
  { value: "faq", label: "FAQ" },
  { value: "policy", label: "Policy" },
  { value: "script", label: "Script" },
  { value: "product", label: "Product Info" },
  { value: "persona", label: "Persona" },
];

const DOC_TYPE_STYLES: Record<string, string> = {
  general: "bg-gray-100 text-gray-800 dark:bg-gray-800 dark:text-gray-200",
  faq: "bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200",
  policy: "bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-200",
  script: "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200",
  product: "bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-200",
  persona: "bg-pink-100 text-pink-800 dark:bg-pink-900 dark:text-pink-200",
};

interface KnowledgeBaseTabProps {
  agentId: string;
}

export function KnowledgeBaseTab({ agentId }: KnowledgeBaseTabProps) {
  const workspaceId = useWorkspaceId();
  const queryClient = useQueryClient();
  const [showAddDialog, setShowAddDialog] = useState(false);
  const [newTitle, setNewTitle] = useState("");
  const [newContent, setNewContent] = useState("");
  const [newDocType, setNewDocType] = useState("general");
  const [newPriority, setNewPriority] = useState(0);

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
      resetForm();
    },
    onError: (err: unknown) =>
      toast.error(getApiErrorMessage(err, "Failed to add document")),
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
    onError: (err: unknown) =>
      toast.error(getApiErrorMessage(err, "Failed to delete document")),
  });

  const resetForm = () => {
    setShowAddDialog(false);
    setNewTitle("");
    setNewContent("");
    setNewDocType("general");
    setNewPriority(0);
  };

  const handleCreate = () => {
    if (!newTitle.trim() || !newContent.trim()) {
      toast.error("Title and content are required");
      return;
    }
    createMutation.mutate({
      title: newTitle,
      content: newContent,
      doc_type: newDocType,
      priority: newPriority,
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
          <div className="flex items-center justify-between">
            <div>
              <CardTitle>Knowledge Base</CardTitle>
              <CardDescription>
                Documents that give your agent context and expertise
              </CardDescription>
            </div>
            <Button onClick={() => setShowAddDialog(true)}>
              <Plus className="mr-2 h-4 w-4" />
              Add Document
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          <div className="space-y-2">
            <div className="flex items-center justify-between text-sm">
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
              Add documents to give your agent knowledge about your business, products, and processes.
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
                  <div className="flex items-start justify-between gap-2">
                    <h3 className="font-medium leading-tight">{doc.title}</h3>
                    <div className="flex shrink-0 items-center gap-1.5">
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
                  <p className="line-clamp-2 text-sm text-muted-foreground">
                    {doc.content}
                  </p>
                  <p className="text-xs text-muted-foreground">
                    Added{" "}
                    {formatRelative(doc.created_at)}
                  </p>
                </div>
                <AlertDialog>
                  <AlertDialogTrigger asChild>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-8 w-8 shrink-0 text-muted-foreground hover:text-destructive"
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </AlertDialogTrigger>
                  <AlertDialogContent>
                    <AlertDialogHeader>
                      <AlertDialogTitle>Delete document?</AlertDialogTitle>
                      <AlertDialogDescription>
                        This will permanently remove &ldquo;{doc.title}&rdquo; from the
                        knowledge base.
                      </AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                      <AlertDialogCancel>Cancel</AlertDialogCancel>
                      <AlertDialogAction
                        onClick={() => deleteMutation.mutate(doc.id)}
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
      <Dialog open={showAddDialog} onOpenChange={setShowAddDialog}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>Add Knowledge Document</DialogTitle>
            <DialogDescription>
              Add a document to your agent&apos;s knowledge base. This content will be available
              during conversations.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="doc-title">Title</Label>
              <Input
                id="doc-title"
                value={newTitle}
                onChange={(e) => setNewTitle(e.target.value)}
                placeholder="e.g. Company FAQ"
              />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label>Document Type</Label>
                <Select value={newDocType} onValueChange={setNewDocType}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {DOC_TYPES.map((dt) => (
                      <SelectItem key={dt.value} value={dt.value}>
                        {dt.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label htmlFor="doc-priority">Priority (0 = default)</Label>
                <Input
                  id="doc-priority"
                  type="number"
                  min={0}
                  max={100}
                  value={newPriority}
                  onChange={(e) => {
                    const val = parseInt(e.target.value, 10);
                    if (!isNaN(val)) setNewPriority(val);
                  }}
                />
              </div>
            </div>
            <div className="space-y-2">
              <Label htmlFor="doc-content">Content</Label>
              <Textarea
                id="doc-content"
                value={newContent}
                onChange={(e) => setNewContent(e.target.value)}
                placeholder="Enter the document content..."
                rows={10}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={resetForm}>
              Cancel
            </Button>
            <Button onClick={handleCreate} disabled={createMutation.isPending}>
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
        </DialogContent>
      </Dialog>
    </div>
  );
}
