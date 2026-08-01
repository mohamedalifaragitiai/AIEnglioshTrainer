"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type {
  ConversationReport,
  ConversationRow,
  FullAnalysis,
  Recommendation,
} from "@/lib/types";
import { StatTile } from "@/components/panels";
import { useUser } from "../user-context";

/** 75/60 bands, so a number's meaning is legible before it is read. */
function band(v: number | null | undefined) {
  if (v == null) return "text-muted bg-panel2";
  if (v >= 75) return "text-good bg-good/10";
  if (v >= 60) return "text-warn bg-warn/10";
  return "text-bad bg-bad/10";
}

function fmtDur(s: number | null) {
  if (s == null) return "—";
  const m = Math.floor(s / 60);
  const sec = Math.round(s % 60);
  return m ? `${m}m ${sec}s` : `${sec}s`;
}

function fmtDate(iso: string) {
  return new Date(iso).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function Score({ value }: { value: number | null }) {
  return (
    <span className={`px-3 py-1.5 rounded-lg font-bold ${band(value)}`}>
      {value == null ? "—" : Math.round(value)}
    </span>
  );
}

function Recommendations({ items }: { items: Recommendation[] }) {
  if (!items.length) {
    return (
      <p className="text-muted text-sm">
        No weak areas flagged — keep practising to build more signal.
      </p>
    );
  }
  return (
    <div className="space-y-3">
      {items.map((r) => (
        <div
          key={r.skill}
          className="rounded-xl border-l-4 border-accent bg-accent/10 px-4 py-3"
        >
          <div className="font-semibold capitalize">
            {r.skill} · {Math.round(r.score)}{" "}
            <span className="pill bg-panel2 text-muted">{r.priority}</span>
          </div>
          <ul className="list-disc pl-5 mt-1.5 text-sm text-muted space-y-1">
            {r.actions.map((a) => (
              <li key={a}>{a}</li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}

export default function ConversationsPage() {
  const { currentUser } = useUser();
  const [rows, setRows] = useState<ConversationRow[] | null>(null);
  const [analysis, setAnalysis] = useState<FullAnalysis | null>(null);
  const [open, setOpen] = useState<ConversationReport | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!currentUser) return;
    setOpen(null);
    setError(null);
    Promise.all([api.conversations(currentUser), api.analysis(currentUser)])
      .then(([r, a]) => {
        setRows(r);
        setAnalysis(a);
      })
      .catch((e) => setError((e as Error).message));
  }, [currentUser]);

  if (!currentUser) return <div className="text-muted">Select a learner first.</div>;
  if (error) return <div className="card text-muted">Could not load: {error}</div>;
  if (!rows || !analysis) return <div className="text-muted">Loading your conversations…</div>;

  const arrow =
    analysis.trend.direction === "improving"
      ? "▲"
      : analysis.trend.direction === "declining"
        ? "▼"
        : "▬";

  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatTile
          label="Conversations"
          value={String(analysis.conversations)}
          sub={`${analysis.learner_turns} turns spoken`}
        />
        <StatTile
          label="Practice time"
          value={fmtDur(analysis.practice_seconds)}
          sub="across all sessions"
        />
        <StatTile
          label="Overall"
          value={analysis.overall != null ? String(Math.round(analysis.overall)) : "—"}
          sub={`${analysis.scored_conversations} scored`}
        />
        <StatTile
          label="Trend"
          value={`${arrow} ${analysis.trend.delta != null ? (analysis.trend.delta > 0 ? "+" : "") + analysis.trend.delta : "—"}`}
          sub={analysis.trend.direction}
        />
      </div>

      <div className="card">
        <h2 className="font-semibold mb-1">What to work on next</h2>
        <p className="text-muted text-xs mb-3">
          {analysis.strengths.length > 0 && (
            <>
              Strongest: <b>{analysis.strengths.join(", ")}</b>.{" "}
            </>
          )}
          {analysis.weaknesses.length > 0 ? (
            <>
              Weakest: <b>{analysis.weaknesses.join(", ")}</b>.
            </>
          ) : (
            "No weak areas flagged."
          )}
        </p>
        <Recommendations items={analysis.recommendations} />
      </div>

      <div className="card">
        <h2 className="font-semibold mb-1">Your conversations</h2>
        <p className="text-muted text-xs mb-3">
          {rows.length
            ? `${rows.length} conversation${rows.length === 1 ? "" : "s"} — select one for the full turn-by-turn analysis.`
            : "No conversations yet. Use the Practice tab to start one."}
        </p>
        <div className="space-y-2.5">
          {rows.map((c) => (
            <button
              key={c.session_id}
              onClick={() =>
                api
                  .conversation(currentUser, c.session_id)
                  .then(setOpen)
                  .catch((e) => setError((e as Error).message))
              }
              className="w-full flex items-center gap-4 text-left rounded-xl border border-line bg-panel px-4 py-3 hover:border-accent hover:bg-panel2 transition"
            >
              <Score value={c.overall} />
              <span className="flex-1 min-w-0">
                <span className="block font-semibold">
                  {fmtDate(c.started_at)} · {fmtDur(c.duration_s)} · {c.learner_turns} turn
                  {c.learner_turns === 1 ? "" : "s"}
                </span>
                <span className="block text-muted text-xs truncate">
                  {c.preview || "no transcript"}
                </span>
              </span>
              <span className="text-muted text-xs">{c.assessments} scored</span>
            </button>
          ))}
        </div>
      </div>

      {open && (
        <div className="card">
          <div className="flex justify-between items-start gap-4">
            <div>
              <h2 className="font-semibold">Conversation analysis</h2>
              <p className="text-muted text-xs">
                {fmtDate(open.started_at)} · {fmtDur(open.duration_s)} · {open.learner_turns} turns
                · {open.words_spoken} words
              </p>
            </div>
            <Score value={open.overall} />
          </div>

          {open.pending_scoring && (
            <p className="mt-3 text-warn text-sm">
              Some turns are still being scored — assessment work is deferred while the machine
              is busy. Re-open this in a minute.
            </p>
          )}

          <div className="flex flex-wrap gap-2 my-4">
            {Object.entries(open.scores).map(([d, v]) => (
              <span key={d} className={`pill capitalize ${band(v as number)}`}>
                {d} {Math.round(v as number)}
              </span>
            ))}
          </div>

          {open.recommendations.length > 0 && (
            <>
              <h3 className="font-semibold mt-4 mb-2">How to improve</h3>
              <Recommendations items={open.recommendations} />
            </>
          )}

          {open.corrections.length > 0 && (
            <>
              <h3 className="font-semibold mt-5 mb-2">
                Corrections ({open.corrections.length})
              </h3>
              <div className="space-y-2">
                {open.corrections.map((c, i) => (
                  <div
                    key={i}
                    className="rounded-lg border-l-4 border-bad bg-bad/10 px-3 py-2 text-sm"
                  >
                    <s className="text-muted">{c.text}</s> →{" "}
                    <b className="text-good">{c.correction}</b>
                    {c.type && <span className="text-muted"> · {c.type}</span>}
                  </div>
                ))}
              </div>
            </>
          )}

          <h3 className="font-semibold mt-5 mb-2">The conversation</h3>
          <div className="space-y-2.5">
            {open.turns.map((t) => (
              <div
                key={t.utterance_id}
                className={`rounded-xl px-4 py-3 max-w-[82%] ${
                  t.role === "coach"
                    ? "bg-accent2/10 border border-line"
                    : "bg-panel2 border border-line ml-auto"
                }`}
              >
                <div>{t.transcript || "…"}</div>
                <div className="text-dim text-xs mt-1.5 flex gap-3 flex-wrap">
                  <span>{t.role === "coach" ? "Coach" : "You"}</span>
                  {t.overall != null && <span>score {Math.round(t.overall)}</span>}
                  {t.notes.length > 0 && <span>{t.notes.join(" · ")}</span>}
                </div>
                {t.corrections.map((c, i) => (
                  <div
                    key={i}
                    className="mt-2 rounded-lg border-l-4 border-bad bg-bad/10 px-3 py-1.5 text-sm"
                  >
                    <s className="text-muted">{c.text}</s> →{" "}
                    <b className="text-good">{c.correction}</b>
                  </div>
                ))}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
