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
}

export interface ProgressOverview {
  user_id: string;
  display_name: string;
  current_level: number;
  streak_days: number;
  latest_overall: number | null;
  latest_scores: Partial<Record<Dimension, number | null>>;
  assessments_count: number;
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
