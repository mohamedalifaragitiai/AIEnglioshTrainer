"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { ThemeToggle } from "@/components/ThemeToggle";
import { api } from "@/lib/api";
import { useUser } from "@/app/user-context";

import { LEVEL_NAMES } from "@/lib/types";

export function Header() {
  const {
    users,
    currentUser,
    currentLevel,
    setCurrentUser,
    refresh,
    modelsLoaded,
    authRequired,
    signedInAs,
    isAdmin,
    signOut,
  } = useUser();
  const pathname = usePathname();
  const onAuthPage = pathname === "/login" || pathname === "/signup";
  const [version, setVersion] = useState<string | null>(null);
  // "Operator" rather than "admin": with auth off there is one user and nothing
  // to separate, so hiding the machine state would just remove a useful view.
  const operator = isAdmin || !authRequired;

  useEffect(() => {
    // Open endpoint, so this resolves on the login page too — "which build is
    // this?" is a question you ask before you can sign in.
    api
      .version()
      .then((v) => setVersion(v.version))
      .catch(() => setVersion(null));
  }, []);

  const newUser = async () => {
    const id = prompt("New learner id (slug, e.g. abu_ali):");
    if (!id) return;
    const name = prompt("Display name:", id) || id;
    try {
      await api.createUser(id.trim(), name.trim());
      setCurrentUser(id.trim());
      await refresh();
    } catch (e) {
      alert("Could not create user:\n" + (e as Error).message);
    }
  };

  const seed = async () => {
    if (!currentUser) return alert("Select a learner first.");
    try {
      await api.seedDemo(currentUser);
      await refresh();
      location.reload();
    } catch (e) {
      alert("Seed failed:\n" + (e as Error).message);
    }
  };

  const tab = (href: string, label: string) => (
    <Link
      href={href}
      className={`px-3 py-2 shrink-0 border-b-2 ${
        pathname === href ? "text-fg border-accent" : "text-muted border-transparent"
      }`}
    >
      {label}
    </Link>
  );

  // On the login/signup pages there is nothing to pick, seed or navigate to yet.
  if (onAuthPage) {
    return (
      <header className="border-b border-line bg-panel">
        <div className="mx-auto w-full max-w-[1680px] px-[clamp(14px,2.2vw,34px)] py-3">
          <div className="flex items-center justify-between">
            <h1 className="text-lg font-semibold flex items-center gap-2.5">
  <span className="brand-mark" aria-hidden="true">AI</span>
                <span className="brand-mark" aria-hidden="true">AI</span>
          AI English <span className="text-accent">Coach</span>
            </h1>
            <ThemeToggle />
          </div>
        </div>
      </header>
    );
  }

  return (
    <header className="border-b border-line bg-panel">
      <div className="mx-auto w-full max-w-[1680px] px-[clamp(14px,2.2vw,34px)] flex items-center gap-4 py-3 flex-wrap">
        <h1 className="text-lg font-semibold flex items-center gap-2.5">
          AI English <span className="text-accent">Coach</span>
        </h1>
        {isAdmin && version && <span className="pill bg-panel2 text-muted">v{version}</span>}
        <span className="pill bg-panel2 text-accent2">
          Level {currentLevel} · {LEVEL_NAMES[currentLevel]}
        </span>
        {/* Strictly admin: model status is never a learner's business,
            even on a single-user install. */}
        {isAdmin && (
          <span
            className={`pill ${
              modelsLoaded === null
                ? ""
                : modelsLoaded
                  ? "bg-good/15 text-good"
                  : "bg-bad/15 text-bad"
            }`}
          >
            models: {modelsLoaded === null ? "?" : modelsLoaded ? "loaded" : "off"}
          </span>
        )}
        <div className="flex-1" />
        <label className="text-muted text-sm hidden sm:block">Learner</label>
        <select
          className="btn max-w-[42vw] sm:max-w-none"
          value={currentUser ?? ""}
          onChange={(e) => setCurrentUser(e.target.value)}
        >
          {users.length === 0 && <option value="">(no learners)</option>}
          {users.map((u) => (
            <option key={u.user_id} value={u.user_id}>
              {u.display_name} ({u.user_id})
            </option>
          ))}
        </select>
        {/* With auth on, profiles come from signup — POST /users is refused. */}
        {!authRequired && (
          <button className="btn" onClick={newUser}>
            + New
          </button>
        )}
        {/* Demo data writes fabricated history into a learner's real progress —
            a setup affordance, never something they should be able to press. */}
        {operator && (
          <button className="btn" onClick={seed}>
            Load demo data
          </button>
        )}
        <Link href="/settings" className="btn" title="Account settings" aria-label="Account settings">
          ⚙️
        </Link>
        <ThemeToggle />
        {signedInAs && (
          <button className="btn" onClick={signOut} title={`Signed in as ${signedInAs}`}>
            Sign out
          </button>
        )}
      </div>
      <nav className="mx-auto w-full max-w-[1680px] px-[clamp(14px,2.2vw,34px)] flex gap-1 overflow-x-auto whitespace-nowrap [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
        {tab("/", "Dashboard")}
        {tab("/practice", "Practice")}
        {tab("/reading", "Reading")}
        {tab("/conversations", "Conversations")}
        {tab("/report", "Report")}
        {/* Monitor is machine state — VRAM, the degradation ladder, model
            status. That belongs to whoever runs the box, not to someone
            practising English. With auth off there is only one user, so it
            stays visible. */}
        {operator && tab("/monitor", "Monitor")}
        {/* Shown for admins only — /admin/overview is what actually enforces it. */}
        {isAdmin && tab("/admin", "Admin")}
      </nav>
    </header>
  );
}
