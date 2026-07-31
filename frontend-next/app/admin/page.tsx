"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { api, AuthError } from "@/lib/api";
import { LEVEL_NAMES, type AdminOverview, type AdminUserRow } from "@/lib/types";
import { StatTile } from "@/components/panels";
import { useUser } from "../user-context";

type SortKey = "display_name" | "assessments" | "sessions" | "avg_overall" | "last_active";

/** "3 days ago" reads faster than a timestamp when scanning a roster. */
function sinceLabel(iso: string | null): string {
  if (!iso) return "never";
  const days = Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000);
  if (days <= 0) return "today";
  if (days === 1) return "yesterday";
  if (days < 30) return `${days} days ago`;
  return new Date(iso).toISOString().slice(0, 10);
}

export default function AdminPage() {
  const { signedInAs, setCurrentUser } = useUser();
  const router = useRouter();
  const [data, setData] = useState<AdminOverview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<SortKey>("last_active");

  const load = () => {
    setError(null);
    api
      .adminOverview()
      .then(setData)
      .catch((e) => {
        // 403 is the ordinary answer for a non-admin, not a fault to debug:
        // say so plainly instead of showing a raw error body.
        if (e instanceof AuthError) {
          setError(
            e.status === 403
              ? "This page is for admin accounts only."
              : "Your session has ended — sign in again.",
          );
        } else {
          setError((e as Error).message);
        }
      });
  };

  useEffect(load, [signedInAs]);

  const rows = useMemo(() => {
    if (!data) return [];
    const q = query.trim().toLowerCase();
    const filtered = q
      ? data.users.filter(
          (u) =>
            u.user_id.toLowerCase().includes(q) ||
            (u.display_name || "").toLowerCase().includes(q),
        )
      : data.users;
    return [...filtered].sort((a, b) => {
      switch (sort) {
        case "display_name":
          return (a.display_name || a.user_id).localeCompare(b.display_name || b.user_id);
        case "last_active":
          // Never-active sorts last rather than first — an empty string would
          // otherwise put the people who did nothing at the top of the list.
          return (b.last_active || "").localeCompare(a.last_active || "");
        default:
          return (Number(b[sort]) || 0) - (Number(a[sort]) || 0);
      }
    });
  }, [data, query, sort]);

  const openLearner = (u: AdminUserRow) => {
    setCurrentUser(u.user_id);
    router.push("/");
  };

  if (error) {
    return (
      <div className="card">
        <h2 className="font-semibold mb-1">Admin</h2>
        <p className="text-muted text-sm">{error}</p>
      </div>
    );
  }
  if (!data) return <div className="text-muted">Loading the cohort…</div>;

  const t = data.totals;
  const th = "text-left py-1.5 px-2 font-medium";

  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
        <StatTile label="Learners" value={String(t.users)} sub={`${t.admins} admin`} />
        <StatTile
          label="Active (7 days)"
          value={String(t.active_7d)}
          sub={`${t.active_30d} in 30 days`}
        />
        <StatTile
          label="Sessions"
          value={String(t.sessions)}
          sub={`${t.utterances} utterances`}
        />
        <StatTile
          label="Assessments"
          value={String(t.assessments)}
          sub={t.avg_overall != null ? `avg ${t.avg_overall}` : "—"}
        />
        <StatTile
          label="Never practised"
          value={String(t.never_practised)}
          sub="no session yet"
        />
      </div>

      <div className="card">
        <div className="flex flex-wrap items-center gap-3 mb-3">
          <h2 className="font-semibold flex-1">All learners</h2>
          <input
            className="btn text-left"
            placeholder="Filter by name or id"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <select
            className="btn"
            value={sort}
            onChange={(e) => setSort(e.target.value as SortKey)}
          >
            <option value="last_active">Sort: last active</option>
            <option value="assessments">Sort: assessments</option>
            <option value="sessions">Sort: sessions</option>
            <option value="avg_overall">Sort: average score</option>
            <option value="display_name">Sort: name</option>
          </select>
          <button className="btn" onClick={load}>
            Refresh
          </button>
        </div>
        <p className="text-muted text-xs mb-2">
          {rows.length} of {data.users.length} — select a learner to open their dashboard.
        </p>

        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-muted">
                <th className={th}>Learner</th>
                <th className={th}>Level</th>
                <th className={th}>Streak</th>
                <th className={th}>Sessions</th>
                <th className={th}>Utterances</th>
                <th className={th}>Assessments</th>
                <th className={th}>Latest</th>
                <th className={th}>Average</th>
                <th className={th}>Last active</th>
                <th className={th}>Account</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((u) => (
                <tr
                  key={u.user_id}
                  className="border-t border-line hover:bg-panel2 cursor-pointer"
                  onClick={() => openLearner(u)}
                >
                  {/* React escapes these for us — display_name and user_id are
                      learner-supplied and signup is open on a public deploy. */}
                  <td className="py-1.5 px-2">
                    <div className="font-semibold">{u.display_name || u.user_id}</div>
                    <div className="text-muted text-xs">{u.user_id}</div>
                  </td>
                  <td className="py-1.5 px-2">
                    {u.current_level} · {LEVEL_NAMES[u.current_level]}
                  </td>
                  <td className="py-1.5 px-2">{u.streak_days}</td>
                  <td className="py-1.5 px-2">{u.sessions}</td>
                  <td className="py-1.5 px-2">{u.utterances}</td>
                  <td className="py-1.5 px-2">{u.assessments}</td>
                  <td className="py-1.5 px-2">{u.latest_overall ?? "—"}</td>
                  <td className="py-1.5 px-2">{u.avg_overall ?? "—"}</td>
                  <td className="py-1.5 px-2 text-muted">{sinceLabel(u.last_active)}</td>
                  <td className="py-1.5 px-2">
                    {u.is_admin ? (
                      <span className="pill bg-panel2 text-accent2">admin</span>
                    ) : u.has_password ? (
                      "learner"
                    ) : (
                      <span className="text-muted">no password</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
