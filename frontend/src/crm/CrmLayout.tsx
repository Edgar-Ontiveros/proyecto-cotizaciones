/** Layout del CRM (F8d): header compartido + menú lateral armado DESDE el
 * mapa rol→secciones (crm/menu.ts). */

import { AppShell, Center, Loader, NavLink, Text } from "@mantine/core";
import { Suspense } from "react";
import { Outlet, useLocation, useNavigate } from "react-router";

import { useAuth } from "../auth/AuthContext";
import { HeaderContenido } from "../components/Layout";
import { esRolCrm, menuDe } from "./menu";

const TITULO_ROL: Record<string, string> = {
  admin: "Administración",
  director_ventas: "Dirección Comercial", // etiqueta de UI (F8e); el enum no cambia
  gerente_compras: "Gerencia de compras",
  gerente_sucursal: "Gerencia de sucursal",
};

export function CrmLayout() {
  const { usuario } = useAuth();
  const navigate = useNavigate();
  const { pathname } = useLocation();
  if (!usuario || !esRolCrm(usuario.rol)) return null; // el guard ya redirigió

  const items = menuDe(usuario.rol);
  const activo = (ruta: string) =>
    ruta === "/crm" ? pathname === "/crm" : pathname.startsWith(ruta);

  return (
    <AppShell header={{ height: 56 }} navbar={{ width: 220, breakpoint: "sm" }} padding="md">
      <AppShell.Header bg="herinox.6">
        <HeaderContenido />
      </AppShell.Header>
      <AppShell.Navbar p="xs">
        <Text size="xs" c="dimmed" fw={600} px="sm" py={4} tt="uppercase">
          {TITULO_ROL[usuario.rol]}
        </Text>
        {items.map((item) => (
          <NavLink
            key={item.seccion}
            label={item.titulo}
            active={activo(item.ruta)}
            onClick={() => navigate(item.ruta)}
          />
        ))}
      </AppShell.Navbar>
      <AppShell.Main bg="gray.0">
        {/* Las secciones del CRM son lazy (F9-prep): loader mientras cargan. */}
        <Suspense
          fallback={
            <Center mt={120}>
              <Loader />
            </Center>
          }
        >
          <Outlet />
        </Suspense>
      </AppShell.Main>
    </AppShell>
  );
}
