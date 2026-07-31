"""The project's version — one source of truth.

``pyproject.toml`` carries the same string because packaging tools read it from
there, and a test asserts the two agree so they cannot drift silently.

Semantics (SemVer, adapted to an application rather than a library):

* **major** — a change that invalidates an existing install: a migration that
  cannot be applied forward, or a config/API break that needs operator action.
* **minor** — new capability that an existing install can take without ceremony
  (auth, the admin role, a new endpoint).
* **patch** — fixes and copy changes only.

Bump it in this file, add the entry to ``CHANGELOG.md``, then tag ``vX.Y.Z``.
"""

from __future__ import annotations

import subprocess
from functools import lru_cache
from pathlib import Path

VERSION = "0.2.0"

_REPO_ROOT = Path(__file__).resolve().parent.parent


@lru_cache(maxsize=1)
def git_sha() -> str | None:
    """Short commit of the working tree, or None outside a git checkout.

    Best-effort by design: a deployed copy may have no ``.git`` and must still
    report its version rather than fail. Read from the filesystem rather than by
    shelling out where possible — ``git`` is not guaranteed on a host that only
    ever runs the app.
    """
    head = _REPO_ROOT / ".git" / "HEAD"
    try:
        ref = head.read_text(encoding="utf-8").strip()
        if ref.startswith("ref: "):
            target = _REPO_ROOT / ".git" / ref[5:]
            if target.exists():
                return target.read_text(encoding="utf-8").strip()[:12]
            # Packed refs: fall back to git itself.
            out = subprocess.run(
                ["git", "-C", str(_REPO_ROOT), "rev-parse", "--short=12", "HEAD"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return out.stdout.strip() or None
        return ref[:12] or None  # detached HEAD holds the sha directly
    except (OSError, subprocess.SubprocessError):
        return None


def version_info() -> dict[str, str | None]:
    return {"version": VERSION, "git_sha": git_sha()}
