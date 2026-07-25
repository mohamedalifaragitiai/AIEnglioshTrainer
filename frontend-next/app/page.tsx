"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { Assessment, GapItem, Plan, ProgressOverview, SkillPoint } from "@/lib/types";
import { useUser } from "./user-context";
import { SkillRadar } from "@/components/SkillRadar";
import { OverallTrend } from "@/components/OverallTrend";
import {
  AssessmentsTable,
  GapsPanel,
  PlanPanel,
  ReportButtons,
  StatTile,
} from "@/components/panels";

export default function Dashboard() {
  const { currentUser } = useUser();
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
  if (err) return <p className="text-red-400">Could not load: {err}</p>;
  if (!ov) return <p className="text-muted">Loading…</p>;

  const eta = ov.estimated_days_to_next_level;
  return (
    <div className="space-y-4">
      {ov.assessments_count === 0 && (
        <div className="rounded-lg border border-yellow-700 bg-yellow-950/40 text-yellow-300 px-4 py-2.5 text-sm">
          No assessments yet — click <b>Load demo data</b> above, or use <b>Practice</b>.
        </div>
      )}

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatTile
          label="Level (0–5)"
          value={String(ov.current_level)}
          sub={ov.next_level != null ? `next: ${ov.next_level}` : "top level"}
        />
        <StatTile label="Streak" value={`${ov.streak_days}d`} />
        <StatTile
          label="Latest overall"
          value={ov.latest_overall != null ? String(Math.round(ov.latest_overall)) : "—"}
          sub={`${ov.assessments_count} assessments`}
        />
        <StatTile
          label="Days to next level"
          value={eta != null ? String(eta) : "—"}
          sub={eta != null ? "at current pace" : "flat / need data"}
        />
      </div>

      <div className="grid md:grid-cols-2 gap-4">
        <div className="card">
          <div className="card-title">Skill radar (latest)</div>
          <SkillRadar scores={ov.latest_scores} />
        </div>
        <div className="card">
          <div className="card-title">Overall trend</div>
          <OverallTrend points={trend} />
        </div>
      </div>

      <div className="grid md:grid-cols-2 gap-4">
        <div className="card">
          <div className="card-title">Top gaps</div>
          <GapsPanel gaps={gaps} />
        </div>
        <div className="card">
          <div className="card-title">Study plan</div>
          <PlanPanel plan={plan} />
        </div>
      </div>

      <div className="card">
        <div className="flex justify-between items-center mb-1">
          <div className="card-title mb-0">Recent assessments</div>
          <ReportButtons userId={currentUser} />
        </div>
        <AssessmentsTable rows={assess} />
      </div>
    </div>
  );
}
