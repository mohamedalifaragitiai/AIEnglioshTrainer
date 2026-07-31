"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
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
    signOut,
  } = useUser();
  const pathname = usePathname();
  const onAuthPage = pathname === "/login" || pathname === "/signup";
  const [version, setVersion] = useState<string | null>(null);

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
      className={`px-3 py-1.5 border-b-2 ${
        pathname === href ? "text-white border-accent" : "text-muted border-transparent"
      }`}
    >
      {label}
    </Link>
  );

  // On the login/signup pages there is nothing to pick, seed or navigate to yet.
  if (onAuthPage) {
    return (
      <header className="border-b border-line bg-panel">
        <div className="px-6 py-3">
          <h1 className="text-lg font-semibold">
            AI English <span className="text-accent">Coach</span>
            {version && <span className="pill bg-panel2 ml-3">v{version}</span>}
          </h1>
        </div>
      </header>
    );
  }

  return (
    <header className="border-b border-line bg-panel">
      <div className="flex items-center gap-4 px-6 py-3 flex-wrap">
        <h1 className="text-lg font-semibold">
          AI English <span className="text-accent">Coach</span>
        </h1>
        {version && <span className="pill bg-panel2 text-muted">v{version}</span>}
        <span className="pill bg-panel2 text-accent2">
          Level {currentLevel} · {LEVEL_NAMES[currentLevel]}
        </span>
        <span
          className={`pill ${
            modelsLoaded === null
              ? ""
              : modelsLoaded
                ? "bg-emerald-900 text-emerald-300"
                : "bg-red-950 text-red-300"
          }`}
        >
          models: {modelsLoaded === null ? "?" : modelsLoaded ? "loaded" : "off"}
        </span>
        <div className="flex-1" />
        <label className="text-muted text-sm">Learner</label>
        <select
          className="btn"
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
        <button className="btn" onClick={seed}>
          Load demo data
        </button>
        {signedInAs && (
          <button className="btn" onClick={signOut} title={`Signed in as ${signedInAs}`}>
            Sign out
          </button>
        )}
      </div>
      <nav className="flex gap-1 px-6">
        {tab("/", "Dashboard")}
        {tab("/practice", "Practice")}
        {tab("/report", "Report")}
        {tab("/monitor", "Monitor")}
      </nav>
    </header>
  );
}
