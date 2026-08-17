/** Mapa rol→secciones del CRM (F8d): el menú lateral y las rutas se arman
 * DESDE este dato (testeado en crm.test.ts). El frontend solo esconde
 * pantallas — la autoridad real de permisos es el backend. */

import type { Rol } from "../lib/types";

export type SeccionCrm =
  | "dashboard"
  | "comparativas"
  | "solicitudes"
  | "usuarios"
  | "sucursales"
  | "territorios"
  | "reasignaciones"
  | "catalogos"
  | "eliminaciones";

export type RolCrm = Extract<
  Rol,
  "admin" | "director_ventas" | "gerente_compras" | "gerente_sucursal"
>;

export const ROLES_CRM: RolCrm[] = [
  "admin",
  "director_ventas",
  "gerente_compras",
  "gerente_sucursal",
];

export interface ItemMenuCrm {
  seccion: SeccionCrm;
  titulo: string;
  ruta: string;
}

/** Orden del menú lateral; la ruta es absoluta bajo /crm. */
export const MENU_CRM: ItemMenuCrm[] = [
  { seccion: "dashboard", titulo: "Dashboard", ruta: "/crm" },
  { seccion: "comparativas", titulo: "Comparativas", ruta: "/crm/comparativas" },
  { seccion: "solicitudes", titulo: "Solicitudes", ruta: "/crm/solicitudes" },
  { seccion: "usuarios", titulo: "Usuarios", ruta: "/crm/usuarios" },
  { seccion: "sucursales", titulo: "Sucursales", ruta: "/crm/sucursales" },
  { seccion: "territorios", titulo: "Territorios", ruta: "/crm/territorios" },
  { seccion: "reasignaciones", titulo: "Reasignaciones", ruta: "/crm/reasignaciones" },
  { seccion: "catalogos", titulo: "Catálogos", ruta: "/crm/catalogos" },
  // F12 p.4: bitácora de eliminaciones — solo admin.
  { seccion: "eliminaciones", titulo: "Eliminaciones", ruta: "/crm/eliminaciones" },
];

/** Qué ve cada rol (especificación §2):
 * - admin: todo.
 * - director_ventas: ventas global — nada de compras (sin territorios;
 *   sus comparativas excluyen por-comprador y no-encontrados).
 * - gerente_compras: compras global — nada de ventas-personal (sin
 *   por-vendedor); administra compradores, territorios y masivas de comprador.
 * - gerente_sucursal: su mini-mundo — dashboard con sucursal fija, SUS
 *   vendedores y reasignaciones entre ellos. */
export const SECCIONES_POR_ROL: Record<RolCrm, SeccionCrm[]> = {
  admin: [
    "dashboard",
    "comparativas",
    "solicitudes",
    "usuarios",
    "sucursales",
    "territorios",
    "reasignaciones",
    "catalogos",
    "eliminaciones",
  ],
  director_ventas: ["dashboard", "comparativas", "solicitudes", "usuarios", "reasignaciones"],
  gerente_compras: [
    "dashboard",
    "comparativas",
    "solicitudes",
    "usuarios",
    "territorios",
    "reasignaciones",
  ],
  gerente_sucursal: ["dashboard", "comparativas", "solicitudes", "usuarios", "reasignaciones"],
};

/** Tabs de comparativas visibles por rol (§2 y gates del backend). */
export type TabComparativa =
  | "por-sucursal"
  | "por-vendedor"
  | "por-cliente"
  | "por-comprador"
  | "materiales"
  | "no-encontrados";

export const COMPARATIVAS_POR_ROL: Record<RolCrm, TabComparativa[]> = {
  admin: [
    "por-sucursal",
    "por-vendedor",
    "por-cliente",
    "por-comprador",
    "materiales",
    "no-encontrados",
  ],
  director_ventas: ["por-sucursal", "por-vendedor", "por-cliente", "materiales"],
  gerente_compras: ["por-sucursal", "por-cliente", "por-comprador", "materiales", "no-encontrados"],
  gerente_sucursal: ["por-vendedor", "por-cliente"],
};

export function esRolCrm(rol: Rol): rol is RolCrm {
  return (ROLES_CRM as Rol[]).includes(rol);
}

export function menuDe(rol: RolCrm): ItemMenuCrm[] {
  const visibles = SECCIONES_POR_ROL[rol];
  return MENU_CRM.filter((item) => visibles.includes(item.seccion));
}
