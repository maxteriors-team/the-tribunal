import { create } from "zustand";

import type { ContactSortBy } from "@/lib/api/contacts";
import type { Contact, ContactAgent, FilterDefinition } from "@/types";

interface ContactStore {
  // Selected contact
  selectedContact: Contact | null;
  setSelectedContact: (contact: Contact | null) => void;

  // Pagination
  contactsPage: number;
  contactsPageSize: number;
  setContactsPage: (page: number) => void;
  setContactsPageSize: (size: number) => void;

  // Search
  searchQuery: string;
  setSearchQuery: (query: string) => void;

  // Filters
  statusFilter: string | null;
  setStatusFilter: (status: string | null) => void;

  // Sorting
  sortBy: ContactSortBy;
  setSortBy: (sortBy: ContactSortBy) => void;

  // Advanced filters
  filters: FilterDefinition | null;
  setFilters: (filters: FilterDefinition | null) => void;

  // Contact-Agent assignments (local UI state)
  contactAgents: ContactAgent[];
  setContactAgents: (assignments: ContactAgent[]) => void;
  assignAgent: (contactId: number, agentId: string) => void;
  toggleContactAgent: (contactId: number) => void;
}

export const useContactStore = create<ContactStore>((set) => ({
  // Selected contact
  selectedContact: null,
  setSelectedContact: (contact) => set({ selectedContact: contact }),

  // Pagination
  contactsPage: 1,
  contactsPageSize: 25,
  setContactsPage: (page) => set({ contactsPage: page }),
  setContactsPageSize: (size) => set({ contactsPageSize: size, contactsPage: 1 }),

  // Search
  searchQuery: "",
  setSearchQuery: (query) => set({ searchQuery: query, contactsPage: 1 }),

  // Filters
  statusFilter: null,
  setStatusFilter: (status) => set({ statusFilter: status, contactsPage: 1 }),

  // Sorting — default mirrors Jobber's Clients list (most recent activity first).
  sortBy: "last_activity_desc",
  setSortBy: (sortBy) => set({ sortBy, contactsPage: 1 }),

  // Advanced filters
  filters: null,
  setFilters: (filters) => set({ filters, contactsPage: 1 }),

  // Contact-Agent assignments
  contactAgents: [],
  setContactAgents: (assignments) => set({ contactAgents: assignments }),
  assignAgent: (contactId, agentId) => set((state) => {
    const existing = state.contactAgents.find((ca) => ca.contact_id === contactId);
    if (existing) {
      return {
        contactAgents: state.contactAgents.map((ca) =>
          ca.contact_id === contactId
            ? { ...ca, agent_id: agentId, is_active: true, assigned_at: new Date().toISOString() }
            : ca
        ),
      };
    }
    return {
      contactAgents: [
        ...state.contactAgents,
        { contact_id: contactId, agent_id: agentId, is_active: true, assigned_at: new Date().toISOString() },
      ],
    };
  }),
  toggleContactAgent: (contactId) => set((state) => ({
    contactAgents: state.contactAgents.map((ca) =>
      ca.contact_id === contactId ? { ...ca, is_active: !ca.is_active } : ca
    ),
  })),
}));
