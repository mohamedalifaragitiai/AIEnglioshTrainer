"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { Activity } from "@/lib/types";

/** Four bands, so one session and five sessions do not look identical. */
function shade(count: number): string {
  if (count === 0) return "bg-panel2";
  if (count === 1) return "bg-accent/30";
  if (count === 2) return "bg-accent/55";
  if (count <= 4) return "bg-accent/75";
  return "bg-accent";
}

export function StreakHeatmap({ userId, currentStreak }: { userId: string; currentStreak: number }) {
  const [data, setData] = useState<Activity | null>(null);

  useEffect(() => {
    api
      .activity(userId, 364)
      .then(setData)
      .catch(() => setData(null));
  }, [userId]);

  if (!data) return null;

  // Columns are weeks and rows are weekdays — the shape people already read.
  // The leading blanks align the first column to the right weekday; without
  // them every row would be shifted and the calendar would lie.
  const pad = data.cells.length ? data.cells[0].weekday : 0;

  return (
    <div className="card">
      <div className="flex justify-between items-baseline flex-wrap gap-2">
        <h2 className="font-semibold">Practice streak</h2>
        <span className="text-muted text-xs">
          {data.active_days} active days · current {currentStreak}d · longest{" "}
          {data.longest_streak}d
        </span>
      </div>

      <div className="overflow-x-auto pb-1.5">
        <div className="grid grid-flow-col gap-[3px] mt-3.5" style={{ gridTemplateRows: "repeat(7, 12px)" }}>
          {Array.from({ length: pad }).map((_, i) => (
            <span key={`pad${i}`} className="w-3 h-3 rounded-[3px]" />
          ))}
          {data.cells.map((c) => (
            <span
              key={c.date}
              title={`${c.date}: ${c.count} session${c.count === 1 ? "" : "s"}`}
              className={`w-3 h-3 rounded-[3px] ${shade(c.count)}`}
            />
          ))}
        </div>
      </div>

      <div className="text-dim text-[11px] mt-2 flex items-center gap-1">
        Less
        {[0, 1, 2, 3, 5].map((n) => (
          <span key={n} className={`w-3 h-3 rounded-[3px] ${shade(n)}`} />
        ))}
        More
      </div>
    </div>
  );
}
