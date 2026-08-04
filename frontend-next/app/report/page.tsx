"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { LEVEL_NAMES, type Feedback, type Plan, type ProgressOverview } from "@/lib/types";
import { useUser } from "../user-context";
import { SkillBars } from "@/components/widgets";
import { PlanPanel, ReportButtons } from "@/components/panels";

export default function Report() {
  const { currentUser } = useUser();
  const [ov, setOv] = useState<ProgressOverview | null>(null);
  const [fb, setFb] = useState<Feedback | null>(null);
  const [plan, setPlan] = useState<Plan | null>(null);

  useEffect(() => {
    if (!currentUser) return;
    (async () => {
      try {
        const [o, f, p] = await Promise.all([
          api.overview(currentUser),
          api.feedback(currentUser),
          api.plan(currentUser),
        ]);
        setOv(o);
        setFb(f);
        setPlan(p);
      } catch {
        /* ignore */
      }
    })();
  }, [currentUser]);

  if (!currentUser) return <p className="text-muted">Select a learner.</p>;
  if (!ov || !fb) return <p className="text-muted">Loading…</p>;

  const eta =
    ov.next_level != null && ov.estimated_days_to_next_level != null
      ? `~${ov.estimated_days_to_next_level}d to level ${ov.next_level}`
      : "top level";

  const overall = ov.latest_overall != null ? Math.round(ov.latest_overall) : null;
  // Encouraging, but not dishonest: the words track the number.
  const headline =
    overall == null
      ? "Your first score is one conversation away"
      : overall >= 85
        ? "Excellent work."
        : overall >= 70
          ? "Good job — you are being understood."
          : overall >= 55
            ? "Solid progress, keep going."
            : "Early days — every session moves this.";

  return (
    <div className="space-y-4">
      <header className="pb-1">
        <h1 className="t-display">Your report</h1>
        <p className="text-muted text-sm mt-1">
          Everything the coach has measured, and what to do next.
        </p>
      </header>

      <section className="hero">
        <div
          className="ring"
          style={{ ["--p" as string]: overall ?? 0, ["--size" as string]: "132px" }}
          role="img"
          aria-label={`Overall score ${overall ?? 0} percent`}
        >
          <div className="relative text-center leading-tight">
            <b className="block text-[30px] font-bold tabular-nums">{overall ?? "—"}</b>
            <span className="t-label block mt-1">overall</span>
          </div>
        </div>
        <div className="flex-1 min-w-[min(100%,260px)]">
          <h2 className="t-display mb-1.5">{headline}</h2>
          <p className="text-muted text-sm mb-4">
            <b className="text-fg">{ov.display_name}</b> · Level {ov.current_level} ·{" "}
            {LEVEL_NAMES[ov.current_level]} · {eta} · {ov.assessments_count} assessments
          </p>
          <ReportButtons userId={currentUser} />
        </div>
      </section>

      <div className="grid md:grid-cols-2 gap-4">
        <div className="card !p-5">
          <div className="t-section mb-3">Per-skill mastery</div>
          <SkillBars scores={ov.latest_scores} />
        </div>
        <div className="card !p-5">
          <div className="t-section mb-3">Strengths &amp; focus</div>
          <div className="mb-3">
            <span className="pill bg-good/15 text-good">Strengths</span>
            <div className="mt-2 flex gap-2 flex-wrap">
              {fb.strengths.length ? (
                fb.strengths.map((s) => (
                  <span key={s} className="pill capitalize">
                    {s}
                  </span>
                ))
              ) : (
                <span className="text-muted text-sm">Keep practicing to build strengths.</span>
              )}
            </div>
          </div>
          <div>
            <span className="pill bg-bad/10 text-bad">Focus on</span>
            <div className="mt-2 flex gap-2 flex-wrap">
              {fb.weaknesses.length ? (
                fb.weaknesses.map((s) => (
                  <span key={s} className="pill capitalize">
                    {s}
                  </span>
                ))
              ) : (
                <span className="text-muted text-sm">All skills near target.</span>
              )}
            </div>
          </div>
          {fb.pronunciation_tip && (
            <div className="text-muted text-sm mt-4">🗣 {fb.pronunciation_tip}</div>
          )}
        </div>
      </div>

      <div className="grid md:grid-cols-2 gap-4">
        <div className="card !p-5">
          <div className="t-section mb-3">Corrections &amp; suggestions</div>
          {fb.corrections.length ? (
            fb.corrections.slice(0, 6).map((c, i) => (
              <div key={i} className="text-sm my-2">
                <span className="text-bad">✗ {c.text}</span>{" "}
                <span className="text-muted">→</span>{" "}
                <span className="text-good">✓ {c.correction}</span>
              </div>
            ))
          ) : (
            <span className="text-muted text-sm">
              No corrections yet — do a live Practice turn (needs the LLM evaluator running).
            </span>
          )}
          {fb.vocabulary_suggestions.length > 0 && (
            <div className="mt-3 flex gap-2 flex-wrap">
              {fb.vocabulary_suggestions.map((v) => (
                <span key={v} className="pill">
                  {v}
                </span>
              ))}
            </div>
          )}
        </div>
        <div className="card !p-5">
          <div className="t-section mb-3">Your plan</div>
          <PlanPanel plan={plan} />
        </div>
      </div>
    </div>
  );
}
