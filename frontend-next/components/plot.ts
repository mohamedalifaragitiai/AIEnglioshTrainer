"use client";

import { useEffect, useState } from "react";

/**
 * Shared Plotly setup for the dashboard's charts.
 *
 * Plotly is imported dynamically by the components that draw: it is a 1.1MB
 * bundle that touches `document` at module scope, so a static import would both
 * break the server render and put the whole library in the first page payload.
 *
 * Every colour is read from the stylesheet at draw time rather than passed in.
 * That is what keeps a chart in step with the theme toggle — the previous charts
 * hardcoded slate hex values and stayed dark-themed on a white page.
 */

/** The three calls the dashboard makes. See types/plotly-basic-dist-min.d.ts. */
export type PlotlyApi = {
  react: (el: HTMLElement, data: unknown[], layout?: unknown, config?: unknown) => Promise<unknown>;
  newPlot: (
    el: HTMLElement,
    data: unknown[],
    layout?: unknown,
    config?: unknown,
  ) => Promise<unknown>;
  purge: (el: HTMLElement) => void;
};

let cached: Promise<PlotlyApi> | null = null;

export function loadPlotly(): Promise<PlotlyApi> {
  // The bundle is UMD: under Next's ESM interop the module object itself is the
  // API in some builds and lives on .default in others. Accept both.
  if (cached === null) {
    cached = import("plotly.js-basic-dist-min").then(
      (m) => ((m as { default?: unknown }).default ?? m) as PlotlyApi,
    );
  }
  return cached;
}

export const PLOT_CONFIG = { responsive: true, displaylogo: false, displayModeBar: false };

export function cssVar(name: string): string {
  if (typeof document === "undefined") return "";
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

/** A `--c-*` triplet ("124 108 246") as a css colour, optionally with alpha. */
export function tone(name: string, alpha = 1): string {
  const triplet = cssVar(name);
  if (!triplet) return "#7c6cf6";
  return alpha === 1 ? `rgb(${triplet})` : `rgba(${triplet.replace(/\s+/g, ",")},${alpha})`;
}

/** #rrggbb → rgba(), for the per-skill tokens which are stored as hex. */
export function hexAlpha(hex: string, alpha: number): string {
  const h = hex.replace("#", "").trim();
  if (h.length !== 6) return hex;
  const n = parseInt(h, 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${alpha})`;
}

export function baseLayout() {
  return {
    paper_bgcolor: "rgba(0,0,0,0)",
    plot_bgcolor: "rgba(0,0,0,0)",
    font: {
      color: tone("--c-muted"),
      family: 'ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif',
      size: 11.5,
    },
    // Drag is off deliberately: Plotly's drag-to-zoom captures touchmove, and a
    // chart that swallows the scroll gesture strands a phone user mid-page.
    dragmode: false as const,
    hoverlabel: {
      bgcolor: tone("--c-panel2"),
      bordercolor: tone("--c-line"),
      font: { color: tone("--c-text"), size: 12 },
    },
  };
}

/**
 * The current theme, re-read whenever it changes.
 *
 * The toggle keeps its state locally and writes `data-theme` on <html>, so there
 * is no context to subscribe to — but the charts must redraw when the palette
 * changes or they stay in the previous theme's colours. Watching the attribute
 * is what makes them independent of where the toggle happens to live.
 */
export function useThemeKey(): string {
  const [key, setKey] = useState<string>("");
  useEffect(() => {
    const read = () => setKey(document.documentElement.dataset.theme ?? "dark");
    read();
    const mo = new MutationObserver(read);
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => mo.disconnect();
  }, []);
  return key;
}
