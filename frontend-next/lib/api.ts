import type {
  Activity,
  AdminOverview,
  Assessment,
  AuthSession,
  AuthStatus,
  ConversationReport,
  ConversationRow,
  Feedback,
  FullAnalysis,
  HistoryConversation,
  GapItem,
  ModelInfo,
  Plan,
  ProgressOverview,
  ReadingHistory,
  ReadingPassage,
  ReadingResult,
  SkillPoint,
  Stats,
  User,
} from "./types";

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE?.replace(/\/$/, "") || "http://127.0.0.1:8000";

// The session token lives in localStorage rather than a cookie: the dashboard
// runs on :3000 against an API on :8000, and the API's CORS config does not
// allow credentials, so a cookie would simply never be sent.
const TOKEN_KEY = "coach.token";

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string | null) {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {}
}

/** Thrown on 401/403 so callers can send the user back to /login. */
export class AuthError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getToken();
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init?.headers || {}),
    },
    cache: "no-store",
  });
  if (!res.ok) {
    const body = await res.text();
    if (res.status === 401 || res.status === 403) throw new AuthError(res.status, body);
    throw new Error(`${res.status} ${body}`);
  }
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T);
}

export const api = {
  base: API_BASE,

  // --- auth ---------------------------------------------------------------
  version: () => req<{ version: string; git_sha: string | null }>("/version"),
  adminOverview: () => req<AdminOverview>("/admin/overview"),
  conversations: (id: string) =>
    req<ConversationRow[]>(`/users/${encodeURIComponent(id)}/conversations`),
  conversation: (id: string, sessionId: string) =>
    req<ConversationReport>(
      `/users/${encodeURIComponent(id)}/conversations/${encodeURIComponent(sessionId)}`,
    ),
  analysis: (id: string) => req<FullAnalysis>(`/users/${encodeURIComponent(id)}/analysis`),
  activity: (id: string, days = 364) =>
    req<Activity>(`/users/${encodeURIComponent(id)}/activity?days=${days}`),
  history: (id: string) =>
    req<HistoryConversation[]>(`/users/${encodeURIComponent(id)}/history`),
  chooseLevel: (id: string, level: number) =>
    req<User>(`/users/${encodeURIComponent(id)}/level`, {
      method: "POST",
      body: JSON.stringify({ current_level: level }),
    }),
  readingPassage: (level: number, seed: string) =>
    req<ReadingPassage>(
      `/reading/passage?level=${level}&seed=${encodeURIComponent(seed)}`,
    ),
  readingHistory: (id: string) =>
    req<ReadingHistory>(`/users/${encodeURIComponent(id)}/reading/attempts?limit=20`),
  scoreReading: (
    id: string,
    body: {
      reference: string;
      spoken: string;
      duration_s: number;
      level: number;
      title: string;
    },
  ) =>
    req<ReadingResult>(`/users/${encodeURIComponent(id)}/reading/score`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  authStatus: () => req<AuthStatus>("/auth/status"),
  signup: (user_id: string, display_name: string, password: string) =>
    req<AuthSession>("/auth/signup", {
      method: "POST",
      body: JSON.stringify({ user_id, display_name, password }),
    }),
  login: (user_id: string, password: string) =>
    req<AuthSession>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ user_id, password }),
    }),
  logout: () => req<void>("/auth/logout", { method: "POST" }),
  logoutAll: () => req<{ revoked: number }>("/auth/logout-all", { method: "POST" }),
  changePassword: (current_password: string, new_password: string) =>
    req<AuthSession>("/auth/password", {
      method: "POST",
      body: JSON.stringify({ current_password, new_password }),
    }),
  updateUser: (id: string, patch: { display_name?: string; current_level?: number }) =>
    req<User>(`/users/${encodeURIComponent(id)}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),
  deleteUser: (id: string) =>
    req<void>(`/users/${encodeURIComponent(id)}`, { method: "DELETE" }),
  me: () => req<User>("/auth/me"),

  listUsers: () => req<User[]>("/users"),
  createUser: (user_id: string, display_name: string) =>
    req<User>("/users", { method: "POST", body: JSON.stringify({ user_id, display_name }) }),
  seedDemo: (id: string) =>
    req<ProgressOverview>(`/dev/users/${id}/seed-demo`, { method: "POST" }),
  overview: (id: string) => req<ProgressOverview>(`/users/${id}/progress`),
  assessments: (id: string) => req<Assessment[]>(`/users/${id}/assessments?limit=200`),
  trend: (id: string, skill = "overall", days = 3650) =>
    req<SkillPoint[]>(`/users/${id}/progress/trend?skill=${skill}&days=${days}`),
  gaps: (id: string) => req<GapItem[]>(`/users/${id}/gaps`),
  plan: (id: string) => req<Plan>(`/users/${id}/plan`),
  feedback: (id: string) => req<Feedback>(`/users/${id}/feedback`),
  models: () => req<ModelInfo[]>("/models"),
  stats: () => req<Stats>("/stats"),
  topics: () => req<{ recommended: string[] }>("/topics"),
  setLevel: (id: string, level: number) =>
    req<User>(`/users/${id}`, { method: "PATCH", body: JSON.stringify({ current_level: level }) }),
  reportUrl: (id: string, fmt: string) => `${API_BASE}/users/${id}/report?format=${fmt}`,
  wsUrl: (id: string, topic?: string) => {
    const u = new URL(API_BASE);
    const proto = u.protocol === "https:" ? "wss" : "ws";
    const t = topic ? `&topic=${encodeURIComponent(topic)}` : "";
    // A browser cannot set an Authorization header on a WebSocket handshake, so
    // the token goes in the query string — that is what the server reads.
    const token = getToken();
    const k = token ? `&token=${encodeURIComponent(token)}` : "";
    return `${proto}://${u.host}/ws/session?user_id=${encodeURIComponent(
      id,
    )}&mode=free&ptt=1${t}${k}`;
  },
};
