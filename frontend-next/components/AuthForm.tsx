"use client";

import { useRouter } from "next/navigation";
import Link from "next/link";
import { useState } from "react";
import { api, setToken } from "@/lib/api";
import { useUser } from "@/app/user-context";

/**
 * The shared body of /login and /signup — the two differ only in which endpoint
 * they call and one extra field, so keeping them one component keeps their
 * error handling, redirect, and styling from drifting apart.
 */
export function AuthForm({ mode }: { mode: "login" | "signup" }) {
  const isSignup = mode === "signup";
  const router = useRouter();
  const { adoptSession, minPasswordLength } = useUser();

  const [userId, setUserId] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const id = userId.trim();
      const session = isSignup
        ? await api.signup(id, displayName.trim() || id, password)
        : await api.login(id, password);
      setToken(session.token);
      await adoptSession(session.user.user_id);
      router.push("/");
    } catch (err) {
      setError(readableError(err as Error, isSignup));
      setBusy(false);
    }
  };

  return (
    <div className="max-w-sm mx-auto mt-16">
      <h2 className="text-xl font-semibold mb-1">
        {isSignup ? "Create your account" : "Sign in"}
      </h2>
      <p className="text-muted text-sm mb-6">
        {isSignup
          ? "Your profile, history and scores stay on this machine."
          : "Welcome back."}
      </p>

      <form onSubmit={submit} className="flex flex-col gap-3">
        <label className="text-sm text-muted" htmlFor="user_id">
          Learner id
        </label>
        <input
          id="user_id"
          className="btn text-left"
          value={userId}
          onChange={(e) => setUserId(e.target.value)}
          placeholder="abu_ali"
          autoComplete="username"
          autoFocus
          required
        />

        {isSignup && (
          <>
            <label className="text-sm text-muted" htmlFor="display_name">
              Display name
            </label>
            <input
              id="display_name"
              className="btn text-left"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              placeholder="Abu Ali"
            />
          </>
        )}

        <label className="text-sm text-muted" htmlFor="password">
          Password
        </label>
        <input
          id="password"
          type="password"
          className="btn text-left"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          autoComplete={isSignup ? "new-password" : "current-password"}
          minLength={isSignup ? minPasswordLength : undefined}
          required
        />
        {isSignup && (
          <span className="text-xs text-muted">
            At least {minPasswordLength} characters.
          </span>
        )}

        {error && (
          <div className="pill bg-red-950 text-red-300 whitespace-pre-wrap">{error}</div>
        )}

        <button className="btn mt-2" disabled={busy} type="submit">
          {busy ? "Working…" : isSignup ? "Create account" : "Sign in"}
        </button>
      </form>

      <p className="text-sm text-muted mt-6">
        {isSignup ? (
          <>
            Already have an account? <Link className="text-accent" href="/login">Sign in</Link>
          </>
        ) : (
          <>
            No account yet? <Link className="text-accent" href="/signup">Create one</Link>
          </>
        )}
      </p>
    </div>
  );
}

/** Turn `409 {"detail":"..."}` into something a human can act on. */
function readableError(err: Error, isSignup: boolean): string {
  const raw = err.message || "";
  const detail = (() => {
    const brace = raw.indexOf("{");
    if (brace < 0) return raw;
    try {
      return JSON.parse(raw.slice(brace)).detail ?? raw;
    } catch {
      return raw;
    }
  })();
  if (/failed to fetch|networkerror/i.test(raw)) {
    return "Cannot reach the API. Is the app running on port 8000?";
  }
  if (isSignup && raw.startsWith("409")) {
    return `${detail}\nSign in instead.`;
  }
  return String(detail);
}
