"use client";

import { useState } from "react";
import { Plus, Trash2, Filter } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { TagPicker } from "@/components/tags/tag-picker";
import { FilterChip } from "@/components/filters/filter-chip";
import { SaveSegmentDialog } from "@/components/segments/save-segment-dialog";
import type { FilterRule, FilterDefinition } from "@/types";

interface FieldOption {
  value: string;
  label: string;
  operators: { value: string; label: string }[];
  valueType: "text" | "number" | "boolean" | "select" | "tags" | "date";
  options?: { value: string; label: string }[];
}

const FIELD_OPTIONS: FieldOption[] = [
  {
    value: "status",
    label: "Status",
    operators: [
      { value: "equals", label: "is" },
      { value: "not_equals", label: "is not" },
      { value: "in", label: "is one of" },
    ],
    valueType: "select",
    options: [
      { value: "new", label: "New" },
      { value: "contacted", label: "Contacted" },
      { value: "qualified", label: "Qualified" },
      { value: "converted", label: "Converted" },
      { value: "lost", label: "Lost" },
    ],
  },
  {
    value: "tags",
    label: "Tags",
    operators: [
      { value: "has_any", label: "has any of" },
      { value: "has_all", label: "has all of" },
      { value: "has_none", label: "has none of" },
    ],
    valueType: "tags",
  },
  {
    value: "lead_score",
    label: "Lead Score",
    operators: [
      { value: "gte", label: ">=" },
      { value: "lte", label: "<=" },
      { value: "gt", label: ">" },
      { value: "lt", label: "<" },
      { value: "equals", label: "equals" },
    ],
    valueType: "number",
  },
  {
    value: "is_qualified",
    label: "Qualified",
    operators: [
      { value: "is_true", label: "is qualified" },
      { value: "is_false", label: "is not qualified" },
    ],
    valueType: "boolean",
  },
  {
    value: "source",
    label: "Source",
    operators: [
      { value: "equals", label: "is" },
      { value: "contains", label: "contains" },
      { value: "is_null", label: "is empty" },
      { value: "is_not_null", label: "is not empty" },
    ],
    valueType: "text",
  },
  {
    value: "company_name",
    label: "Company",
    operators: [
      { value: "contains", label: "contains" },
      { value: "equals", label: "is" },
      { value: "starts_with", label: "starts with" },
      { value: "is_null", label: "is empty" },
      { value: "is_not_null", label: "is not empty" },
    ],
    valueType: "text",
  },
  {
    value: "created_at",
    label: "Created Date",
    operators: [
      { value: "after", label: "after" },
      { value: "before", label: "before" },
    ],
    valueType: "date",
  },
  {
    value: "enrichment_status",
    label: "Enrichment",
    operators: [
      { value: "equals", label: "is" },
      { value: "not_equals", label: "is not" },
      { value: "is_null", label: "is empty" },
    ],
    valueType: "select",
    options: [
      { value: "pending", label: "Pending" },
      { value: "enriched", label: "Enriched" },
      { value: "failed", label: "Failed" },
      { value: "skipped", label: "Skipped" },
    ],
  },
];

interface ContactFilterBuilderProps {
  workspaceId: string;
  filters: FilterDefinition | null;
  onFiltersChange: (filters: FilterDefinition | null) => void;
  compact?: boolean;
  onSaveSegment?: () => void;
}

export function ContactFilterBuilder({
  workspaceId,
  filters,
  onFiltersChange,
  compact = false,
  onSaveSegment,
}: ContactFilterBuilderProps) {
  const [open, setOpen] = useState(false);
  const [saveSegmentOpen, setSaveSegmentOpen] = useState(false);
  const rules = filters?.rules ?? [];
  const logic = filters?.logic ?? "and";

  const addRule = () => {
    const newRule: FilterRule = {
      field: "status",
      operator: "equals",
      value: "new",
    };
    onFiltersChange({
      logic,
      rules: [...rules, newRule],
    });
  };

  const updateRule = (index: number, updates: Partial<FilterRule>) => {
    const newRules = [...rules];
    newRules[index] = { ...newRules[index], ...updates };
    onFiltersChange({ logic, rules: newRules });
  };

  const removeRule = (index: number) => {
    const newRules = rules.filter((_, i) => i !== index);
    if (newRules.length === 0) {
      onFiltersChange(null);
    } else {
      onFiltersChange({ logic, rules: newRules });
    }
  };

  const setLogic = (newLogic: "and" | "or") => {
    onFiltersChange({ logic: newLogic, rules });
  };

  const clearAll = () => {
    onFiltersChange(null);
    setOpen(false);
  };

  const noValueOperators = ["is_true", "is_false", "is_null", "is_not_null"];

  return (
    <div className="space-y-2">
      {/* Active filter chips */}
      {rules.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5">
          {rules.map((rule, i) => (
            <FilterChip key={i} rule={rule} onRemove={() => removeRule(i)} />
          ))}
          <Button variant="ghost" size="sm" onClick={clearAll} className="h-7 text-xs">
            Clear all
          </Button>
          {(onSaveSegment || filters) && (
            <Button variant="ghost" size="sm" onClick={() => {
              if (onSaveSegment) onSaveSegment();
              else setSaveSegmentOpen(true);
            }} className="h-7 text-xs">
              Save as Segment
            </Button>
          )}
        </div>
      )}

      {/* Filter builder popover */}
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button
            variant="outline"
            size={compact ? "sm" : "default"}
            className="gap-2"
          >
            <Filter className="h-4 w-4" />
            {rules.length > 0 ? `Filters (${rules.length})` : "Filters"}
          </Button>
        </PopoverTrigger>
        <PopoverContent className="w-[520px] p-4" align="start">
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <h4 className="text-sm font-medium">Filter contacts</h4>
              {rules.length > 1 && (
                <Select value={logic} onValueChange={(v) => setLogic(v as "and" | "or")}>
                  <SelectTrigger className="w-24 h-7 text-xs">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="and">Match all</SelectItem>
                    <SelectItem value="or">Match any</SelectItem>
                  </SelectContent>
                </Select>
              )}
            </div>

            {/* Filter rules */}
            {rules.map((rule, index) => {
              const fieldConfig = FIELD_OPTIONS.find((f) => f.value === rule.field);
              const operators = fieldConfig?.operators ?? [];

              return (
                <div key={index} className="flex items-start gap-2">
                  {/* Field select */}
                  <Select
                    value={rule.field}
                    onValueChange={(v) => {
                      const newField = FIELD_OPTIONS.find((f) => f.value === v);
                      updateRule(index, {
                        field: v,
                        operator: newField?.operators[0]?.value ?? "equals",
                        value: newField?.valueType === "boolean" ? true : "",
                      });
                    }}
                  >
                    <SelectTrigger className="w-32 h-8 text-xs">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {FIELD_OPTIONS.map((f) => (
                        <SelectItem key={f.value} value={f.value}>
                          {f.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>

                  {/* Operator select */}
                  <Select
                    value={rule.operator}
                    onValueChange={(v) => updateRule(index, { operator: v })}
                  >
                    <SelectTrigger className="w-32 h-8 text-xs">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {operators.map((op) => (
                        <SelectItem key={op.value} value={op.value}>
                          {op.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>

                  {/* Value input (polymorphic) */}
                  {!noValueOperators.includes(rule.operator) && (
                    <div className="flex-1 min-w-0">
                      {fieldConfig?.valueType === "tags" ? (
                        <TagPicker
                          workspaceId={workspaceId}
                          selectedTagIds={Array.isArray(rule.value) ? (rule.value as string[]) : []}
                          onSelectionChange={(tagIds) =>
                            updateRule(index, { value: tagIds })
                          }
                          allowCreate={false}
                        />
                      ) : fieldConfig?.valueType === "select" ? (
                        <Select
                          value={String(rule.value)}
                          onValueChange={(v) => updateRule(index, { value: v })}
                        >
                          <SelectTrigger className="h-8 text-xs">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            {fieldConfig.options?.map((opt) => (
                              <SelectItem key={opt.value} value={opt.value}>
                                {opt.label}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      ) : fieldConfig?.valueType === "number" ? (
                        <Input
                          type="number"
                          value={String(rule.value ?? "")}
                          onChange={(e) =>
                            updateRule(index, {
                              value: e.target.value ? Number(e.target.value) : "",
                            })
                          }
                          className="h-8 text-xs"
                          placeholder="Value"
                        />
                      ) : fieldConfig?.valueType === "date" ? (
                        <Input
                          type="date"
                          value={String(rule.value ?? "")}
                          onChange={(e) =>
                            updateRule(index, { value: e.target.value })
                          }
                          className="h-8 text-xs"
                        />
                      ) : (
                        <Input
                          value={String(rule.value ?? "")}
                          onChange={(e) =>
                            updateRule(index, { value: e.target.value })
                          }
                          className="h-8 text-xs"
                          placeholder="Value"
                        />
                      )}
                    </div>
                  )}

                  {/* Remove button */}
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-8 w-8 shrink-0"
                    onClick={() => removeRule(index)}
                    aria-label="Remove rule"
                  >
                    <Trash2 className="h-3.5 w-3.5 text-muted-foreground" />
                  </Button>
                </div>
              );
            })}

            <Button
              variant="outline"
              size="sm"
              onClick={addRule}
              className="w-full gap-2"
            >
              <Plus className="h-3.5 w-3.5" />
              Add filter
            </Button>
          </div>
        </PopoverContent>
      </Popover>

      {/* Save segment dialog */}
      {filters && (
        <SaveSegmentDialog
          open={saveSegmentOpen}
          onOpenChange={setSaveSegmentOpen}
          filters={filters}
          workspaceId={workspaceId}
        />
      )}
    </div>
  );
}
