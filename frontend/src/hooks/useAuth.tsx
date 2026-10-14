import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { api, tokenStore } from "@/services/api";
import type { User } from "@/types";

interface AuthState {
  user: User | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<User>;
  register: (name: string, email: string, password: string) => Promise<User>;
  logout: () => void;
  setUser: (u: User) => void;
}

const Ctx = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(Boolean(tokenStore.get()));

  useEffect(() => {
    if (!tokenStore.get()) return;
    api.me().then(setUser).catch(() => tokenStore.clear()).finally(() => setLoading(false));
  }, []);

  const logout = useCallback(() => { tokenStore.clear(); setUser(null); }, []);

  useEffect(() => {
    window.addEventListener("nova:unauthorized", logout);
    return () => window.removeEventListener("nova:unauthorized", logout);
  }, [logout]);

  const value = useMemo<AuthState>(() => ({
    user, loading, logout, setUser,
    login: async (email, password) => {
      const r = await api.login({ email, password });
      tokenStore.set(r.access_token); setUser(r.user); return r.user;
    },
    register: async (name, email, password) => {
      const r = await api.register({ name, email, password });
      tokenStore.set(r.access_token); setUser(r.user); return r.user;
    },
  }), [user, loading, logout]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthState {
  const v = useContext(Ctx);
  if (!v) throw new Error("useAuth must be used inside <AuthProvider>");
  return v;
}
