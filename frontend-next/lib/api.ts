import type {
  Assessment,
  Feedback,
  GapItem,
  ModelInfo,
  Plan,
  ProgressOverview,
  SkillPoint,
  Stats,
  User,
} from "./types";

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE?.replace(/\/$/, "") || "http://127.0.0.1:8000";

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json() as Promise<T>;
}

export const api = {
  base: API_BASE,
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
    return `${proto}://${u.host}/ws/session?user_id=${encodeURIComponent(id)}&mode=free&ptt=1${t}`;
  },
};
