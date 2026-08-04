"use client";

import Link from "next/link";
import { DIMENSIONS, type Dimension, type Assessment, type Plan } from "@/lib/types";
import { Icon, SKILL_ICON } from "@/components/icons";
import { SKILL_FALLBACK } from "@/components/widgets";

/**
 * The Home screen's cards.
 *
 * Every number here comes from an endpoint that already existed. Where the
 * design called for something the backend does not track, the card either
 * derives it honestly from real data (the daily-goal ring counts recorded
 * session seconds) or is left out — see the notes on each.
 */

const tint = (skill: string) => `var(--sk-${skill}, ${SKILL_FALLBACK[skill] ?? "#7c6cf6"})`;

/** Score -> the word a learner actually wants: how am I doing on this one. */
export function skillStatus(score: number | null | undefined): string {
  if (score == null) return "Start practicing";
  if (score >= 85) return "Excellent";
  if (score >= 70) return "Good";
  if (score >= 55) return "Improving";
  return "Needs work";
}

function scoreTone(score: number): string {
  if (score >= 85) return "rgb(var(--c-good))";
  if (score >= 70) return "var(--sk-fluency)";
  if (score >= 55) return "rgb(var(--c-warn))";
  return "var(--sk-listening)";
}

/* -------------------------------------------------------------- hero ------ */

export function HeroCard({
  name,
  goalPct,
  minutesToday,
  goalMinutes,
}: {
  name: string;
  goalPct: number;
  minutesToday: number;
  goalMinutes: number;
}) {
  const left = Math.max(0, goalMinutes - minutesToday);
  return (
    <section className="hero">
      <div className="flex-1 min-w-[min(100%,280px)]">
        <h2 className="t-display mb-1.5">Keep going, you&apos;re doing great.</h2>
        <p className="text-muted text-sm mb-5">
          {left > 0
            ? `Continue your daily practice — about ${left} minute${left === 1 ? "" : "s"} to go.`
            : `You have hit today's ${goalMinutes} minutes. Anything more is a bonus.`}
        </p>
        <Link href="/practice" className="btn btn-primary inline-flex items-center gap-2 px-5 py-2.5">
          <Icon.play size={15} />
          Continue practice
          <Icon.arrow size={15} />
        </Link>
      </div>

      <div className="flex items-center gap-5">
        <div
          className="ring"
          style={{ ["--p" as string]: goalPct }}
          role="img"
          aria-label={`Daily goal ${goalPct} percent complete`}
        >
          <div className="relative text-center leading-tight">
            <b className="t-stat block">{goalPct}%</b>
            <span className="t-label block mt-1">daily goal</span>
          </div>
        </div>
        {/* No mascot asset exists and this app ships nothing it cannot serve
            offline, so the space holds an abstract mark rather than a stock
            character or a gap. */}
        <svg width="104" height="104" viewBox="0 0 104 104" aria-hidden="true" className="hidden sm:block opacity-90">
          <defs>
            <linearGradient id="heroGrad" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0%" stopColor="rgb(var(--c-accent))" />
              <stop offset="100%" stopColor="rgb(var(--c-accent2))" />
            </linearGradient>
          </defs>
          <circle cx="52" cy="52" r="46" fill="url(#heroGrad)" opacity="0.12" />
          <circle cx="52" cy="52" r="30" fill="url(#heroGrad)" opacity="0.18" />
          {[0, 1, 2, 3, 4].map((i) => (
            <rect
              key={i}
              x={30 + i * 10}
              y={52 - (i % 2 ? 20 : 12)}
              width="5"
              height={(i % 2 ? 20 : 12) * 2}
              rx="2.5"
              fill="url(#heroGrad)"
            />
          ))}
        </svg>
      </div>
    </section>
  );
}

/* ------------------------------------------------------------- level ------ */

export function LevelCard({
  level,
  levelName,
  pct,
  nextLevel,
  etaDays,
}: {
  level: number;
  levelName: string;
  pct: number;
  nextLevel: number | null;
  etaDays: number | null;
}) {
  return (
    <section className="card !p-5">
      <div className="flex items-start justify-between gap-4 mb-4">
        <div className="t-section">Your level</div>
        {nextLevel != null && (
          <div className="flex items-center gap-2 rounded-xl bg-panel2 border border-line px-3 py-1.5">
            <Icon.trophy size={15} />
            <span className="leading-tight">
              <span className="t-label block">next level</span>
              <b className="text-[13px]">Level {nextLevel}</b>
            </span>
          </div>
        )}
      </div>

      <div className="flex items-center gap-5 flex-wrap">
        {/* Hexagon, per the mockup — a clip-path, so it costs no image. */}
        <div
          className="grid place-items-center shrink-0 w-[86px] h-[92px] text-center"
          style={{
            clipPath: "polygon(50% 0%, 100% 25%, 100% 75%, 50% 100%, 0% 75%, 0% 25%)",
            background: "var(--grad-accent)",
          }}
        >
          <span className="text-white">
            <b className="block text-[30px] font-bold leading-none">{level}</b>
            <span className="block text-[9.5px] uppercase tracking-widest mt-1 opacity-90">
              level
            </span>
          </span>
        </div>

        <div className="flex-1 min-w-[min(100%,220px)]">
          <div className="flex items-baseline gap-2 mb-1">
            <b className="t-stat text-good">{pct}%</b>
            <span className="text-muted text-sm">overall progress</span>
          </div>
          <p className="t-caption mb-3">{levelName}</p>
          <div className="track" style={{ ["--tint" as string]: "rgb(var(--c-good))" }}>
            <i style={{ width: `${pct}%` }} />
          </div>
          <p className="t-caption mt-2">
            {nextLevel != null
              ? `Only ${Math.max(0, 100 - pct)}% to reach level ${nextLevel}` +
                (etaDays != null ? ` · about ${etaDays} day${etaDays === 1 ? "" : "s"}` : "")
              : "You are at the top level — keep it sharp."}
          </p>
        </div>
      </div>
    </section>
  );
}

/* ------------------------------------------------------------ skills ------ */

export function SkillGrid({
  scores,
}: {
  scores: Partial<Record<Dimension, number | null>>;
}) {
  return (
    <section className="card !p-5">
      <div className="flex items-center justify-between mb-4">
        <div className="t-section">Your skills</div>
        <Link href="/report" className="text-accent text-[13px] font-medium inline-flex items-center gap-1">
          View details <Icon.arrow size={14} />
        </Link>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-3">
        {DIMENSIONS.map((d) => {
          const raw = scores[d];
          const tested = raw != null;
          const value = tested ? Math.round(raw) : null;
          const Glyph = SKILL_ICON[d] ?? Icon.spark;
          return (
            <div
              key={d}
              className="rounded-xl border border-line surface p-4 transition-colors hover:border-accent/40"
            >
              <div className="flex items-center gap-2.5 mb-3">
                <span className="icon-badge" style={{ ["--tint" as string]: tint(d) }}>
                  <Glyph size={17} />
                </span>
                <span className="text-[13px] font-medium capitalize">{d}</span>
              </div>
              {tested ? (
                <>
                  <b className="t-stat block mb-2.5">{value}%</b>
                  <div className="track" style={{ ["--tint" as string]: tint(d) }}>
                    <i style={{ width: `${value}%` }} />
                  </div>
                </>
              ) : (
                <>
                  <b className="block text-[15px] font-medium text-dim mb-3.5">Not tested yet</b>
                  <div className="track-empty" />
                </>
              )}
              <p className="t-caption mt-2.5">{skillStatus(raw)}</p>
            </div>
          );
        })}
      </div>
    </section>
  );
}

/* --------------------------------------------------------- today's plan --- */

export function TodayPlan({ plan }: { plan: Plan | null }) {
  if (!plan || !plan.focus_areas.length) {
    return (
      <section className="card !p-5">
        <div className="t-section mb-2">Today&apos;s plan</div>
        <p className="text-muted text-sm">
          Your plan is written from your scores — finish a conversation and it appears here.
        </p>
      </section>
    );
  }

  // Three focus areas, one activity each, is a session someone will actually
  // finish. The estimate is the app's own two-minute conversation unit.
  const items = plan.focus_areas.slice(0, 3);
  const minutes = items.length * 2;

  return (
    <section className="card !p-5">
      <div className="t-section mb-4">Today&apos;s plan</div>
      <div className="flex gap-5 flex-wrap">
        <ul className="flex-1 min-w-[min(100%,240px)] space-y-3">
          {items.map((f) => (
            <li key={f.skill} className="flex gap-3">
              {/* No completion tracking exists, so every item shows as pending
                  rather than inventing ticks the app cannot honour. */}
              <span
                className="icon-badge mt-0.5"
                style={{ ["--tint" as string]: tint(f.skill), width: 26, height: 26 }}
              >
                <Icon.check size={13} />
              </span>
              <span>
                <b className="block text-[13.5px] capitalize">{f.skill}</b>
                <span className="t-caption">{f.activities[0] ?? f.why}</span>
              </span>
            </li>
          ))}
        </ul>

        <div className="w-full sm:w-auto sm:min-w-[168px] rounded-xl border border-line surface p-4 flex flex-col justify-between gap-3">
          <div>
            <span className="t-label flex items-center gap-1.5">
              <Icon.clock size={13} /> estimated time
            </span>
            <b className="t-stat block mt-1.5">
              {minutes}
              <span className="text-sm font-medium text-muted ml-1">min</span>
            </b>
          </div>
          <Link href="/practice" className="btn btn-primary w-full text-center py-2">
            Start plan
          </Link>
        </div>
      </div>
    </section>
  );
}

/* --------------------------------------------------------- quick stats ---- */

export function QuickStats({
  streak,
  assessments,
  level,
  levelName,
  spark,
}: {
  streak: number;
  assessments: number;
  level: number;
  levelName: string;
  spark: number[];
}) {
  const tiles = [
    {
      icon: Icon.flame,
      tone: "var(--sk-listening)",
      value: String(streak),
      label: streak === 1 ? "Day streak" : "Day streak",
      sub: streak > 0 ? "Keep it up" : "Start today",
    },
    {
      icon: Icon.trophy,
      tone: "var(--sk-grammar)",
      value: String(assessments),
      label: "Assessments",
      sub: "Completed",
    },
    {
      icon: Icon.shield,
      tone: "var(--sk-pronunciation)",
      value: String(level),
      label: levelName,
      sub: "Current level",
    },
  ];

  return (
    <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
      {tiles.map((t) => (
        <section key={t.label} className="card !p-4">
          <div className="flex items-start gap-3">
            <span className="icon-badge" style={{ ["--tint" as string]: t.tone }}>
              <t.icon size={17} />
            </span>
            <div className="flex-1 min-w-0">
              <b className="t-stat block">{t.value}</b>
              <p className="text-[13px] font-medium mt-1 truncate">{t.label}</p>
              <p className="t-caption">{t.sub}</p>
            </div>
            <Sparkline values={spark} tone={t.tone} />
          </div>
        </section>
      ))}
    </div>
  );
}

/** Last few scores as bars. Deliberately unlabelled — it is a shape, not a chart. */
function Sparkline({ values, tone }: { values: number[]; tone: string }) {
  if (values.length < 2) return null;
  const max = Math.max(...values, 1);
  return (
    <span className="flex items-end gap-[3px] h-8 shrink-0" aria-hidden="true">
      {values.slice(-8).map((v, i) => (
        <i
          key={i}
          className="w-[3px] rounded-full block"
          style={{
            height: `${Math.max(12, (v / max) * 100)}%`,
            background: tone,
            opacity: 0.35 + (i / 8) * 0.65,
          }}
        />
      ))}
    </span>
  );
}

/* ------------------------------------------------------ recent activity --- */

export function RecentActivity({ rows }: { rows: Assessment[] }) {
  const recent = [...rows].reverse().slice(0, 5);
  return (
    <section className="card !p-5">
      <div className="flex items-center justify-between mb-4">
        <div className="t-section">Recent activity</div>
        <Link href="/report" className="text-accent text-[13px] font-medium inline-flex items-center gap-1">
          View all <Icon.arrow size={14} />
        </Link>
      </div>

      {recent.length === 0 ? (
        <p className="text-muted text-sm">
          Nothing yet — your first conversation shows up here straight away.
        </p>
      ) : (
        <ul className="space-y-2.5">
          {recent.map((a) => {
            const score = a.overall != null ? Math.round(a.overall) : null;
            return (
              <li key={a.assessment_id} className="flex items-center gap-3">
                <span
                  className="grid place-items-center w-9 h-9 rounded-full text-[12.5px] font-bold shrink-0"
                  style={{
                    color: score == null ? "rgb(var(--c-dim))" : scoreTone(score),
                    background:
                      score == null
                        ? "rgb(var(--c-panel2))"
                        : `color-mix(in srgb, ${scoreTone(score)} 16%, transparent)`,
                  }}
                >
                  {score ?? "—"}
                </span>
                <span className="flex-1 min-w-0">
                  <b className="block text-[13.5px]">Assessment</b>
                  <span className="t-caption">Overall score</span>
                </span>
                <span className="t-caption shrink-0">
                  {new Date(a.created_at).toLocaleDateString(undefined, {
                    month: "short",
                    day: "numeric",
                    year: "numeric",
                  })}
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

/* ---------------------------------------------------------- quote strip --- */

export function QuoteStrip() {
  return (
    <aside className="rounded-2xl border border-line surface px-5 py-4 flex items-center gap-3.5">
      <span className="icon-badge" style={{ ["--tint" as string]: "rgb(var(--c-accent))" }}>
        <Icon.quote size={17} />
      </span>
      <p className="text-[13.5px] text-muted flex-1">
        Practice is the key to success. Keep going and never give up.
      </p>
      <Icon.spark size={16} />
    </aside>
  );
}
