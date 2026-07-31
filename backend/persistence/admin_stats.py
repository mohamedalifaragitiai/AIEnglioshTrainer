"""Cohort-wide statistics for the admin view.

Deliberately SQL aggregates rather than loading rows and counting in Python: an
admin dashboard that walks every learner's assessments would get slower with
exactly the data it exists to show. Everything here is one pass per question,
with the per-user counts done as correlated subqueries so the whole roster comes
back in a single round trip instead of N+1.

Nothing in here filters by caller — that is the API layer's job. This class will
happily report on everyone, which is the point, and is why the endpoint that
uses it is admin-only.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from backend.coldpath.scoring import DIMENSIONS
from backend.persistence.db import Database

_USER_ROWS = """
SELECT
  u.user_id, u.display_name, u.created_at, u.current_level, u.streak_days, u.is_admin,
  (SELECT COUNT(*) FROM sessions    s WHERE s.user_id = u.user_id) AS sessions,
  (SELECT COUNT(*) FROM utterances  t WHERE t.user_id = u.user_id) AS utterances,
  (SELECT COUNT(*) FROM assessments a WHERE a.user_id = u.user_id) AS assessments,
  (SELECT MAX(a.created_at) FROM assessments a WHERE a.user_id = u.user_id) AS last_assessment_at,
  (SELECT MAX(s.started_at) FROM sessions    s WHERE s.user_id = u.user_id) AS last_session_at,
  (SELECT a.overall FROM assessments a WHERE a.user_id = u.user_id
     ORDER BY a.created_at DESC LIMIT 1) AS latest_overall,
  (SELECT AVG(a.overall) FROM assessments a WHERE a.user_id = u.user_id) AS avg_overall,
  (SELECT COUNT(*) FROM user_credentials c WHERE c.user_id = u.user_id) AS has_password
FROM users u
ORDER BY u.created_at
"""

_AVG_DIMS = f"""
SELECT user_id, {", ".join(f"AVG({d}) AS {d}" for d in DIMENSIONS)}
FROM assessments GROUP BY user_id
"""


def _round(value: float | None, places: int = 1) -> float | None:
    return None if value is None else round(value, places)


class AdminStatsRepository:
    def __init__(self, db: Database):
        self.db = db

    def overview(self, *, active_window_days: int = 7) -> dict:
        cutoff = (datetime.now(UTC) - timedelta(days=active_window_days)).isoformat()
        month_cutoff = (datetime.now(UTC) - timedelta(days=30)).isoformat()

        with self.db.connection() as con:
            rows = [dict(r) for r in con.execute(_USER_ROWS).fetchall()]
            dims = {r["user_id"]: dict(r) for r in con.execute(_AVG_DIMS).fetchall()}
            totals = dict(
                con.execute(
                    "SELECT"
                    " (SELECT COUNT(*) FROM users) AS users,"
                    " (SELECT COUNT(*) FROM sessions) AS sessions,"
                    " (SELECT COUNT(*) FROM utterances) AS utterances,"
                    " (SELECT COUNT(*) FROM assessments) AS assessments,"
                    " (SELECT COUNT(*) FROM users WHERE is_admin=1) AS admins,"
                    " (SELECT AVG(overall) FROM assessments) AS avg_overall"
                ).fetchone()
            )

        users = []
        for row in rows:
            per_user = dims.get(row["user_id"], {})
            # "Last active" is whichever came later: a practice session started or
            # an assessment landing. Sessions alone would call a learner inactive
            # while their turn is still being scored; assessments alone would miss
            # anyone whose scoring is deferred under guard pressure.
            last_active = max(
                [t for t in (row["last_session_at"], row["last_assessment_at"]) if t],
                default=None,
            )
            users.append(
                {
                    "user_id": row["user_id"],
                    "display_name": row["display_name"],
                    "created_at": row["created_at"],
                    "current_level": row["current_level"],
                    "streak_days": row["streak_days"],
                    "is_admin": bool(row["is_admin"]),
                    "has_password": bool(row["has_password"]),
                    "sessions": row["sessions"],
                    "utterances": row["utterances"],
                    "assessments": row["assessments"],
                    "last_active": last_active,
                    "latest_overall": _round(row["latest_overall"]),
                    "avg_overall": _round(row["avg_overall"]),
                    "avg_scores": {
                        d: _round(per_user.get(d))
                        for d in DIMENSIONS
                        if per_user.get(d) is not None
                    },
                }
            )

        return {
            "totals": {
                "users": totals["users"],
                "admins": totals["admins"],
                "sessions": totals["sessions"],
                "utterances": totals["utterances"],
                "assessments": totals["assessments"],
                "avg_overall": _round(totals["avg_overall"]),
                "active_7d": sum(
                    1 for u in users if u["last_active"] and u["last_active"] >= cutoff
                ),
                "active_30d": sum(
                    1 for u in users if u["last_active"] and u["last_active"] >= month_cutoff
                ),
                "never_practised": sum(1 for u in users if not u["last_active"]),
            },
            "users": users,
        }
