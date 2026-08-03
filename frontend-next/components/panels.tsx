"use client";

import { api } from "@/lib/api";
import { DIMENSIONS, type Assessment, type GapItem, type Plan } from "@/lib/types";

export function StatTile({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="card">
      <div className="text-muted text-sm">{label}</div>
      <div className="text-3xl font-bold">{value}</div>
      {sub && <div className="text-accent text-xs mt-0.5">{sub}</div>}
    </div>
  );
}

export function GapsPanel({ gaps }: { gaps: GapItem[] }) {
  if (!gaps.length) return <div className="text-muted text-sm">No assessments yet.</div>;
  return (
    <div className="space-y-3">
      {gaps.slice(0, 5).map((g) => (
        <div key={g.skill}>
          <div className="flex justify-between text-sm">
            <span className="capitalize">{g.skill}</span>
            <span className="text-muted">
              {Math.round(g.score)}/{Math.round(g.target)}
            </span>
          </div>
          <div className="h-2 bg-panel2 rounded overflow-hidden">
            <div
              className="h-full"
              style={{
                width: `${g.score}%`,
                background: "linear-gradient(90deg,rgb(var(--c-bad)),rgb(var(--c-good)))",
              }}
            />
          </div>
        </div>
      ))}
    </div>
  );
}

export function PlanPanel({ plan }: { plan: Plan | null }) {
  if (!plan) return <div className="text-muted text-sm">No plan yet.</div>;
  return (
    <div>
      <p className="mb-2">{plan.summary}</p>
      <div className="text-muted text-xs mb-3">
        difficulty {plan.difficulty} · horizon {plan.horizon.replace("_", " ")}
        {plan.estimated_days_to_next_level != null &&
          ` · ~${plan.estimated_days_to_next_level}d to level ${plan.next_level}`}
      </div>
      <div className="space-y-3">
        {plan.focus_areas.map((f) => (
          <div key={f.skill}>
            <div className="font-semibold capitalize">
              {f.skill} <span className="text-muted font-normal">({Math.round(f.score)})</span>
            </div>
            <div className="text-sm text-fg">{f.activities[0]}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

export function ReportButtons({ userId }: { userId: string }) {
  const fmts: [string, string][] = [
    ["json", "JSON"],
    ["csv", "CSV"],
    ["xlsx", "Excel"],
    ["pdf", "PDF"],
  ];
  return (
    <div className="flex items-center gap-2">
      <span className="text-muted text-xs">Download report:</span>
      {fmts.map(([f, label]) => (
        <a key={f} className="btn" href={api.reportUrl(userId, f)} target="_blank" rel="noreferrer">
          {label}
        </a>
      ))}
    </div>
  );
}

export function AssessmentsTable({ rows }: { rows: Assessment[] }) {
  const recent = rows.slice(-12).reverse();
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-muted">
            <th className="text-left py-1.5 px-2">when</th>
            <th className="text-left py-1.5 px-2">overall</th>
            {DIMENSIONS.map((d) => (
              <th key={d} className="text-left py-1.5 px-2">
                {d.slice(0, 4)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {recent.map((a) => (
            <tr key={a.assessment_id} className="border-t border-line">
              <td className="py-1.5 px-2 text-muted">
                {new Date(a.created_at).toLocaleDateString(undefined, {
                  month: "short",
                  day: "numeric",
                })}
              </td>
              <td className="py-1.5 px-2 font-semibold">
                {a.overall != null ? Math.round(a.overall) : "—"}
              </td>
              {DIMENSIONS.map((d) => (
                <td key={d} className="py-1.5 px-2">
                  {a[d] != null ? Math.round(a[d] as number) : "·"}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
