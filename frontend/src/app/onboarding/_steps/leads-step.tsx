"use client";

import { CheckCircle2, Phone } from "lucide-react";
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

function normalizeAreaCode(value: string): string {
  const digits = value.replace(/\D/g, "");
  const nationalDigits = digits.length > 3 && digits.startsWith("1") ? digits.slice(1) : digits;

  return nationalDigits.slice(0, 3);
}

export function LeadsStep() {
  const form = useFormContext<OnboardingFormValues>();
  const { csvFile, csvRowCount, setCsvFile, leadsError } = useOnboardingExtras();

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
    [setCsvFile],
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

      {leadsError && (
        <p className="text-sm text-destructive" role="alert">
          {leadsError}
        </p>
      )}

      <p className="text-xs text-muted-foreground">
        CSV needs at least: <span className="font-mono font-medium">first_name</span> (or{" "}
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
            inputMode="numeric"
            autoComplete="tel-area-code"
            placeholder="e.g. 212"
            className="pl-9"
            value={areaCode}
            onChange={(event) =>
              form.setValue("area_code", normalizeAreaCode(event.target.value), {
                shouldDirty: true,
              })
            }
          />
        </div>
        <p className="text-xs text-muted-foreground">
          Preferred area code for your texting number. Leave blank for any US number.
        </p>
      </div>
    </div>
  );
}
