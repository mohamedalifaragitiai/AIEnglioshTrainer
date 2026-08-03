"use client";

import { DIMENSIONS, LEVEL_NAMES, type Dimension } from "@/lib/types";

/**
 * One colour per skill, read from the stylesheet's `--sk-*` tokens so a skill is
 * the same colour in its bar, its card and its point on the radar — and so the
 * light theme's darker variants apply without a second table here. The hex
 * values are the dark-theme fallback for the server render, where there is no
 * document to read from.
 */
export const SKILL_FALLBACK: Record<string, string> = {
  pronunciation: "#8b5cf6",
  grammar: "#f59e0b",
  vocabulary: "#ec4899",
  listening: "#f97316",
  fluency: "#3b82f6",
  confidence: "#22c55e",
  coherence: "#06b6d4",
  relevance: "#14b8a6",
};

export function SkillBars({ scores }: { scores: Partial<Record<Dimension, number | null>> }) {
  return (
    <div className="space-y-2.5">
      {DIMENSIONS.map((d) => {
        const v = Math.round(scores[d] ?? 0);
        // var() with the hex as fallback: correct on the server render, and
        // correct again in whichever theme the browser ends up in.
        const c = `var(--sk-${d}, ${SKILL_FALLBACK[d]})`;
        return (
          <div key={d}>
            <div className="flex justify-between text-sm mb-1">
              <span className="capitalize">{d}</span>
              <span className="text-muted">{v}%</span>
            </div>
            <div className="h-2 bg-panel2 rounded overflow-hidden">
              <div
                className="h-full rounded transition-all duration-700"
                style={{
                  width: `${v}%`,
                  background: c,
                  backgroundImage: `linear-gradient(90deg, color-mix(in srgb, ${c} 45%, transparent), ${c})`,
                }}
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
            i === current ? "border-accent bg-accent/10" : "border-line bg-panel2 hover:border-accent2"
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
  const col = v > 0.96 ? "#ef4444" : v > 0.88 ? "#fb923c" : v > 0.7 ? "#fbbf24" : "#7c6cf6";
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
