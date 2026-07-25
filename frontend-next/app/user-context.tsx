"use client";

import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { api } from "@/lib/api";
import type { User } from "@/lib/types";

interface UserCtx {
  users: User[];
  currentUser: string | null;
  setCurrentUser: (id: string) => void;
  refresh: () => Promise<void>;
  modelsLoaded: boolean | null;
}

const Ctx = createContext<UserCtx | null>(null);

export function UserProvider({ children }: { children: ReactNode }) {
  const [users, setUsers] = useState<User[]>([]);
  const [currentUser, setCurrentUserState] = useState<string | null>(null);
  const [modelsLoaded, setModelsLoaded] = useState<boolean | null>(null);

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

  useEffect(() => {
    refresh().catch(() => {});
    api
      .models()
      .then((m) => setModelsLoaded(m.some((x) => x.status === "loaded")))
      .catch(() => setModelsLoaded(null));
  }, []);

  return (
    <Ctx.Provider value={{ users, currentUser, setCurrentUser, refresh, modelsLoaded }}>
      {children}
    </Ctx.Provider>
  );
}

export function useUser(): UserCtx {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useUser must be used within UserProvider");
  return ctx;
}
