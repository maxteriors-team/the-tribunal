"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { FileText, AlertCircle, CheckCircle2, X, Download, Loader2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { FileDropzone } from "@/components/shared/file-dropzone";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import {
  contactsApi,
  type ImportResult,
  type ImportOptions,
  type CSVPreviewResult,
} from "@/lib/api/contacts";
import { queryKeys } from "@/lib/query-keys";
import { cn } from "@/lib/utils";
import { getApiErrorMessage } from "@/lib/utils/errors";

interface ImportContactsDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

type ImportStep = "upload" | "mapping" | "options" | "importing" | "results";

const SKIP_VALUE = "__skip__";

export function ImportContactsDialog({ open, onOpenChange }: ImportContactsDialogProps) {
  const queryClient = useQueryClient();
  const workspaceId = useWorkspaceId();

  const [step, setStep] = useState<ImportStep>("upload");
  const [file, setFile] = useState<File | null>(null);
  const [options, setOptions] = useState<ImportOptions>({
    skip_duplicates: true,
    default_status: "new",
    source: "csv_import",
  });
  const [result, setResult] = useState<ImportResult | null>(null);
  const [preview, setPreview] = useState<CSVPreviewResult | null>(null);
  const [columnMapping, setColumnMapping] = useState<Record<string, string | null>>({});
  const [previewLoading, setPreviewLoading] = useState(false);

  const isMappingValid = (): boolean => {
    const mappedFields = new Set(
      Object.values(columnMapping).filter((v): v is string => v !== null && v !== SKIP_VALUE)
    );
    return mappedFields.has("first_name") && mappedFields.has("phone_number");
  };

  const importMutation = useMutation({
    mutationFn: async () => {
      if (!workspaceId || !file) throw new Error("Missing workspace or file");
      // Build column_mapping from columnMapping state (filter out skips/nulls)
      const mapping: Record<string, string> = {};
      for (const [csvHeader, fieldName] of Object.entries(columnMapping)) {
        if (fieldName && fieldName !== SKIP_VALUE) {
          mapping[csvHeader] = fieldName;
        }
      }
      return contactsApi.importCSV(workspaceId, file, {
        ...options,
        column_mapping: Object.keys(mapping).length > 0 ? mapping : undefined,
      });
    },
    onSuccess: (data) => {
      setResult(data);
      setStep("results");
      queryClient.invalidateQueries({ queryKey: queryKeys.contacts.all(workspaceId ?? "") });
      if (data.successful > 0) {
        toast.success(`Successfully imported ${data.successful} contacts`);
      }
    },
    onError: (error) => {
      toast.error(getApiErrorMessage(error, "Failed to import contacts. Please check your CSV file."));
      setStep("options");
    },
  });

  const handleFileSelect = async (selectedFile: File) => {
    setFile(selectedFile);

    if (!workspaceId) return;

    setPreviewLoading(true);
    setStep("mapping");
    try {
      const previewResult = await contactsApi.previewCSV(workspaceId, selectedFile);
      setPreview(previewResult);
      setColumnMapping(previewResult.suggested_mapping);
    } catch {
      toast.error("Failed to preview CSV file. Please check the file format.");
      setStep("upload");
      setFile(null);
    } finally {
      setPreviewLoading(false);
    }
  };

  const handleStartImport = () => {
    setStep("importing");
    importMutation.mutate();
  };

  const handleClose = () => {
    setStep("upload");
    setFile(null);
    setResult(null);
    setPreview(null);
    setColumnMapping({});
    onOpenChange(false);
  };

  const handleDownloadTemplate = () => {
    const csvContent = "first_name,last_name,phone_number,email,company_name,status,tags,notes\nJohn,Doe,+15551234567,john@example.com,Acme Inc,new,\"vip,priority\",Follow up next week\nJane,Smith,5559876543,jane@example.com,Tech Corp,contacted,lead,Interested in product";
    const blob = new Blob([csvContent], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "contacts_template.csv";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  // Get set of already-mapped field names (excluding the current header) for disabling duplicates
  const getMappedFields = (excludeHeader: string): Set<string> => {
    const mapped = new Set<string>();
    for (const [header, field] of Object.entries(columnMapping)) {
      if (header !== excludeHeader && field && field !== SKIP_VALUE) {
        mapped.add(field);
      }
    }
    return mapped;
  };

  // Get sample data for a header from preview rows
  const getSampleData = (header: string): string => {
    if (!preview) return "";
    return preview.sample_rows
      .slice(0, 3)
      .map((row) => row[header] || "")
      .filter(Boolean)
      .join(", ");
  };

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent className={cn(
        "sm:max-w-[550px]",
        step === "mapping" && "sm:max-w-[700px]"
      )}>
        <DialogHeader>
          <DialogTitle>
            {step === "upload" && "Import Contacts"}
            {step === "mapping" && "Map Fields"}
            {step === "options" && "Import Options"}
            {step === "importing" && "Importing..."}
            {step === "results" && "Import Complete"}
          </DialogTitle>
          <DialogDescription>
            {step === "upload" && "Upload a CSV file to import contacts in bulk."}
            {step === "mapping" && "Map your CSV columns to contact fields."}
            {step === "options" && "Configure how your contacts should be imported."}
            {step === "importing" && "Please wait while we import your contacts."}
            {step === "results" && "Here's a summary of your import."}
          </DialogDescription>
        </DialogHeader>

        {/* Upload Step */}
        {step === "upload" && (
          <div className="space-y-4">
            <FileDropzone
              accept=".csv"
              onFile={(f) => {
                void handleFileSelect(f);
              }}
              onReject={(reason) => toast.error(reason)}
              placeholder="Drag and drop your CSV file here"
              subtext="or click to browse"
              ariaLabel="Upload CSV file"
            />

            <div className="flex items-center justify-between text-sm">
              <span className="text-muted-foreground">Need a template?</span>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="gap-2"
                onClick={handleDownloadTemplate}
              >
                <Download className="h-4 w-4" />
                Download Template
              </Button>
            </div>

            <div className="bg-muted/50 rounded-lg p-4 text-sm">
              <p className="font-medium mb-2">Required columns:</p>
              <ul className="list-disc list-inside text-muted-foreground space-y-1">
                <li><code className="text-xs bg-muted px-1 rounded">first_name</code> - Contact&apos;s first name</li>
                <li><code className="text-xs bg-muted px-1 rounded">phone_number</code> - Phone number</li>
              </ul>
              <p className="font-medium mt-3 mb-2">Optional columns:</p>
              <ul className="list-disc list-inside text-muted-foreground space-y-1">
                <li><code className="text-xs bg-muted px-1 rounded">last_name</code>, <code className="text-xs bg-muted px-1 rounded">email</code>, <code className="text-xs bg-muted px-1 rounded">company_name</code></li>
                <li><code className="text-xs bg-muted px-1 rounded">status</code>, <code className="text-xs bg-muted px-1 rounded">tags</code>, <code className="text-xs bg-muted px-1 rounded">notes</code></li>
              </ul>
            </div>
          </div>
        )}

        {/* Mapping Step */}
        {step === "mapping" && (
          <div className="space-y-4">
            {previewLoading ? (
              <div className="py-8 flex flex-col items-center gap-3">
                <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
                <p className="text-sm text-muted-foreground">Analyzing CSV file...</p>
              </div>
            ) : preview && (
              <>
                {/* File info */}
                <div className="flex items-center gap-3 p-3 bg-muted/50 rounded-lg text-sm">
                  <FileText className="h-5 w-5 text-primary shrink-0" />
                  <span className="font-medium truncate">{file?.name}</span>
                  <span className="text-muted-foreground shrink-0">
                    {preview.headers.length} columns, {preview.sample_rows.length}+ rows
                  </span>
                </div>

                {/* Required fields warning */}
                {!isMappingValid() && (
                  <div className="flex items-center gap-2 p-3 bg-warning/10 border border-warning/20 rounded-lg text-sm text-warning">
                    <AlertCircle className="h-4 w-4 shrink-0" />
                    <span>
                      Map both <strong>First Name</strong> and <strong>Phone Number</strong> to continue.
                    </span>
                  </div>
                )}

                {/* Mapping table */}
                <ScrollArea className="h-[300px] rounded-lg border">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead className="w-[180px]">CSV Column</TableHead>
                        <TableHead className="w-[200px]">Maps To</TableHead>
                        <TableHead>Sample Data</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {preview.headers.map((header) => {
                        const mappedFields = getMappedFields(header);
                        const currentValue = columnMapping[header];
                        return (
                          <TableRow key={header}>
                            <TableCell className="font-mono text-xs">
                              {header}
                            </TableCell>
                            <TableCell>
                              <Select
                                value={currentValue ?? SKIP_VALUE}
                                onValueChange={(value) =>
                                  setColumnMapping((prev) => ({
                                    ...prev,
                                    [header]: value === SKIP_VALUE ? null : value,
                                  }))
                                }
                              >
                                <SelectTrigger className="h-8 text-xs">
                                  <SelectValue />
                                </SelectTrigger>
                                <SelectContent>
                                  <SelectItem value={SKIP_VALUE}>-- Skip --</SelectItem>
                                  {preview.contact_fields.map((field) => (
                                    <SelectItem
                                      key={field.name}
                                      value={field.name}
                                      disabled={mappedFields.has(field.name)}
                                    >
                                      {field.label}
                                      {field.required ? " *" : ""}
                                    </SelectItem>
                                  ))}
                                </SelectContent>
                              </Select>
                            </TableCell>
                            <TableCell className="text-xs text-muted-foreground truncate max-w-[200px]">
                              {getSampleData(header)}
                            </TableCell>
                          </TableRow>
                        );
                      })}
                    </TableBody>
                  </Table>
                </ScrollArea>
              </>
            )}
          </div>
        )}

        {/* Options Step */}
        {step === "options" && file && (
          <div className="space-y-6">
            <div className="flex items-center gap-3 p-3 bg-muted/50 rounded-lg">
              <FileText className="h-8 w-8 text-primary" />
              <div className="flex-1 min-w-0">
                <p className="font-medium truncate">{file.name}</p>
                <p className="text-xs text-muted-foreground">
                  {(file.size / 1024).toFixed(1)} KB
                </p>
              </div>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                aria-label="Remove file"
                onClick={() => {
                  setFile(null);
                  setPreview(null);
                  setColumnMapping({});
                  setStep("upload");
                }}
              >
                <X className="h-4 w-4" />
              </Button>
            </div>

            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <div className="space-y-0.5">
                  <Label>Skip Duplicates</Label>
                  <p className="text-xs text-muted-foreground">
                    Skip contacts with phone numbers that already exist
                  </p>
                </div>
                <Switch
                  checked={options.skip_duplicates}
                  onCheckedChange={(checked) =>
                    setOptions({ ...options, skip_duplicates: checked })
                  }
                />
              </div>

              <div className="space-y-2">
                <Label>Default Status</Label>
                <Select
                  value={options.default_status}
                  onValueChange={(value) =>
                    setOptions({ ...options, default_status: value })
                  }
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="new">New</SelectItem>
                    <SelectItem value="contacted">Contacted</SelectItem>
                    <SelectItem value="qualified">Qualified</SelectItem>
                    <SelectItem value="converted">Converted</SelectItem>
                    <SelectItem value="lost">Lost</SelectItem>
                  </SelectContent>
                </Select>
                <p className="text-xs text-muted-foreground">
                  Used when status column is empty or invalid
                </p>
              </div>
            </div>
          </div>
        )}

        {/* Importing Step */}
        {step === "importing" && (
          <div className="py-8 space-y-4">
            <Progress value={undefined} className="h-2" />
            <p className="text-center text-sm text-muted-foreground">
              Processing your CSV file...
            </p>
          </div>
        )}

        {/* Results Step */}
        {step === "results" && result && (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div className="p-4 bg-success/10 rounded-lg text-center">
                <CheckCircle2 className="h-8 w-8 mx-auto mb-2 text-success" />
                <p className="text-2xl font-bold text-success">{result.successful}</p>
                <p className="text-xs text-muted-foreground">Imported</p>
              </div>
              <div className="p-4 bg-muted/50 rounded-lg text-center">
                <p className="text-2xl font-bold">{result.total_rows}</p>
                <p className="text-xs text-muted-foreground">Total Rows</p>
              </div>
            </div>

            {(result.skipped_duplicates > 0 || result.failed > 0) && (
              <div className="flex gap-4 text-sm">
                {result.skipped_duplicates > 0 && (
                  <div className="flex items-center gap-2 text-warning">
                    <AlertCircle className="h-4 w-4" />
                    <span>{result.skipped_duplicates} duplicates skipped</span>
                  </div>
                )}
                {result.failed > 0 && (
                  <div className="flex items-center gap-2 text-destructive">
                    <AlertCircle className="h-4 w-4" />
                    <span>{result.failed} failed</span>
                  </div>
                )}
              </div>
            )}

            {result.errors.length > 0 && (
              <div className="space-y-2">
                <p className="text-sm font-medium">Errors:</p>
                <ScrollArea className="h-[150px] rounded-lg border">
                  <div className="p-3 space-y-2">
                    {result.errors.map((error, idx) => (
                      <div
                        key={idx}
                        className="text-xs p-2 bg-destructive/10 rounded flex gap-2"
                      >
                        <span className="font-mono text-destructive">Row {error.row}</span>
                        <span className="text-muted-foreground">{error.error}</span>
                      </div>
                    ))}
                  </div>
                </ScrollArea>
              </div>
            )}
          </div>
        )}

        <DialogFooter>
          {step === "upload" && (
            <Button variant="outline" onClick={handleClose}>
              Cancel
            </Button>
          )}
          {step === "mapping" && (
            <>
              <Button
                variant="outline"
                onClick={() => {
                  setFile(null);
                  setPreview(null);
                  setColumnMapping({});
                  setStep("upload");
                }}
              >
                Back
              </Button>
              <Button
                onClick={() => setStep("options")}
                disabled={previewLoading || !isMappingValid()}
              >
                Continue
              </Button>
            </>
          )}
          {step === "options" && (
            <>
              <Button variant="outline" onClick={() => setStep("mapping")}>
                Back
              </Button>
              <Button onClick={handleStartImport}>
                Import Contacts
              </Button>
            </>
          )}
          {step === "results" && (
            <Button onClick={handleClose}>
              Done
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
