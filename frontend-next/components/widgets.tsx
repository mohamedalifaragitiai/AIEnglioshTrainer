"use client";

import { DIMENSIONS, LEVEL_NAMES, type Dimension } from "@/lib/types";

export const SKILL_COLORS: Record<string, string> = {
  pronunciation: "#2dd4bf",
  grammar: "#818cf8",
  vocabulary: "#f472b6",
  listening: "#60a5fa",
  fluency: "#34d399",
  confidence: "#fbbf24",
  coherence: "#a78bfa",
  relevance: "#fb923c",
};

export function SkillBars({ scores }: { scores: Partial<Record<Dimension, number | null>> }) {
  return (
    <div className="space-y-2.5">
      {DIMENSIONS.map((d) => {
        const v = Math.round(scores[d] ?? 0);
        const c = SKILL_COLORS[d];
        return (
          <div key={d}>
            <div className="flex justify-between text-sm mb-1">
              <span className="capitalize">{d}</span>
              <span className="text-muted">{v}%</span>
            </div>
            <div className="h-2 bg-panel2 rounded overflow-hidden">
              <div
                className="h-full rounded transition-all duration-700"
                style={{ width: `${v}%`, background: `linear-gradient(90deg,${c}88,${c})` }}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}

export function LevelPicker({
  current,
  onSet,
}: {
  current: number;
  onSet: (level: number) => void;
}) {
  return (
    <div className="flex gap-2 flex-wrap">
      {LEVEL_NAMES.map((n, i) => (
        <button
          key={i}
          onClick={() => onSet(i)}
          className={`flex-1 min-w-[96px] text-center rounded-xl border px-2 py-2.5 transition ${
            i === current ? "border-accent bg-[#0f2b28]" : "border-line bg-panel2 hover:border-accent2"
          }`}
        >
          <div className="text-xl font-extrabold">{i}</div>
          <div className="text-[11px] text-muted">{n}</div>
        </button>
      ))}
    </div>
  );
}

export function Gauge({
  label,
  value,
  sub,
}: {
  label: string;
  value: number | null;
  sub?: string;
}) {
  const v = value == null ? 0 : Math.max(0, Math.min(1, value));
  const C = 2 * Math.PI * 44;
  const col = v > 0.96 ? "#ef4444" : v > 0.88 ? "#fb923c" : v > 0.7 ? "#fbbf24" : "#2dd4bf";
  return (
    <div className="card flex flex-col items-center gap-1.5">
      <div className="relative w-28 h-28">
        <svg width="112" height="112" className="-rotate-90">
          <circle cx="56" cy="56" r="44" fill="none" stroke="#26375a" strokeWidth="10" />
          <circle
            cx="56"
            cy="56"
            r="44"
            fill="none"
            stroke={col}
            strokeWidth="10"
            strokeLinecap="round"
            strokeDasharray={C}
            strokeDashoffset={C * (1 - v)}
          />
        </svg>
        <div className="absolute inset-0 grid place-items-center text-center">
          <div>
            <div className="text-xl font-extrabold">{value == null ? "—" : Math.round(v * 100) + "%"}</div>
            <div className="text-[11px] text-muted">{sub}</div>
          </div>
        </div>
      </div>
      <div className="text-sm text-muted font-semibold">{label}</div>
    </div>
  );
}
