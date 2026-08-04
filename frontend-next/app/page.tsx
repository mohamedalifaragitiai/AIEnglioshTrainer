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
  type Activity,
} from "@/lib/types";
import { useUser } from "./user-context";
import { SkillRadar } from "@/components/SkillRadar";
import { Icon } from "@/components/icons";
import { StreakHeatmap } from "@/components/StreakHeatmap";
import { ReadingSummary } from "@/components/ReadingSummary";
import { DashboardSkeleton } from "@/components/Skeleton";
import { OverallTrend } from "@/components/OverallTrend";
import { LevelPicker } from "@/components/widgets";
import {
  HeroCard,
  LevelCard,
  QuickStats,
  QuoteStrip,
  RecentActivity,
  SkillGrid,
  TodayPlan,
} from "@/components/home";
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
  const [activity, setActivity] = useState<Activity | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!currentUser) return;
    setErr(null);
    (async () => {
      try {
        const [o, a, t, g, p, act] = await Promise.all([
          api.overview(currentUser),
          api.assessments(currentUser),
          api.trend(currentUser),
          api.gaps(currentUser),
          api.plan(currentUser),
          // Already served for the streak heatmap; the daily-goal ring reads the
          // same per-day seconds rather than inventing a number to show.
          api.activity(currentUser, 7),
        ]);
        setOv(o);
        setAssess(a);
        setTrend(t);
        setGaps(g);
        setPlan(p);
        setActivity(act);
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
  // The app has no daily-target setting, so the ring needs one stated here
  // rather than implied. Ten minutes is five of this app's two-minute
  // conversations — long enough to be a day's practice, short enough to keep.
  const DAILY_GOAL_MIN = 10;
  const today = new Date().toISOString().slice(0, 10);
  const secondsToday = activity?.cells.find((c) => c.date === today)?.seconds ?? 0;
  const minutesToday = Math.floor(secondsToday / 60);
  const goalPct = Math.min(100, Math.round((secondsToday / (DAILY_GOAL_MIN * 60)) * 100));

  const overallPct = ov.latest_overall != null ? Math.round(ov.latest_overall) : 0;
  const firstName =
    (users.find((u) => u.user_id === currentUser)?.display_name ?? "").split(" ")[0] || "there";
  const spark = trend.slice(-8).map((t) => Math.round(t.value));
  const fresh = ov.assessments_count === 0;

  return (
    <div className="space-y-4">
      <header className="flex items-end justify-between gap-4 flex-wrap pb-1">
        <div>
          <h1 className="t-display">Hello {firstName} 👋</h1>
          <p className="text-muted text-sm mt-1">Ready to improve your English today?</p>
        </div>
      </header>

      {/* A learner with no history lands here first. A dashboard of zeros is a
          review surface being used as a landing surface, so give them the one
          action that fills it — and hide the empty panels below. */}
      {fresh && (
        <div className="card text-center py-9">
          <h2 className="t-section text-lg mb-1">Ready when you are</h2>
          <p className="text-muted text-sm mb-5 max-w-sm mx-auto">
            Your scores, skills and streak fill in after your first conversation. It takes
            about two minutes.
          </p>
          <Link href="/practice" className="btn btn-primary inline-block px-6 py-3">
            🎙️ Start your first conversation
          </Link>
        </div>
      )}

      {!fresh && (
        <>
          <HeroCard
            name={firstName}
            goalPct={goalPct}
            minutesToday={minutesToday}
            goalMinutes={DAILY_GOAL_MIN}
          />

          <LevelCard
            level={ov.current_level}
            levelName={LEVEL_NAMES[ov.current_level]}
            pct={overallPct}
            nextLevel={ov.next_level}
            etaDays={eta}
          />

          <SkillGrid scores={ov.latest_scores} />

          <TodayPlan plan={plan} />

          <QuickStats
            streak={ov.streak_days}
            assessments={ov.assessments_count}
            level={ov.current_level}
            levelName={LEVEL_NAMES[ov.current_level]}
            spark={spark}
          />

          <div className="grid xl:grid-cols-2 gap-4">
            <RecentActivity rows={assess} />
            <div className="card !p-5">
              <div className="flex items-center justify-between mb-3">
                <div className="t-section">Overall progress</div>
                <span className="t-caption">Last {trend.length} assessments</span>
              </div>
              <OverallTrend points={trend} />
              {spark.length >= 2 && (
                <p className="mt-3 rounded-xl border border-line surface px-3.5 py-2.5 text-[13px] flex items-center gap-2">
                  <span className="icon-badge" style={{ ["--tint" as string]: "rgb(var(--c-good))", width: 26, height: 26 }}>
                    <Icon.chart size={13} />
                  </span>
                  {spark[spark.length - 1] >= spark[0]
                    ? "You're improving. Keep practising consistently."
                    : "Scores dipped recently — a short session today usually turns it round."}
                </p>
              )}
            </div>
          </div>

          <div className="grid xl:grid-cols-2 gap-4">
            <div className="card !p-5">
              <div className="t-section mb-3">Skill radar</div>
              <SkillRadar scores={ov.latest_scores} />
            </div>
            <div className="card !p-5">
              <div className="t-section mb-3">Study plan</div>
              <PlanPanel plan={plan} />
            </div>
          </div>

          <div className="card !p-5">
            <div className="t-section mb-3">Top gaps</div>
            <GapsPanel gaps={gaps} />
          </div>

          {currentUser && <ReadingSummary userId={currentUser} />}

          <div className="card !p-5">
            <div className="flex justify-between items-center mb-3 gap-3 flex-wrap">
              <div className="t-section">Recent assessments</div>
              <ReportButtons userId={currentUser} />
            </div>
            <AssessmentsTable rows={assess} />
          </div>
        </>
      )}

      {/* Level first for a new learner: it sets the difficulty of everything
          else. For everyone else it sits below the review, since it is a
          setting, not a reading. */}
      <div className="card !p-5">
        <div className="t-section mb-3">Your level — pick where you want to practice</div>
        <LevelPicker current={currentLevel} onSet={setLevel} />
      </div>

      {/* Last: a year of squares is a look-back, not something you act on. */}
      {currentUser && !fresh && (
        <StreakHeatmap userId={currentUser} currentStreak={ov.streak_days} />
      )}

      <QuoteStrip />
    </div>
  );
}
