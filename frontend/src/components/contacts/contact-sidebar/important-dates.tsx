"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Plus, X, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { formatLongDate } from "@/lib/utils/date";
import { getApiErrorMessage } from "@/lib/utils/errors";
import { contactsApi, type ImportantDates } from "@/lib/api/contacts";
import { contactQueryKeys } from "@/hooks/useContacts";
import { useContactStore } from "@/lib/contact-store";
import type { Contact } from "@/types";

type DateType = "birthday" | "anniversary" | "custom";

interface ImportantDatesSectionProps {
  contact: Contact;
  workspaceId: string | null | undefined;
}

function formatLocalDate(dateStr: string): string {
  // Parse as local date to avoid timezone issues
  const parts = dateStr.split("-").map(Number);
  if (parts.length !== 3 || parts.some((n) => Number.isNaN(n))) return dateStr;
  const [year, month, day] = parts;
  return formatLongDate(new Date(year, month - 1, day));
}

export function ImportantDatesSection({
  contact,
  workspaceId,
}: ImportantDatesSectionProps) {
  const queryClient = useQueryClient();
  const { setSelectedContact } = useContactStore();
  const [addFormOpen, setAddFormOpen] = useState(false);
  const [dateType, setDateType] = useState<DateType>("birthday");
  const [dateValue, setDateValue] = useState("");
  const [customLabel, setCustomLabel] = useState("");

  const dates = contact.important_dates;

  const updateDatesMutation = useMutation({
    mutationFn: (newDates: ImportantDates | null) => {
      if (!workspaceId) throw new Error("Workspace not loaded");
      return contactsApi.update(workspaceId, contact.id, {
        important_dates: newDates,
      });
    },
    onSuccess: (updatedContact) => {
      void queryClient.invalidateQueries({
        queryKey: contactQueryKeys.all(workspaceId ?? ""),
      });
      void queryClient.invalidateQueries({
        queryKey: contactQueryKeys.get(workspaceId ?? "", contact.id),
      });
      setSelectedContact(updatedContact);
      toast.success("Important dates updated");
    },
    onError: (error) => {
      toast.error(getApiErrorMessage(error, "Failed to update important dates"));
    },
  });

  const handleAdd = () => {
    if (!dateValue) return;
    const current: ImportantDates = { ...dates };

    if (dateType === "birthday") {
      current.birthday = dateValue;
    } else if (dateType === "anniversary") {
      current.anniversary = dateValue;
    } else {
      if (!customLabel.trim()) return;
      current.custom = [
        ...(current.custom ?? []),
        { label: customLabel.trim(), date: dateValue },
      ];
    }

    updateDatesMutation.mutate(current);
    setAddFormOpen(false);
    setDateValue("");
    setCustomLabel("");
    setDateType("birthday");
  };

  const handleRemove = (
    type: "birthday" | "anniversary" | "custom",
    index?: number,
  ) => {
    const current: ImportantDates = { ...dates };
    if (type === "birthday") {
      delete current.birthday;
    } else if (type === "anniversary") {
      delete current.anniversary;
    } else if (type === "custom" && index !== undefined) {
      current.custom = [...(current.custom ?? [])];
      current.custom.splice(index, 1);
      if (current.custom.length === 0) delete current.custom;
    }
    const hasData =
      current.birthday ||
      current.anniversary ||
      (current.custom && current.custom.length > 0);
    updateDatesMutation.mutate(hasData ? current : null);
  };

  const hasDates =
    dates?.birthday ||
    dates?.anniversary ||
    (dates?.custom && dates.custom.length > 0);

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between px-2">
        <h3 className="text-sm font-medium text-muted-foreground">
          Important Dates
        </h3>
        <Button
          variant="ghost"
          size="icon"
          className="h-6 w-6"
          onClick={() => setAddFormOpen(!addFormOpen)}
          disabled={updateDatesMutation.isPending}
          aria-label={
            addFormOpen ? "Close add date form" : "Add important date"
          }
        >
          <Plus className="h-3.5 w-3.5" />
        </Button>
      </div>

      {!hasDates && !addFormOpen && (
        <p className="text-xs text-muted-foreground px-2 py-1">
          No important dates yet. Add birthdays and anniversaries to get
          reminders.
        </p>
      )}

      <div className="space-y-1 px-2">
        {dates?.birthday && (
          <div className="flex items-center gap-2 text-sm group">
            <span>🎂</span>
            <div className="flex-1 min-w-0">
              <p className="text-xs text-muted-foreground">Birthday</p>
              <p className="text-sm font-medium">
                {formatLocalDate(dates.birthday)}
              </p>
            </div>
            <Button
              variant="ghost"
              size="icon"
              className="h-5 w-5 opacity-0 group-hover:opacity-100 transition-opacity"
              onClick={() => handleRemove("birthday")}
              disabled={updateDatesMutation.isPending}
              aria-label="Remove birthday"
            >
              <X className="h-3 w-3" />
            </Button>
          </div>
        )}
        {dates?.anniversary && (
          <div className="flex items-center gap-2 text-sm group">
            <span>💍</span>
            <div className="flex-1 min-w-0">
              <p className="text-xs text-muted-foreground">Anniversary</p>
              <p className="text-sm font-medium">
                {formatLocalDate(dates.anniversary)}
              </p>
            </div>
            <Button
              variant="ghost"
              size="icon"
              className="h-5 w-5 opacity-0 group-hover:opacity-100 transition-opacity"
              onClick={() => handleRemove("anniversary")}
              disabled={updateDatesMutation.isPending}
              aria-label="Remove anniversary"
            >
              <X className="h-3 w-3" />
            </Button>
          </div>
        )}
        {dates?.custom?.map((item, i) => (
          <div
            key={`${item.label}-${item.date}`}
            className="flex items-center gap-2 text-sm group"
          >
            <span>📅</span>
            <div className="flex-1 min-w-0">
              <p className="text-xs text-muted-foreground">{item.label}</p>
              <p className="text-sm font-medium">{formatLocalDate(item.date)}</p>
            </div>
            <Button
              variant="ghost"
              size="icon"
              className="h-5 w-5 opacity-0 group-hover:opacity-100 transition-opacity"
              onClick={() => handleRemove("custom", i)}
              disabled={updateDatesMutation.isPending}
              aria-label={`Remove ${item.label}`}
            >
              <X className="h-3 w-3" />
            </Button>
          </div>
        ))}
      </div>

      {addFormOpen && (
        <div className="space-y-2 px-2 py-2 bg-muted/30 rounded-lg">
          <Select
            value={dateType}
            onValueChange={(v) => setDateType(v as DateType)}
          >
            <SelectTrigger className="h-8 text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="birthday">Birthday</SelectItem>
              <SelectItem value="anniversary">Anniversary</SelectItem>
              <SelectItem value="custom">Custom</SelectItem>
            </SelectContent>
          </Select>
          {dateType === "custom" && (
            <Input
              placeholder="Label (e.g. Contract Renewal)"
              value={customLabel}
              onChange={(e) => setCustomLabel(e.target.value)}
              className="h-8 text-xs"
            />
          )}
          <Input
            type="date"
            value={dateValue}
            onChange={(e) => setDateValue(e.target.value)}
            className="h-8 text-xs"
          />
          <div className="flex gap-2">
            <Button
              size="sm"
              variant="outline"
              className="flex-1 h-7 text-xs"
              onClick={() => {
                setAddFormOpen(false);
                setDateValue("");
                setCustomLabel("");
              }}
            >
              Cancel
            </Button>
            <Button
              size="sm"
              className="flex-1 h-7 text-xs"
              onClick={handleAdd}
              disabled={
                !dateValue ||
                (dateType === "custom" && !customLabel.trim()) ||
                updateDatesMutation.isPending
              }
            >
              {updateDatesMutation.isPending ? (
                <Loader2 className="h-3 w-3 animate-spin" />
              ) : (
                "Save"
              )}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
