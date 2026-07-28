/** Lógica pura del CRM (F8d), sin React: testeable en crm.test.ts. */

import dayjs from "dayjs";

export type PresetFechas = "mes" | "30d" | "trimestre";

export interface FiltrosDashboard {
  preset: PresetFechas;
  sucursal_id?: number;
  comprador_id?: number;
  vendedor_id?: number;
}

/** Query para /metricas/* desde el estado del dashboard. `hoy` inyectable
 * para tests. Presets: mes en curso · últimos 30 días · trimestre actual. */
export function queryFiltrosDashboard(
  filtros: FiltrosDashboard,
  hoy: string = dayjs().format("YYYY-MM-DD"),
): Record<string, string | number | undefined> {
  const fin = dayjs(hoy);
  let inicio = fin.startOf("month");
  if (filtros.preset === "30d") inicio = fin.subtract(30, "day");
  if (filtros.preset === "trimestre") {
    const mesInicio = Math.floor(fin.month() / 3) * 3;
    inicio = fin.month(mesInicio).startOf("month");
  }
  return {
    desde: inicio.format("YYYY-MM-DD"),
    hasta: fin.format("YYYY-MM-DD"),
    sucursal_id: filtros.sucursal_id,
    comprador_id: filtros.comprador_id,
    vendedor_id: filtros.vendedor_id,
  };
}

export interface RequisitosBaja {
  requiereTitularidades: boolean;
  requiereSolicitudes: boolean;
}

/** Parsea el 409 `baja_requiere_reasignacion` a los campos que el modal debe
 * pedir. El backend lo dice en el detail: "(envía titularidades_a)" /
 * "(envía solicitudes_a)". */
export function parseBajaSegura(detail: string): RequisitosBaja {
  return {
    requiereTitularidades: detail.includes("titularidades_a"),
    requiereSolicitudes: detail.includes("solicitudes_a"),
  };
}

/** Espejo de usuarios/service.MATRIZ_GESTION del backend (F8c): qué roles
 * puede crear/editar cada gestor. El backend es la autoridad — esto solo
 * arma el formulario. */
export const ROLES_GESTIONABLES: Record<string, string[]> = {
  admin: [
    "vendedor",
    "comprador",
    "gerente_sucursal",
    "gerente_compras",
    "director_ventas",
    "admin",
  ],
  director_ventas: ["vendedor", "gerente_sucursal"],
  gerente_compras: ["comprador"],
  gerente_sucursal: ["vendedor"],
};

/** Roles que exigen sucursal en el alta/edición. */
export const ROLES_CON_SUCURSAL = ["vendedor", "gerente_sucursal"];

/** Etiquetas de UI de los roles (F8e): director_ventas se MUESTRA como
 * "Director Comercial" en todo el frontend; el enum del backend NO cambia. */
export const ETIQUETA_ROL: Record<string, string> = {
  vendedor: "Vendedor",
  comprador: "Comprador",
  gerente_sucursal: "Gerente de sucursal",
  gerente_compras: "Gerente de compras",
  director_ventas: "Director Comercial",
  admin: "Admin",
};

export function etiquetaRol(rol: string): string {
  return ETIQUETA_ROL[rol] ?? rol;
}

/** Mapa de ACCIONES del detalle CRM por rol (F9-prep, testeado): qué botones
 * ve cada perfil. El gating por ESTADO vive en la vista; la autoridad real
 * de permisos es el backend. */
export interface AccionesDetalleCrm {
  capturar: boolean;
  reasignarComprador: boolean;
  reasignarVendedor: boolean;
  corregirTC: boolean; // en CONFIRMADA (el comprador corrige el suyo en COTIZADA)
}

export function accionesDetalleCrm(rol: string): AccionesDetalleCrm {
  const esAdmin = rol === "admin";
  return {
    capturar: esAdmin || rol === "gerente_compras",
    reasignarComprador: esAdmin || rol === "gerente_compras",
    // F9-prep: el director TAMBIÉN reasigna vendedor individual (el backend
    // lo permite desde F5); el gerente, solo dentro de su sucursal.
    reasignarVendedor: esAdmin || rol === "gerente_sucursal" || rol === "director_ventas",
    corregirTC: esAdmin,
  };
}

/** Base de rutas de solicitudes según dónde está montada la vista: las vistas
 * de vendedor se REUSAN bajo /crm (F8d) y sus navegaciones internas deben
 * quedarse en su mundo. */
export function baseSolicitudes(pathname: string): "/crm" | "/comprador" | "/vendedor" {
  if (pathname.startsWith("/crm")) return "/crm";
  if (pathname.startsWith("/comprador")) return "/comprador";
  return "/vendedor";
}
