"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import type { ReadingHistory } from "@/lib/types";
import { StatTile } from "./panels";

/**
 * Reading results on the dashboard.
 *
 * They were only visible inside the tab that produced them, so nothing on the
 * learner's main screen ever reflected that they had read anything. Renders
 * nothing until there is at least one attempt — an empty card is worse than no
 * card.
 */
export function ReadingSummary({ userId }: { userId: string }) {
  const [data, setData] = useState<ReadingHistory | null>(null);

  useEffect(() => {
    api
      .readingHistory(userId)
      .then(setData)
      .catch(() => setData(null));
  }, [userId]);

  if (!data || data.attempts.length === 0) return null;

  const s = data.summary;
  const last = data.attempts[0];

  return (
    <div className="card">
      <div className="flex justify-between items-baseline mb-3">
        <h2 className="font-semibold">Reading</h2>
        <Link href="/reading" className="btn text-xs">
          Open reading practice
        </Link>
      </div>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatTile
          label="Attempts"
          value={String(s.attempts)}
          sub={`${s.words_read} words read`}
        />
        <StatTile
          label="Best"
          value={s.best_accuracy != null ? `${s.best_accuracy}%` : "—"}
          sub={s.avg_accuracy != null ? `average ${s.avg_accuracy}%` : "—"}
        />
        <StatTile
          label="Pace"
          value={s.avg_wpm != null ? String(Math.round(s.avg_wpm)) : "—"}
          sub="words per minute"
        />
        <StatTile
          label="Last read"
          value={last.accuracy != null ? `${last.accuracy}%` : "—"}
          sub={last.title ?? ""}
        />
      </div>
    </div>
  );
}
