"use client";

import { useEffect, useRef } from "react";
import { DIMENSIONS, type Dimension } from "@/lib/types";
import { PLOT_CONFIG, baseLayout, cssVar, loadPlotly, tone, useThemeKey } from "./plot";

/**
 * The skill radar, drawn in cartesian space.
 *
 * The basic Plotly bundle is 1.1MB and has no polar subplot; the bundle that
 * does is 4.9MB. This dashboard gets opened on phones over a tunnel, so the
 * radar is eight lines of trigonometry rather than 3.8MB of extra download.
 */
export function SkillRadar({
  scores,
}: {
  scores: Partial<Record<Dimension, number | null>>;
}) {
  const host = useRef<HTMLDivElement>(null);
  // A dependency, not a value: it changes when the palette does, which is what
  // makes the effect redraw the chart in the new theme.
  const theme = useThemeKey();

  useEffect(() => {
    let cancelled = false;
    const el = host.current;
    if (!el) return;

    void loadPlotly().then((Plotly) => {
      if (cancelled || !host.current) return;
      const n = DIMENSIONS.length;
      const ang = (i: number) => -Math.PI / 2 + (i * 2 * Math.PI) / n;
      const xs: number[] = [];
      const ys: number[] = [];
      const text: string[] = [];
      const colors: string[] = [];

      for (let i = 0; i <= n; i++) {
        const d = DIMENSIONS[i % n];
        const raw = scores[d] ?? 0;
        const v = Math.max(0, Math.min(100, raw)) / 100;
        xs.push(v * Math.cos(ang(i)));
        ys.push(v * Math.sin(ang(i)));
        text.push(`${d} — ${Math.round(raw)}%`);
        colors.push(cssVar(`--sk-${d}`) || tone("--c-accent"));
      }

      const grid = tone("--c-line");
      const shapes = [
        ...[0.25, 0.5, 0.75, 1].map((r) => ({
          type: "circle",
          xref: "x",
          yref: "y",
          x0: -r,
          y0: -r,
          x1: r,
          y1: r,
          line: { color: grid, width: 1 },
        })),
        ...DIMENSIONS.map((_, i) => ({
          type: "line",
          x0: 0,
          y0: 0,
          x1: Math.cos(ang(i)),
          y1: Math.sin(ang(i)),
          line: { color: grid, width: 1 },
        })),
      ];

      const annotations = DIMENSIONS.map((d, i) => ({
        x: 1.17 * Math.cos(ang(i)),
        y: 1.17 * Math.sin(ang(i)),
        text: d.slice(0, 5),
        showarrow: false,
        font: { color: tone("--c-muted"), size: 11 },
      }));

      void Plotly.react(
        host.current,
        [
          {
            x: xs,
            y: ys,
            type: "scatter",
            mode: "lines+markers",
            fill: "toself",
            fillcolor: tone("--c-accent", 0.22),
            line: { color: tone("--c-accent"), width: 2 },
            marker: { size: 7, color: colors, line: { color: tone("--c-panel"), width: 1.5 } },
            text,
            hoverinfo: "text",
            hoveron: "points",
          },
        ] as never,
        {
          ...baseLayout(),
          margin: { l: 10, r: 10, t: 10, b: 10 },
          showlegend: false,
          shapes,
          annotations,
          xaxis: { visible: false, range: [-1.38, 1.38], fixedrange: true },
          yaxis: { visible: false, range: [-1.32, 1.32], fixedrange: true, scaleanchor: "x" },
        } as never,
        PLOT_CONFIG,
      );
    });

    return () => {
      cancelled = true;
      // Plotly leaves resize listeners and chart state on the node; without a
      // purge those survive every route change.
      void loadPlotly().then((Plotly) => Plotly.purge(el));
    };
  }, [scores, theme]);

  return <div ref={host} style={{ width: "100%", height: 300 }} />;
}
