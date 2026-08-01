"use client";

import { useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import type { HistoryConversation } from "@/lib/types";
import { useUser } from "../user-context";

export default function HistoryPage() {
  const { currentUser } = useUser();
  const [data, setData] = useState<HistoryConversation[] | null>(null);
  const [query, setQuery] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!currentUser) return;
    api
      .history(currentUser)
      .then(setData)
      .catch((e) => setError((e as Error).message));
  }, [currentUser]);

  const filtered = useMemo(() => {
    if (!data) return [];
    const q = query.trim().toLowerCase();
    if (!q) return data;
    return data
      .map((c) => ({
        ...c,
        messages: c.messages.filter((m) => (m.transcript || "").toLowerCase().includes(q)),
      }))
      .filter((c) => c.messages.length > 0);
  }, [data, query]);

  const shown = filtered.reduce((n, c) => n + c.messages.length, 0);

  if (!currentUser) return <div className="text-muted">Select a learner first.</div>;
  if (error) return <div className="card text-muted">Could not load: {error}</div>;
  if (!data) return <div className="text-muted">Loading your history…</div>;

  return (
    <div className="card">
      <div className="flex justify-between items-center gap-3 flex-wrap">
        <h2 className="font-semibold">Chat history</h2>
        <input
          className="btn text-left"
          placeholder="Search what was said"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </div>
      <p className="text-muted text-xs mt-2 mb-4">
        {shown} message{shown === 1 ? "" : "s"}
        {query ? ` matching “${query}”` : ""}.
      </p>

      {filtered.length === 0 ? (
        <p className="text-muted text-sm">
          {query ? "Nothing matches that search." : "No conversations yet."}
        </p>
      ) : (
        filtered.map((c) => (
          <div key={c.session_id} className="mb-6">
            <div className="text-muted text-xs mb-2">
              {new Date(c.started_at).toLocaleString(undefined, {
                month: "short",
                day: "numeric",
                hour: "2-digit",
                minute: "2-digit",
              })}
            </div>
            <div className="space-y-2">
              {c.messages.map((m, i) => (
                <div
                  key={i}
                  className={`rounded-xl px-4 py-2.5 max-w-[82%] ${
                    m.role === "coach"
                      ? "bg-accent2/10 border border-line"
                      : "bg-panel2 border border-line ml-auto"
                  }`}
                >
                  <div>{m.transcript || "…"}</div>
                  <div className="text-dim text-xs mt-1">
                    {m.role === "coach" ? "Coach" : "You"}
                  </div>
                </div>
              ))}
            </div>
          </div>
        ))
      )}
    </div>
  );
}
