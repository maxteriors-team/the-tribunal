"use client";

import { CheckCircle2, FileSpreadsheet, Phone } from "lucide-react";
import { useCallback, useId } from "react";
import { useFormContext } from "react-hook-form";
import { toast } from "sonner";

import { FileDropzone } from "@/components/shared/file-dropzone";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { formatNumber } from "@/lib/utils/number";

import type { OnboardingFormValues } from "../_state";

import { useOnboardingExtras } from "./onboarding-context";

export function LeadsStep() {
  const form = useFormContext<OnboardingFormValues>();
  const { csvFile, csvRowCount, setCsvFile, leadsError } =
    useOnboardingExtras();

  const areaCodeId = useId();

  const processFile = useCallback(
    (selected: File) => {
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

  const areaCode = form.watch("area_code");

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold">Import Your Dead Leads</h2>
        <p className="text-muted-foreground mt-1">
          Choose how to import the leads you want to reactivate
        </p>
      </div>

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

      <FileDropzone
        accept=".csv"
        onFile={processFile}
        onReject={(reason) => toast.error(reason)}
        placeholder="Drop your CSV here or click to browse"
        subtext="Accepts .csv files"
        ariaLabel="Upload CSV file"
      />

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
