"use client";

import { useCallback, useId, useRef, useState } from "react";
import { useFormContext } from "react-hook-form";
import { toast } from "sonner";
import {
  CheckCircle2,
  Database,
  FileSpreadsheet,
  Loader2,
  Phone,
  Upload,
  Users,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { importFubContacts } from "@/lib/api/realtor";
import { getApiErrorMessage } from "@/lib/utils/errors";
import { formatNumber } from "@/lib/utils/number";
import { useWorkspace } from "@/providers/workspace-provider";

import type { OnboardingFormValues } from "../_state";
import { useOnboardingExtras } from "./onboarding-context";

export function LeadsStep() {
  const form = useFormContext<OnboardingFormValues>();
  const { currentWorkspaceId } = useWorkspace();
  const {
    csvFile,
    csvRowCount,
    setCsvFile,
    fubConnected,
    fubImportCount,
    setFubImportCount,
    leadsError,
    setLeadsError,
  } = useOnboardingExtras();

  const inputRef = useRef<HTMLInputElement>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [fubImporting, setFubImporting] = useState(false);
  const areaCodeId = useId();

  const processFile = useCallback(
    (selected: File | null) => {
      if (!selected) {
        setCsvFile(null, null);
        return;
      }
      const reader = new FileReader();
      reader.onload = (e) => {
        const text = e.target?.result as string;
        const lines = text.split("\n").filter((l) => l.trim().length > 0);
        const rows = Math.max(0, lines.length - 1);
        setCsvFile(selected, rows);
      };
      reader.readAsText(selected);
    },
    [setCsvFile]
  );

  const handleFileInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    processFile(e.target.files?.[0] ?? null);
  };

  const handleDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDragging(false);
    const dropped = e.dataTransfer.files[0];
    if (dropped?.name.endsWith(".csv")) {
      processFile(dropped);
    } else {
      toast.error("Please drop a .csv file.");
    }
  };

  const handleDragOver = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = () => setIsDragging(false);

  const handleFubImport = useCallback(async () => {
    if (!currentWorkspaceId) {
      toast.error("No workspace found. Please log in again.");
      return;
    }
    setFubImporting(true);
    try {
      const result = await importFubContacts(currentWorkspaceId, true);
      setFubImportCount(result.imported);
      setLeadsError(null);
      toast.success(
        `Imported ${formatNumber(result.imported)} leads from Follow Up Boss`
      );
    } catch (err) {
      toast.error(getApiErrorMessage(err, "Failed to import leads."));
    } finally {
      setFubImporting(false);
    }
  }, [currentWorkspaceId, setFubImportCount, setLeadsError]);

  const areaCode = form.watch("area_code");

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold">Import Your Dead Leads</h2>
        <p className="text-muted-foreground mt-1">
          Choose how to import the leads you want to reactivate
        </p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <Card
          className={`relative overflow-hidden ${!fubConnected ? "opacity-50" : ""}`}
        >
          <CardContent className="p-5 flex flex-col items-center text-center gap-3">
            <div className="flex items-center justify-center w-12 h-12 rounded-full bg-primary/10 text-primary">
              <Database className="w-6 h-6" />
            </div>
            <div>
              <p className="font-semibold text-sm">Pull from Follow Up Boss</p>
              {fubImportCount !== null && (
                <p className="text-xs text-green-600 mt-1">
                  {formatNumber(fubImportCount)} lead
                  {fubImportCount !== 1 ? "s" : ""} imported
                </p>
              )}
              {!fubConnected && (
                <p className="text-xs text-muted-foreground mt-1">
                  Connect Follow Up Boss in Step 1 first
                </p>
              )}
            </div>
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={!fubConnected || fubImporting}
              onClick={handleFubImport}
            >
              {fubImporting ? (
                <Loader2 className="size-4 mr-2 animate-spin" />
              ) : (
                <Users className="size-4 mr-2" />
              )}
              Import All Leads
            </Button>
          </CardContent>
        </Card>

        <Card className="relative overflow-hidden">
          <CardContent className="p-5 flex flex-col items-center text-center gap-3">
            <div className="flex items-center justify-center w-12 h-12 rounded-full bg-primary/10 text-primary">
              <FileSpreadsheet className="w-6 h-6" />
            </div>
            <div>
              <p className="font-semibold text-sm">Upload CSV</p>
              <p className="text-xs text-muted-foreground mt-1">
                Drag and drop or click to browse
              </p>
            </div>
          </CardContent>
        </Card>
      </div>

      <div
        role="button"
        tabIndex={0}
        aria-label="Upload CSV file"
        className={`border-2 border-dashed rounded-lg p-8 flex flex-col items-center justify-center gap-3 cursor-pointer transition-colors ${
          isDragging
            ? "border-primary bg-primary/5"
            : "border-border hover:border-primary/50 hover:bg-muted/30"
        }`}
        onClick={() => inputRef.current?.click()}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") inputRef.current?.click();
        }}
        onDrop={handleDrop}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
      >
        <Upload className="size-8 text-muted-foreground" />
        <div className="text-center">
          <p className="font-medium">Drop your CSV here or click to browse</p>
          <p className="text-sm text-muted-foreground mt-1">
            Accepts .csv files
          </p>
        </div>
        <input
          ref={inputRef}
          type="file"
          accept=".csv"
          className="hidden"
          onChange={handleFileInput}
        />
      </div>

      {csvFile && (
        <Card className="bg-muted/30">
          <CardContent className="py-3 px-4 flex items-center gap-3">
            <CheckCircle2 className="size-4 text-green-500 shrink-0" />
            <div className="min-w-0">
              <p className="font-medium truncate text-sm">{csvFile.name}</p>
              {csvRowCount !== null && (
                <p className="text-xs text-muted-foreground">
                  ~{formatNumber(csvRowCount)} lead
                  {csvRowCount !== 1 ? "s" : ""} detected
                </p>
              )}
            </div>
          </CardContent>
        </Card>
      )}

      {leadsError && <p className="text-sm text-destructive">{leadsError}</p>}

      <p className="text-xs text-muted-foreground">
        CSV needs at least:{" "}
        <span className="font-mono font-medium">first_name</span> (or{" "}
        <span className="font-mono font-medium">name</span>),{" "}
        <span className="font-mono font-medium">phone</span>. Email is optional.
      </p>

      <div className="space-y-2">
        <Label htmlFor={areaCodeId}>Preferred Area Code (optional)</Label>
        <div className="relative max-w-xs">
          <Phone className="absolute left-3 top-1/2 -translate-y-1/2 size-4 text-muted-foreground" />
          <Input
            id={areaCodeId}
            type="text"
            placeholder="e.g. 212"
            maxLength={3}
            className="pl-9"
            value={areaCode}
            onChange={(e) =>
              form.setValue("area_code", e.target.value.replace(/\D/g, ""), {
                shouldDirty: true,
              })
            }
          />
        </div>
        <p className="text-xs text-muted-foreground">
          Preferred area code for your texting number. Leave blank for any US
          number.
        </p>
      </div>
    </div>
  );
}
