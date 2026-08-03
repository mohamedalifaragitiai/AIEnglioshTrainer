"use client";

import { useEffect, useRef } from "react";
import type { SkillPoint } from "@/lib/types";
import { PLOT_CONFIG, baseLayout, loadPlotly, tone, useThemeKey } from "./plot";

/** Overall score over time. Hover a point for the exact number. */
export function OverallTrend({ points }: { points: SkillPoint[] }) {
  const host = useRef<HTMLDivElement>(null);
  // A dependency, not a value: redraws the chart when the palette changes.
  const theme = useThemeKey();
  const empty = points.length === 0;

  useEffect(() => {
    let cancelled = false;
    const el = host.current;
    if (!el || empty) return;

    void loadPlotly().then((Plotly) => {
      if (cancelled || !host.current) return;
      const x = points.map((p) => p.created_at);
      const y = points.map((p) => Math.round(p.value));

      void Plotly.react(
        host.current,
        [
          {
            x,
            y,
            type: "scatter",
            mode: "lines+markers",
            fill: "tozeroy",
            fillcolor: tone("--c-accent2", 0.16),
            line: { color: tone("--c-accent2"), width: 2.5, shape: "spline", smoothing: 0.6 },
            marker: {
              size: 6,
              color: tone("--c-accent"),
              line: { color: tone("--c-panel"), width: 1.5 },
            },
            hovertemplate: "%{y}%<extra>overall</extra>",
          },
        ] as never,
        {
          ...baseLayout(),
          margin: { l: 34, r: 14, t: 10, b: 34 },
          showlegend: false,
          hovermode: "x unified",
          xaxis: {
            gridcolor: "rgba(0,0,0,0)",
            linecolor: tone("--c-line"),
            tickformat: "%b %d",
            fixedrange: true,
            tickfont: { color: tone("--c-dim") },
          },
          yaxis: {
            range: [0, 100],
            gridcolor: tone("--c-line"),
            zeroline: false,
            fixedrange: true,
            ticksuffix: "%",
            tickfont: { color: tone("--c-dim") },
          },
        } as never,
        PLOT_CONFIG,
      );
    });

    return () => {
      cancelled = true;
      void loadPlotly().then((Plotly) => Plotly.purge(el));
    };
  }, [points, theme, empty]);

  if (empty) {
    return (
      <p className="text-muted text-sm">
        No assessments yet — your trend appears after your first one.
      </p>
    );
  }
  return <div ref={host} style={{ width: "100%", height: 300 }} />;
}
