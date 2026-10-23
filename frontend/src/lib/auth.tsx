"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import {
  api,
  refreshSession,
  setAccessToken,
  setSessionExpiredHandler,
  type Schemas,
} from "@/lib/api/client";

export type User = Schemas["UserRead"];
type Status = "loading" | "authenticated" | "anonymous";

interface AuthContextValue {
  status: Status;
  user: User | null;
  login: (email: string, password: string) => Promise<void>;
  register: (body: Schemas["RegisterRequest"]) => Promise<void>;
  logout: () => Promise<void>;
  setUser: (user: User) => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [status, setStatus] = useState<Status>("loading");
  const [user, setUserState] = useState<User | null>(null);

  const clear = useCallback(() => {
    setAccessToken(null);
    setUserState(null);
    setStatus("anonymous");
  }, []);

  useEffect(() => {
    setSessionExpiredHandler(clear);
    let cancelled = false;
    (async () => {
      const ok = await refreshSession();
      if (!ok) {
        if (!cancelled) clear();
        return;
      }
      try {
        const me = await api<User>("/me");
        if (!cancelled) {
          setUserState(me);
          setStatus("authenticated");
        }
      } catch {
        if (!cancelled) clear();
      }
    })();
    return () => {
      cancelled = true;
      setSessionExpiredHandler(null);
    };
  }, [clear]);

  const login = useCallback(async (email: string, password: string) => {
    const tokens = await api<Schemas["TokenResponse"]>("/auth/login", {
      method: "POST",
      body: { email, password },
    });
    setAccessToken(tokens.access_token);
    const me = await api<User>("/me");
    setUserState(me);
    setStatus("authenticated");
  }, []);

  const register = useCallback(
    async (body: Schemas["RegisterRequest"]) => {
      await api<User>("/auth/register", { method: "POST", body });
      await login(body.email, body.password);
    },
    [login],
  );

  const logout = useCallback(async () => {
    try {
      await api<null>("/auth/logout", { method: "POST" });
    } finally {
      clear();
    }
  }, [clear]);

  const value = useMemo<AuthContextValue>(
    () => ({ status, user, login, register, logout, setUser: setUserState }),
    [status, user, login, register, logout],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}

/** The signed-in user; only call inside the authenticated app shell. */
export function useUser(): User {
  const { user } = useAuth();
  if (!user) throw new Error("useUser called without an authenticated user");
  return user;
}
