export const DIMENSIONS = [
  "pronunciation",
  "grammar",
  "vocabulary",
  "listening",
  "fluency",
  "confidence",
  "coherence",
  "relevance",
] as const;
export type Dimension = (typeof DIMENSIONS)[number];

export interface User {
  user_id: string;
  display_name: string;
  created_at: string;
  current_level: number;
  streak_days: number;
  is_admin?: boolean;
  /** False until the learner picks a starting level themselves. */
  level_selected?: boolean;
  full_name?: string | null;
  email?: string | null;
  country?: string | null;
  native_language?: string | null;
  goal?: string | null;
  /** Coach voice: semantic, not a model voice id. */
  voice?: "female" | "male";
}

export interface AuthStatus {
  auth_required: boolean;
  authenticated: boolean;
  user_id: string | null;
  min_password_length: number;
  is_admin: boolean;
}

export interface ActivityCell {
  date: string;
  weekday: number;
  count: number;
  seconds: number;
}

export interface Activity {
  user_id: string;
  from: string;
  to: string;
  days: number;
  cells: ActivityCell[];
  active_days: number;
  total_sessions: number;
  total_seconds: number;
  longest_streak: number;
}

export interface HistoryConversation {
  session_id: string;
  started_at: string;
  messages: { role: string; transcript: string | null; created_at: string }[];
}

export interface ReadingPassage {
  level: number;
  title: string;
  text: string;
  words: number;
}

export interface ReadingResult {
  reference_words: number;
  spoken_words: number;
  matched_words: number;
  accuracy: number | null;
  wer: number | null;
  wpm: number | null;
  pace: string | null;
  duration_s: number | null;
  missed_words: string[];
  extra_words: string[];
  substitutions: { expected: string; heard: string }[];
  verdict: string;
}

export interface ReadingAttempt {
  attempt_id: string;
  level: number | null;
  title: string | null;
  reference_words: number;
  spoken_words: number;
  matched_words: number;
  accuracy: number | null;
  wer: number | null;
  wpm: number | null;
  pace: string | null;
  duration_s: number | null;
  created_at: string;
}

export interface ReadingHistory {
  user_id: string;
  summary: {
    attempts: number;
    avg_accuracy: number | null;
    best_accuracy: number | null;
    avg_wpm: number | null;
    total_seconds: number | null;
    words_read: number;
    delta: number | null;
  };
  attempts: ReadingAttempt[];
}

export interface Recommendation {
  skill: string;
  score: number;
  priority: string;
  actions: string[];
}

export interface Correction {
  text: string | null;
  correction: string | null;
  type?: string | null;
}

export interface ConversationRow {
  session_id: string;
  started_at: string;
  ended_at: string | null;
  duration_s: number | null;
  mode: string;
  learner_turns: number;
  assessments: number;
  overall: number | null;
  scores: Partial<Record<Dimension, number>>;
  preview: string | null;
}

export interface ConversationTurn {
  utterance_id: string;
  role: string;
  transcript: string | null;
  created_at: string;
  overall: number | null;
  scores: Partial<Record<Dimension, number>>;
  corrections: Correction[];
  suggestions: string[];
  notes: string[];
}

export interface ConversationReport extends ConversationRow {
  user_id: string;
  turns: ConversationTurn[];
  words_spoken: number;
  strengths: string[];
  weaknesses: string[];
  corrections: Correction[];
  suggestions: string[];
  recommendations: Recommendation[];
  pending_scoring: boolean;
}

export interface FullAnalysis {
  user_id: string;
  conversations: number;
  scored_conversations: number;
  learner_turns: number;
  practice_seconds: number;
  overall: number | null;
  scores: Partial<Record<Dimension, number>>;
  strengths: string[];
  weaknesses: string[];
  trend: {
    first_half_overall: number | null;
    second_half_overall: number | null;
    delta: number | null;
    direction: string;
  };
  recommendations: Recommendation[];
  history: { started_at: string; overall: number | null }[];
}

export interface AdminUserRow {
  user_id: string;
  display_name: string;
  created_at: string;
  current_level: number;
  streak_days: number;
  is_admin: boolean;
  has_password: boolean;
  sessions: number;
  utterances: number;
  assessments: number;
  last_active: string | null;
  latest_overall: number | null;
  avg_overall: number | null;
  avg_scores: Partial<Record<Dimension, number>>;
}

export interface AdminOverview {
  totals: {
    users: number;
    admins: number;
    sessions: number;
    utterances: number;
    assessments: number;
    avg_overall: number | null;
    active_7d: number;
    active_30d: number;
    never_practised: number;
  };
  users: AdminUserRow[];
}

export interface AuthSession {
  token: string;
  expires_at: string;
  user: User;
}

export interface ProgressOverview {
  user_id: string;
  display_name: string;
  current_level: number;
  streak_days: number;
  latest_overall: number | null;
  latest_scores: Partial<Record<Dimension, number | null>>;
  assessments_count: number;
  /** Level implied by the latest score; may differ from the chosen one. */
  scored_level: number | null;
  next_level: number | null;
  estimated_days_to_next_level: number | null;
}

export interface Assessment {
  assessment_id: string;
  created_at: string;
  overall: number | null;
  scoring_model_version: string;
  pronunciation: number | null;
  grammar: number | null;
  vocabulary: number | null;
  listening: number | null;
  fluency: number | null;
  confidence: number | null;
  coherence: number | null;
  relevance: number | null;
}

export interface SkillPoint {
  created_at: string;
  value: number;
}

export interface GapItem {
  skill: Dimension;
  score: number;
  target: number;
  gap: number;
  severity: number;
  rank: number;
}

export interface FocusArea {
  skill: string;
  score: number;
  why: string;
  activities: string[];
}

export interface Plan {
  user_id: string;
  created_at: string;
  horizon: string;
  difficulty: number;
  next_level: number | null;
  estimated_days_to_next_level: number | null;
  focus_areas: FocusArea[];
  summary: string;
}

export interface Feedback {
  user_id: string;
  overall: number | null;
  current_level: number;
  next_level: number | null;
  estimated_days_to_next_level: number | null;
  strengths: string[];
  weaknesses: string[];
  corrections: { text?: string; correction?: string; type?: string }[];
  vocabulary_suggestions: string[];
  pronunciation_tip: string | null;
}

export interface ModelInfo {
  name: string;
  kind: string;
  status: string;
  vram_gb: number;
}

export interface Stats {
  degradation_level: number;
  ceiling: number;
  soft: number;
  resources: Partial<Record<"vram" | "gpu_util" | "ram" | "cpu" | "disk", number | null>>;
  vram_total_gb: number | null;
  vram_used_gb: number | null;
  models: ModelInfo[];
  models_loaded: number;
}

export const LEVEL_NAMES = [
  "Beginner",
  "Intermediate",
  "Advanced",
  "Professional",
  "Fluent",
  "Native-like",
] as const;
