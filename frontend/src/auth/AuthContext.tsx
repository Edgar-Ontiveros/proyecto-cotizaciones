/** Sesión en memoria: el access token vive en lib/api (JAMÁS en
 * localStorage/sessionStorage); al recargar la página se recupera con la
 * cookie HttpOnly del refresh. */

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { api, configurarCallbacks, refrescarToken, setAccessToken } from "../lib/api";
import type { AccessTokenResponse, UsuarioMe } from "../lib/types";

interface AuthState {
  usuario: UsuarioMe | null;
  cargando: boolean;
  mustChangePassword: boolean;
  login: (email: string, password: string) => Promise<{ mustChangePassword: boolean }>;
  cambiarPassword: (actual: string, nueva: string) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [usuario, setUsuario] = useState<UsuarioMe | null>(null);
  const [cargando, setCargando] = useState(true);
  const [mustChangePassword, setMustChangePassword] = useState(false);

  const limpiarSesion = useCallback(() => {
    setAccessToken(null);
    setUsuario(null);
    setMustChangePassword(false);
  }, []);

  useEffect(() => {
    configurarCallbacks({
      sesionExpirada: () => {
        setUsuario(null);
        setMustChangePassword(false);
      },
      passwordChangeRequired: () => setMustChangePassword(true),
    });
  }, []);

  // Bootstrap: intenta recuperar la sesión con la cookie del refresh.
  useEffect(() => {
    void (async () => {
      try {
        if (await refrescarToken()) {
          const me = await api<UsuarioMe>("/auth/me");
          setUsuario(me);
          setMustChangePassword(me.must_change_password);
        }
      } catch {
        // Sin sesión previa: se queda en login.
      } finally {
        setCargando(false);
      }
    })();
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const r = await api<AccessTokenResponse>("/auth/login", {
      method: "POST",
      body: { email, password },
    });
    setAccessToken(r.access_token);
    setMustChangePassword(r.must_change_password);
    if (!r.must_change_password) {
      setUsuario(await api<UsuarioMe>("/auth/me"));
    }
    return { mustChangePassword: r.must_change_password };
  }, []);

  const cambiarPassword = useCallback(async (actual: string, nueva: string) => {
    const r = await api<AccessTokenResponse>("/auth/change-password", {
      method: "POST",
      body: { password_actual: actual, password_nueva: nueva },
    });
    setAccessToken(r.access_token);
    setMustChangePassword(false);
    setUsuario(await api<UsuarioMe>("/auth/me"));
  }, []);

  const logout = useCallback(async () => {
    try {
      await api<void>("/auth/logout", { method: "POST" });
    } finally {
      limpiarSesion();
    }
  }, [limpiarSesion]);

  const value = useMemo(
    () => ({ usuario, cargando, mustChangePassword, login, cambiarPassword, logout }),
    [usuario, cargando, mustChangePassword, login, cambiarPassword, logout],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth requiere AuthProvider");
  return ctx;
}

/** Ruta "home" de cada rol (admin y gerente → placeholder F8b). */
export function rutaPorRol(rol: UsuarioMe["rol"]): string {
  if (rol === "vendedor") return "/vendedor";
  if (rol === "comprador") return "/comprador";
  return "/admin";
}
