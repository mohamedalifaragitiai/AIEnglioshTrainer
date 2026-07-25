"use client";

import {
  PolarAngleAxis,
  PolarGrid,
  PolarRadiusAxis,
  Radar,
  RadarChart,
  ResponsiveContainer,
} from "recharts";
import { DIMENSIONS, type Dimension } from "@/lib/types";

export function SkillRadar({ scores }: { scores: Partial<Record<Dimension, number | null>> }) {
  const data = DIMENSIONS.map((d) => ({ skill: d.slice(0, 5), value: scores[d] ?? 0 }));
  return (
    <ResponsiveContainer width="100%" height={300}>
      <RadarChart data={data} outerRadius="72%">
        <PolarGrid stroke="#334155" />
        <PolarAngleAxis dataKey="skill" tick={{ fill: "#94a3b8", fontSize: 11 }} />
        <PolarRadiusAxis domain={[0, 100]} tick={false} axisLine={false} />
        <Radar dataKey="value" stroke="#2dd4bf" fill="#2dd4bf" fillOpacity={0.3} />
      </RadarChart>
    </ResponsiveContainer>
  );
}
