"use client";

import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { usePathname, useRouter } from "next/navigation";
import { api, AuthError, setToken } from "@/lib/api";
import type { User } from "@/lib/types";

interface UserCtx {
  users: User[];
  currentUser: string | null;
  currentLevel: number;
  setCurrentUser: (id: string) => void;
  refresh: () => Promise<void>;
  modelsLoaded: boolean | null;
  /** True once the server says a session is required to read anything. */
  authRequired: boolean;
  /** Who is signed in, when auth is on. Null while signed out or auth is off. */
  signedInAs: string | null;
  minPasswordLength: number;
  /** Called by the auth form after a successful signup/login. */
  adoptSession: (userId: string) => Promise<void>;
  signOut: () => Promise<void>;
}

const Ctx = createContext<UserCtx | null>(null);

const AUTH_PAGES = ["/login", "/signup"];

export function UserProvider({ children }: { children: ReactNode }) {
  const [users, setUsers] = useState<User[]>([]);
  const [currentUser, setCurrentUserState] = useState<string | null>(null);
  const [modelsLoaded, setModelsLoaded] = useState<boolean | null>(null);
  const [authRequired, setAuthRequired] = useState(false);
  const [signedInAs, setSignedInAs] = useState<string | null>(null);
  const [minPasswordLength, setMinPasswordLength] = useState(8);
  const router = useRouter();
  const pathname = usePathname();
  const onAuthPage = AUTH_PAGES.includes(pathname);

  const setCurrentUser = (id: string) => {
    setCurrentUserState(id);
    try {
      localStorage.setItem("coach.user", id);
    } catch {}
  };

  const refresh = async () => {
    const list = await api.listUsers();
    setUsers(list);
    const saved = (() => {
      try {
        return localStorage.getItem("coach.user");
      } catch {
        return null;
      }
    })();
    const pick =
      (saved && list.find((u) => u.user_id === saved)?.user_id) || list[0]?.user_id || null;
    setCurrentUserState(pick);
  };

  const adoptSession = async (userId: string) => {
    setSignedInAs(userId);
    setCurrentUser(userId);
    await refresh().catch(() => {});
  };

  const signOut = async () => {
    await api.logout().catch(() => {});
    setToken(null);
    setSignedInAs(null);
    setUsers([]);
    setCurrentUserState(null);
    router.push("/login");
  };

  useEffect(() => {
    let cancelled = false;

    (async () => {
      // One call decides everything: whether this install enforces auth, and
      // whether the token we are holding is still good. Doing it before the
      // data fetches keeps a signed-out visitor from flashing an error page on
      // the way to /login.
      const status = await api.authStatus().catch(() => null);
      if (cancelled) return;
      if (status) {
        setAuthRequired(status.auth_required);
        setSignedInAs(status.authenticated ? status.user_id : null);
        setMinPasswordLength(status.min_password_length);
        if (status.auth_required && !status.authenticated) {
          if (!onAuthPage) router.replace("/login");
          return;
        }
      }

      await refresh().catch((e) => {
        // A token that expired between page loads: bounce to the login page
        // rather than leaving an empty dashboard with no explanation.
        if (e instanceof AuthError && !onAuthPage) router.replace("/login");
      });
      api
        .models()
        .then((m) => setModelsLoaded(m.some((x) => x.status === "loaded")))
        .catch(() => setModelsLoaded(null));
    })();

    return () => {
      cancelled = true;
    };
    // Re-runs on navigation so signing in/out re-evaluates the gate.
  }, [pathname]); // eslint-disable-line react-hooks/exhaustive-deps

  const currentLevel = users.find((u) => u.user_id === currentUser)?.current_level ?? 0;

  return (
    <Ctx.Provider
      value={{
        users,
        currentUser,
        currentLevel,
        setCurrentUser,
        refresh,
        modelsLoaded,
        authRequired,
        signedInAs,
        minPasswordLength,
        adoptSession,
        signOut,
      }}
    >
      {children}
    </Ctx.Provider>
  );
}

export function useUser(): UserCtx {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useUser must be used within UserProvider");
  return ctx;
}
