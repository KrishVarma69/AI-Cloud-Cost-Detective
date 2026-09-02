import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { api, clearToken, getToken, setToken } from "./api";

type AuthState = {
  token: string | null;
  email: string | null;
  isAuthed: boolean;
  signup: (email: string, password: string) => Promise<void>;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
};

const AuthContext = createContext<AuthState | undefined>(undefined);

type AuthResponse = { token: string; email: string };

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setTok] = useState<string | null>(() => getToken());
  const [email, setEmail] = useState<string | null>(
    () => localStorage.getItem("accd_email"),
  );

  const persist = useCallback((res: AuthResponse) => {
    setToken(res.token);
    localStorage.setItem("accd_email", res.email);
    setTok(res.token);
    setEmail(res.email);
  }, []);

  const signup = useCallback(
    async (e: string, p: string) => {
      const res = await api<AuthResponse>("/api/auth/signup", {
        method: "POST",
        body: { email: e, password: p },
        auth: false,
      });
      persist(res);
    },
    [persist],
  );

  const login = useCallback(
    async (e: string, p: string) => {
      const res = await api<AuthResponse>("/api/auth/login", {
        method: "POST",
        body: { email: e, password: p },
        auth: false,
      });
      persist(res);
    },
    [persist],
  );

  const logout = useCallback(() => {
    clearToken();
    localStorage.removeItem("accd_email");
    setTok(null);
    setEmail(null);
  }, []);

  const value = useMemo<AuthState>(
    () => ({ token, email, isAuthed: !!token, signup, login, logout }),
    [token, email, signup, login, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
