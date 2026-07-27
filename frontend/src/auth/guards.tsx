import { Center, Loader } from "@mantine/core";
import { Navigate, Outlet } from "react-router";

import type { Rol } from "../lib/types";
import { rutaPorRol, useAuth } from "./AuthContext";

/** Guard por rol: sin sesión → login; con cambio de contraseña pendiente →
 * pantalla de cambio; rol distinto → su home (el frontend solo esconde
 * pantallas — la autoridad real es el backend). */
export function RequireRol({ roles }: { roles: Rol[] }) {
  const { usuario, cargando, mustChangePassword } = useAuth();
  if (cargando) {
    return (
      <Center h="100vh">
        <Loader />
      </Center>
    );
  }
  if (mustChangePassword) return <Navigate to="/cambiar-password" replace />;
  if (!usuario) return <Navigate to="/login" replace />;
  if (!roles.includes(usuario.rol)) return <Navigate to={rutaPorRol(usuario.rol)} replace />;
  return <Outlet />;
}
