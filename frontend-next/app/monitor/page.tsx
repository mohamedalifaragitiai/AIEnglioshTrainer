"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { Stats } from "@/lib/types";
import { Gauge } from "@/components/widgets";

const DEG_COLORS = ["#34d399", "#fbbf24", "#fb923c", "#f87171", "#ef4444"];

export default function Monitor() {
  const [s, setS] = useState<Stats | null>(null);

  useEffect(() => {
    const tick = () => api.stats().then(setS).catch(() => {});
    tick();
    const id = setInterval(tick, 2000);
    return () => clearInterval(id);
  }, []);

  if (!s) return <p className="text-muted">Loading system stats…</p>;

  const R = s.resources;
  const gauges = [
    { k: "VRAM", v: R.vram ?? null, sub: s.vram_used_gb != null ? `${s.vram_used_gb}/${s.vram_total_gb} GB` : "" },
    { k: "GPU", v: R.gpu_util ?? null, sub: "utilization" },
    { k: "CPU", v: R.cpu ?? null, sub: "" },
    { k: "RAM", v: R.ram ?? null, sub: "" },
    { k: "Disk", v: R.disk ?? null, sub: "" },
  ];

  return (
    <div className="space-y-4">
      <div className="card">
        <div className="flex justify-between items-center">
          <div className="card-title mb-0">System — live utilization</div>
          <div className="flex items-center gap-2">
            <span className="text-muted text-xs">degradation</span>
            <div className="flex gap-1.5">
              {[0, 1, 2, 3].map((i) => (
                <span
                  key={i}
                  className="w-6 h-2 rounded"
                  style={{
                    background:
                      s.degradation_level > i ? DEG_COLORS[Math.min(s.degradation_level, 4)] : "#293a5a",
                  }}
                />
              ))}
            </div>
            <span className="text-muted text-xs">
              level {s.degradation_level}
              {s.degradation_level === 0 ? " (normal)" : ""}
            </span>
          </div>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4 mt-3">
          {gauges.map((g) => (
            <Gauge key={g.k} label={g.k} value={g.v} sub={g.sub} />
          ))}
        </div>
      </div>

      <div className="card">
        <div className="card-title">Models</div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-muted">
                <th className="text-left py-1.5 px-2">model</th>
                <th className="text-left py-1.5 px-2">kind</th>
                <th className="text-left py-1.5 px-2">status</th>
                <th className="text-left py-1.5 px-2">VRAM</th>
              </tr>
            </thead>
            <tbody>
              {s.models.map((m) => (
                <tr key={m.name} className="border-t border-line">
                  <td className="py-1.5 px-2">{m.name}</td>
                  <td className="py-1.5 px-2 text-muted">{m.kind}</td>
                  <td className="py-1.5 px-2">
                    <span
                      className={`pill ${
                        m.status === "loaded"
                          ? "bg-emerald-900 text-emerald-300"
                          : m.status === "not_loaded" || m.status === "disabled"
                            ? ""
                            : "bg-red-950 text-red-300"
                      }`}
                    >
                      {m.status}
                    </span>
                  </td>
                  <td className="py-1.5 px-2 text-muted">{m.vram_gb} GB</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="text-muted text-xs mt-3">
          {s.models_loaded} model(s) loaded · ceiling {Math.round(s.ceiling * 100)}% · VRAM{" "}
          {s.vram_used_gb ?? "?"}/{s.vram_total_gb ?? "?"} GB
        </div>
      </div>
    </div>
  );
}
