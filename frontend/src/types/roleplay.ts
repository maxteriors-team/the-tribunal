// Practice-arena (roleplay) domain types.

export type PersonaDifficulty = "easy" | "medium" | "hard";

export interface ProspectPersona {
  id: string;
  workspace_id: string | null;
  slug: string;
  name: string;
  description: string | null;
  difficulty: string;
  channel: string;
  persona_prompt: string;
  opening_message: string | null;
  objections: string[];
  goal: string | null;
  is_builtin: boolean;
  created_at: string;
  updated_at: string;
}

export type RehearseeType = "ai" | "human";

export type RehearsalStatus = "pending" | "running" | "completed" | "failed";

export interface RehearsalTranscriptTurn {
  role: string; // "prospect" | "agent"
  content: string;
}

export interface ObjectionBreakdownItem {
  objection: string;
  addressed: boolean;
  note: string;
}

export interface RehearsalScores {
  overall_score?: number;
  objection_coverage_score?: number;
  tone_score?: number;
  tone_label?: string;
  booking_attempted?: boolean;
  objection_breakdown?: ObjectionBreakdownItem[];
  sentiment?: string | null;
  sentiment_score?: number | null;
  intents?: string[];
  topics?: string[];
}

export interface RehearsalRunSummary {
  id: string;
  workspace_id: string;
  agent_id: string | null;
  persona_id: string | null;
  agent_name: string | null;
  persona_name: string | null;
  rehearsee: string;
  channel: string;
  status: string;
  pending_action?: string | null;
  attempt_count?: number;
  retryable?: boolean;
  overall_score: number | null;
  objection_coverage: number | null;
  booking_attempted: boolean | null;
  tone_score: number | null;
  created_at: string;
  completed_at: string | null;
}

export interface RehearsalRun extends RehearsalRunSummary {
  max_turns: number;
  transcript: RehearsalTranscriptTurn[];
  scores: RehearsalScores;
  strengths: string[];
  gaps: string[];
  suggestions: string[];
  summary: string | null;
  error: string | null;
  updated_at: string;
}

export interface CreateRehearsalRequest {
  idempotency_key?: string;
  agent_id: string;
  persona_id: string;
  rehearsee?: RehearseeType;
  channel?: string | null;
  max_turns?: number;
}

export interface CreatePersonaRequest {
  name: string;
  description?: string;
  slug?: string;
  difficulty?: PersonaDifficulty;
  channel?: string;
  persona_prompt: string;
  opening_message?: string;
  objections?: string[];
  goal?: string;
}
