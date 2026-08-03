"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import {
  LEVEL_NAMES,
  type Assessment,
  type GapItem,
  type Plan,
  type ProgressOverview,
  type SkillPoint,
} from "@/lib/types";
import { useUser } from "./user-context";
import { SkillRadar } from "@/components/SkillRadar";
import { StreakHeatmap } from "@/components/StreakHeatmap";
import { ReadingSummary } from "@/components/ReadingSummary";
import { DashboardSkeleton } from "@/components/Skeleton";
import { OverallTrend } from "@/components/OverallTrend";
import { LevelPicker, SkillBars } from "@/components/widgets";
import {
  AssessmentsTable,
  GapsPanel,
  PlanPanel,
  ReportButtons,
  StatTile,
} from "@/components/panels";

export default function Dashboard() {
  const { currentUser, currentLevel, refresh, users } = useUser();
  const [ov, setOv] = useState<ProgressOverview | null>(null);
  const [assess, setAssess] = useState<Assessment[]>([]);
  const [trend, setTrend] = useState<SkillPoint[]>([]);
  const [gaps, setGaps] = useState<GapItem[]>([]);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!currentUser) return;
    setErr(null);
    (async () => {
      try {
        const [o, a, t, g, p] = await Promise.all([
          api.overview(currentUser),
          api.assessments(currentUser),
          api.trend(currentUser),
          api.gaps(currentUser),
          api.plan(currentUser),
        ]);
        setOv(o);
        setAssess(a);
        setTrend(t);
        setGaps(g);
        setPlan(p);
      } catch (e) {
        setErr((e as Error).message);
      }
    })();
  }, [currentUser]);

  if (!currentUser)
    return <p className="text-muted">Create or select a learner to see the dashboard.</p>;
  if (err) return <p className="text-bad">Could not load: {err}</p>;
  if (!ov) return <DashboardSkeleton />;

  const eta = ov.estimated_days_to_next_level;
  const setLevel = async (l: number) => {
    await api.setLevel(currentUser, l);
    await refresh();
  };
  return (
    <div className="space-y-4">
      {/* A learner with no history lands here first. A dashboard of zeros is a
          review surface being used as a landing surface, so give them the one
          action that fills it — and hide the empty charts below. */}
      {ov.assessments_count === 0 && (
        <div className="card text-center py-8">
          <h2 className="text-lg font-semibold mb-1">Ready when you are</h2>
          <p className="text-muted text-sm mb-5">
            Your scores, radar and streak fill in after your first conversation. It takes
            about two minutes.
          </p>
          <Link href="/practice" className="btn btn-primary inline-block px-6 py-3">
            🎙️ Start your first conversation
          </Link>
        </div>
      )}

      {/* The hero reads the same numbers as the tiles below it. It exists
          because four identical tiles give the eye nowhere to land first — a
          greeting, a ring and one button do. */}
      {ov.assessments_count > 0 &&
        (() => {
          const pct = ov.latest_overall != null ? Math.round(ov.latest_overall) : 0;
          const first =
            (users.find((u) => u.user_id === currentUser)?.display_name ?? "").split(" ")[0] ||
            "there";
          return (
            <div className="hero">
              <div className="flex-1 min-w-[min(100%,260px)]">
                <h2 className="text-xl font-semibold mb-1">Hello {first} 👋</h2>
                <p className="text-muted text-sm mb-3.5">
                  Level {ov.current_level} · {LEVEL_NAMES[ov.current_level]} · {ov.streak_days}-day
                  streak
                </p>
                <div className="h-2.5 rounded-full bg-panel3 overflow-hidden mb-2">
                  <div
                    className="h-full rounded-full bg-gradient-to-r from-accent to-accent2"
                    style={{ width: `${pct}%` }}
                  />
                </div>
                <p className="text-muted text-sm mb-3.5">
                  {ov.next_level != null
                    ? `${Math.max(0, 100 - pct)}% to go until level ${ov.next_level}` +
                      (eta != null ? ` · about ${eta} day${eta === 1 ? "" : "s"} at this pace` : "")
                    : "You are at the top level — keep it sharp."}
                </p>
                <Link href="/practice" className="btn btn-primary inline-block px-5 py-2.5">
                  🎙️ Continue practising
                </Link>
              </div>
              <div
                className="ring"
                style={{ ["--p" as string]: pct }}
                role="img"
                aria-label={`Overall score ${pct} percent`}
              >
                <div className="relative text-center leading-tight">
                  <b className="text-2xl block">{pct}%</b>
                  <span className="text-[10.5px] text-muted uppercase tracking-wide">overall</span>
                </div>
              </div>
            </div>
          );
        })()}

      {/* Level first: it sets the difficulty of everything below it, so it
          belongs above the numbers rather than buried between charts. */}
      <div className="card">
        <div className="card-title">Your level — pick where you want to practice</div>
        <LevelPicker current={currentLevel} onSet={setLevel} />
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatTile
          label="Level"
          value={String(ov.current_level)}
          /* When the chosen level and the scored level disagree, say which is
             which rather than contradicting it two tiles later. */
          sub={
            ov.scored_level != null && ov.scored_level !== ov.current_level
              ? `you chose this · scores say ${ov.scored_level}`
              : LEVEL_NAMES[ov.current_level]
          }
        />
        <StatTile label="Streak" value={`${ov.streak_days}d`} sub="keep it up" />
        <StatTile
          label="Overall"
          value={ov.latest_overall != null ? Math.round(ov.latest_overall) + "%" : "—"}
          sub={`${ov.assessments_count} assessments`}
        />
        <StatTile
          label="To next level"
          value={eta != null ? `${eta}d` : "—"}
          sub={ov.next_level != null ? `reach level ${ov.next_level}` : "top level"}
        />
      </div>

      {ov.assessments_count > 0 && (
      <div className="grid md:grid-cols-2 gap-4">
        <div className="card">
          <div className="card-title">Skill radar</div>
          <SkillRadar scores={ov.latest_scores} />
        </div>
        <div className="card">
          <div className="card-title">Per-skill mastery</div>
          <SkillBars scores={ov.latest_scores} />
        </div>
      </div>
      )}

      <div className="grid md:grid-cols-2 gap-4">
        <div className="card">
          <div className="card-title">Overall trend</div>
          <OverallTrend points={trend} />
        </div>
        <div className="card">
          <div className="card-title">Study plan</div>
          <PlanPanel plan={plan} />
        </div>
      </div>

      <div className="card">
        <div className="card-title">Top gaps</div>
        <GapsPanel gaps={gaps} />
      </div>

      {currentUser && <ReadingSummary userId={currentUser} />}

      <div className="card">
        <div className="flex justify-between items-center mb-1">
          <div className="card-title mb-0">Recent assessments</div>
          <ReportButtons userId={currentUser} />
        </div>
        <AssessmentsTable rows={assess} />
      </div>

      {/* Last: a year of squares is a look-back, not something you act on. */}
      {currentUser && <StreakHeatmap userId={currentUser} currentStreak={ov.streak_days} />}
    </div>
  );
}
