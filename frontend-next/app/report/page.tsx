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

  return (
    <div className="space-y-4">
      <div className="card flex flex-wrap justify-between items-start gap-3">
        <div>
          <div className="card-title mb-1">Coach&apos;s report</div>
          <div className="text-muted text-sm">
            <b className="text-[var(--text)]">{ov.display_name}</b> · Level {ov.current_level} (
            {LEVEL_NAMES[ov.current_level]}) · Overall{" "}
            {ov.latest_overall != null ? Math.round(ov.latest_overall) + "%" : "—"} · {eta} ·{" "}
            {ov.assessments_count} assessments
          </div>
        </div>
        <ReportButtons userId={currentUser} />
      </div>

      <div className="grid md:grid-cols-2 gap-4">
        <div className="card">
          <div className="card-title">Per-skill mastery</div>
          <SkillBars scores={ov.latest_scores} />
        </div>
        <div className="card">
          <div className="card-title">Strengths &amp; focus</div>
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
        <div className="card">
          <div className="card-title">Corrections &amp; suggestions</div>
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
        <div className="card">
          <div className="card-title">Your plan</div>
          <PlanPanel plan={plan} />
        </div>
      </div>
    </div>
  );
}
