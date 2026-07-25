"use client";

import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { SkillPoint } from "@/lib/types";

export function OverallTrend({ points }: { points: SkillPoint[] }) {
  const data = points.map((p) => ({
    date: new Date(p.created_at).toLocaleDateString(undefined, { month: "short", day: "numeric" }),
    value: Math.round(p.value * 10) / 10,
  }));
  return (
    <ResponsiveContainer width="100%" height={300}>
      <LineChart data={data} margin={{ top: 8, right: 12, bottom: 4, left: -18 }}>
        <CartesianGrid stroke="#334155" strokeDasharray="3 3" />
        <XAxis dataKey="date" tick={{ fill: "#94a3b8", fontSize: 11 }} />
        <YAxis domain={[0, 100]} tick={{ fill: "#94a3b8", fontSize: 11 }} />
        <Tooltip
          contentStyle={{ background: "#1e293b", border: "1px solid #334155", borderRadius: 8 }}
          labelStyle={{ color: "#94a3b8" }}
        />
        <Line
          type="monotone"
          dataKey="value"
          stroke="#818cf8"
          strokeWidth={2}
          dot={{ fill: "#2dd4bf", r: 3 }}
        />
      </LineChart>
    </ResponsiveContainer>
  );
}
