"use client";

import { Search, Users, CheckCircle2, Circle, Filter, X } from "lucide-react";
import { motion, AnimatePresence } from "motion/react";
import { useState, useMemo } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { contactStatusColors } from "@/lib/status-colors";
import type { Contact, ContactStatus } from "@/types";

interface ContactSelectorProps {
  contacts: Contact[];
  selectedIds: number[];
  onSelectionChange: (ids: number[]) => void;
  isLoading?: boolean;
}

export function ContactSelector({
  contacts,
  selectedIds,
  onSelectionChange,
}: ContactSelectorProps) {
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<ContactStatus | "all">("all");

  const filteredContacts = useMemo(() => {
    return contacts.filter((contact) => {
      const matchesSearch =
        !search ||
        contact.first_name?.toLowerCase().includes(search.toLowerCase()) ||
        contact.last_name?.toLowerCase().includes(search.toLowerCase()) ||
        contact.email?.toLowerCase().includes(search.toLowerCase()) ||
        contact.phone_number?.includes(search) ||
        contact.company_name?.toLowerCase().includes(search.toLowerCase());

      const matchesStatus = statusFilter === "all" || contact.status === statusFilter;

      return matchesSearch && matchesStatus;
    });
  }, [contacts, search, statusFilter]);

  const toggleContact = (contactId: number) => {
    if (selectedIds.includes(contactId)) {
      onSelectionChange(selectedIds.filter((id) => id !== contactId));
    } else {
      onSelectionChange([...selectedIds, contactId]);
    }
  };

  const selectAll = () => {
    const allFilteredIds = filteredContacts.map((c) => c.id);
    const newSelected = [...new Set([...selectedIds, ...allFilteredIds])];
    onSelectionChange(newSelected);
  };

  const deselectAll = () => {
    const filteredIds = new Set(filteredContacts.map((c) => c.id));
    onSelectionChange(selectedIds.filter((id) => !filteredIds.has(id)));
  };

  const formatPhone = (phone?: string) => {
    if (!phone) return "";
    const cleaned = phone.replace(/\D/g, "");
    if (cleaned.length === 10) {
      return `(${cleaned.slice(0, 3)}) ${cleaned.slice(3, 6)}-${cleaned.slice(6)}`;
    }
    if (cleaned.length === 11 && cleaned.startsWith("1")) {
      return `+1 (${cleaned.slice(1, 4)}) ${cleaned.slice(4, 7)}-${cleaned.slice(7)}`;
    }
    return phone;
  };

  return (
    <div className="space-y-4">
      {/* Header with stats */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Users className="size-5 text-muted-foreground" />
          <span className="text-sm text-muted-foreground">
            {selectedIds.length} of {contacts.length} selected
          </span>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={selectAll}
            disabled={filteredContacts.length === 0}
          >
            Select All ({filteredContacts.length})
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={deselectAll}
            disabled={selectedIds.length === 0}
          >
            Clear
          </Button>
        </div>
      </div>

      {/* Filters */}
      <div className="flex gap-3">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 size-4 text-muted-foreground" />
          <Input
            aria-label="Search campaign contacts"
            placeholder="Search by name, email, phone..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-10"
          />
          {search && (
            <Button
              variant="ghost"
              size="icon"
              className="absolute right-1 top-1/2 -translate-y-1/2 size-7"
              onClick={() => setSearch("")}
              aria-label="Clear contact search"
            >
              <X className="size-4" aria-hidden="true" />
            </Button>
          )}
        </div>
        <Select
          value={statusFilter}
          onValueChange={(v) => setStatusFilter(v as ContactStatus | "all")}
        >
          <SelectTrigger className="w-40" aria-label="Filter contacts by status">
            <Filter className="size-4 mr-2" aria-hidden="true" />
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All Statuses</SelectItem>
            <SelectItem value="new">New</SelectItem>
            <SelectItem value="contacted">Contacted</SelectItem>
            <SelectItem value="qualified">Qualified</SelectItem>
            <SelectItem value="converted">Converted</SelectItem>
            <SelectItem value="lost">Lost</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {/* Contact List */}
      <ScrollArea className="h-[400px] border rounded-lg">
        <div className="p-2 space-y-1">
          <AnimatePresence mode="popLayout">
            {filteredContacts.map((contact) => {
              const isSelected = selectedIds.includes(contact.id);
              const fullName = [contact.first_name, contact.last_name].filter(Boolean).join(" ");

              return (
                <motion.div
                  key={contact.id}
                  layout
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -10 }}
                  onClick={() => toggleContact(contact.id)}
                  className={`flex items-center gap-3 p-3 rounded-lg cursor-pointer transition-colors ${
                    isSelected ? "bg-primary/10 border border-primary/30" : "hover:bg-muted/50"
                  }`}
                >
                  <div className="flex-shrink-0">
                    {isSelected ? (
                      <CheckCircle2 className="size-5 text-primary" />
                    ) : (
                      <Circle className="size-5 text-muted-foreground" />
                    )}
                  </div>

                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="font-medium truncate">{fullName || "Unknown"}</span>
                      <Badge
                        variant="secondary"
                        className={`text-xs ${contactStatusColors[contact.status]}`}
                      >
                        {contact.status}
                      </Badge>
                    </div>
                    <div className="flex items-center gap-3 text-sm text-muted-foreground">
                      {contact.phone_number && <span>{formatPhone(contact.phone_number)}</span>}
                      {contact.email && <span className="truncate">{contact.email}</span>}
                    </div>
                    {contact.company_name && (
                      <div className="text-xs text-muted-foreground mt-0.5">
                        {contact.company_name}
                      </div>
                    )}
                  </div>
                </motion.div>
              );
            })}
          </AnimatePresence>

          {filteredContacts.length === 0 && (
            <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
              <Users className="size-12 mb-2 opacity-50" />
              <p>No contacts found</p>
              {search && (
                <Button variant="link" onClick={() => setSearch("")} className="mt-1">
                  Clear search
                </Button>
              )}
            </div>
          )}
        </div>
      </ScrollArea>

      {/* Selected summary */}
      {selectedIds.length > 0 && (
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          className="flex items-center gap-2 p-3 bg-primary/5 rounded-lg border border-primary/20"
        >
          <CheckCircle2 className="size-5 text-primary" />
          <span className="text-sm font-medium">
            {selectedIds.length} contact{selectedIds.length !== 1 ? "s" : ""} selected
          </span>
        </motion.div>
      )}
    </div>
  );
}
