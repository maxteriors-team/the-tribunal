// Re-exports the shared agent edit form schema. The single source of truth now
// lives in `@/lib/agents/agent-form`; this module is kept for the existing tab
// imports under `@/components/agents/tabs/*`.
export {
  editAgentFormSchema,
  TAB_FIELDS,
  type EditAgentFormValues,
} from "@/lib/agents/agent-form";
