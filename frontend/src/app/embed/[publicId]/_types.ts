export interface AgentConfig {
  public_id: string;
  name: string;
  greeting_message: string | null;
  button_text: string;
  theme: "light" | "dark" | "auto";
  position: string;
  primary_color: string;
  language: string;
  voice?: string;
  channel_mode: string;
}

export interface TokenResponse {
  client_secret: { value: string };
  agent: {
    name: string;
    voice: string;
    language: string;
    initial_greeting: string | null;
  };
  model: string;
  tools: Array<{
    type: string;
    name: string;
    description: string;
    parameters: Record<string, unknown>;
  }>;
}

export type ConnectionStatus = "idle" | "connecting" | "connected" | "error";
export type AgentState = "idle" | "listening" | "thinking" | "speaking";

// WebRTC/audio resource shapes and their cleanup helpers live in the shared
// embed browser layer so they can be unit-tested in isolation.
export type {
  WebRTCResources,
  AudioAnalysisResources as AudioResources,
} from "@/lib/embed/session";

export type TranscriptEntry = {
  role: "user" | "assistant";
  content: string;
};

// Theme option/resolution helpers live in `@/lib/embed/theme`.
export type { ThemeOption, ResolvedTheme } from "@/lib/embed/theme";

export const POSITION_CLASSES: Record<string, string> = {
  "bottom-right": "bottom-5 right-5",
  "bottom-left": "bottom-5 left-5",
  "top-right": "top-5 right-5",
  "top-left": "top-5 left-5",
};

export const POSITION_CLASSES_LG: Record<string, string> = {
  "bottom-right": "bottom-8 right-5",
  "bottom-left": "bottom-8 left-5",
  "top-right": "top-8 right-5",
  "top-left": "top-8 left-5",
};
