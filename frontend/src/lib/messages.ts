/**
 * Centralized user-facing toast/notification copy.
 *
 * Grouped by domain. Each leaf is either a string constant or a small
 * function returning a string when the message needs dynamic values.
 *
 * Patterns:
 *   - `success` — confirmation of a completed action
 *   - `error`   — fallback string for failure paths (pair with `getApiErrorMessage`)
 *   - `info`    — neutral notice (validation, prerequisites)
 *
 * Add new entries near related domains rather than creating new top-level
 * groups unless a clearly distinct domain is introduced.
 */

export const messages = {
  agents: {
    notFound: "Agent not found or has been deleted",
    updated: "Agent updated successfully",
    updateFailed: "Failed to update agent",
    deleted: "Agent deleted successfully",
    deleteFailed: "Failed to delete agent",
  },

  campaigns: {
    smsCreated: "Campaign created successfully!",
    smsCreateFailed: "Failed to create campaign",
    voiceCreated: "Voice campaign created successfully!",
    voiceCreateFailed: "Failed to create campaign",
    emailCreated: "Email campaign created successfully!",
    emailCreateFailed: "Failed to create email campaign",
  },

  offers: {
    created: "Offer created successfully",
    createFailed: "Failed to create offer",
  },

  contacts: {
    created: "Contact created successfully!",
    createFailed: "Failed to create contact. Please try again.",
    updated: "Contact updated successfully!",
    updateFailed: "Failed to update contact. Please try again.",
    deleted: "Contact deleted successfully",
    deleteFailed: "Failed to delete contact. Please try again.",
    noPhoneNumber: "Contact has no phone number",
    aiEnabled: "AI engagement enabled!",
    aiDisabled: "AI engagement disabled!",
    aiToggleFailed: "Failed to toggle AI engagement. Please try again.",
  },

  phoneNumbers: {
    noneVoiceEnabled: "No voice-enabled phone numbers available",
  },

  findLeads: {
    found: (count: number) => `Found ${count} businesses`,
    searchFailed: "Failed to search. Please check your API key configuration.",
    queryRequired: "Please enter a search query",
    selectionRequired: "Please select at least one lead to import",
  },

  workspace: {
    notLoaded: "Workspace not loaded",
  },
} as const;
