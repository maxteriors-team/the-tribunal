/**
 * Theme tokens for embed pages.
 *
 * The palette, agent-state colors, and color math now live in the shared embed
 * browser layer (`@/lib/embed/theme`) so the standalone widget and these React
 * routes stay in lockstep. This module re-exports the embed-page surface for
 * existing local imports.
 */

export {
  DEFAULT_PRIMARY_COLOR,
  getAgentStateInfo,
  getEmbedTheme,
  type AgentStateInfo,
  type EmbedTheme,
} from "@/lib/embed/theme";
