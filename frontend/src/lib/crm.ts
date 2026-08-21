/** Lógica pura del CRM (F8d), sin React: testeable en crm.test.ts. */

import dayjs from "dayjs";

import type { Estado, GrupoOut } from "./types";

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
  // F12 p.4: eliminación DEFINITIVA — exclusiva del admin maestro; ningún
  // otro rol renderiza siquiera el botón (y el backend responde 404).
  eliminar: boolean;
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
    eliminar: esAdmin,
  };
}

/** F12 p.4: el botón rojo final del modal de eliminación solo se habilita con
 * el FOLIO tecleado EXACTO (o el #id si aún no hay folio) y un motivo con
 * sustancia (mínimo 10 caracteres, igual que el backend). */
export function habilitaEliminar(
  folioTecleado: string,
  motivo: string,
  solicitud: { folio: string | null; id: number },
): boolean {
  const objetivo = solicitud.folio ?? `#${solicitud.id}`;
  return folioTecleado.trim() === objetivo && motivo.trim().length >= 10;
}

/** Base de rutas de solicitudes según dónde está montada la vista: las vistas
 * de vendedor se REUSAN bajo /crm (F8d) y sus navegaciones internas deben
 * quedarse en su mundo. */
export function baseSolicitudes(pathname: string): "/crm" | "/comprador" | "/vendedor" {
  if (pathname.startsWith("/crm")) return "/crm";
  if (pathname.startsWith("/comprador")) return "/comprador";
  return "/vendedor";
}

/** F10.2 p.3b: proveedores de la opción GANADORA — lista única, en orden de
 * aparición, omitiendo renglones sin dato. Para el vendedor la clave no viene
 * en su JSON y la lista queda vacía (su regla de siempre). */
export function proveedoresGanadora(solicitud: {
  opcion_seleccionada_id: number | null;
  opciones: { id: number; renglones: { proveedor?: string | null }[] }[];
}): string[] {
  const ganadora = solicitud.opciones.find((o) => o.id === solicitud.opcion_seleccionada_id);
  if (!ganadora) return [];
  const unicos: string[] = [];
  for (const r of ganadora.renglones) {
    if (r.proveedor && !unicos.includes(r.proveedor)) unicos.push(r.proveedor);
  }
  return unicos;
}

/** F10.2 p.4: params de las pestañas paginadas del panel del comprador —
 * dato puro testeado. Confirmadas ordena por fecha de confirmación (backend
 * orden=confirmado_en); Cotizadas acepta el filtro de cambio pendiente. */
export function paramsPestanaComprador(
  tab: "cotizadas" | "confirmadas" | "todas",
  soloCambios = false,
): { estado?: string; cambio_pendiente?: boolean; orden?: string } {
  if (tab === "cotizadas") {
    return { estado: "COTIZADA", ...(soloCambios ? { cambio_pendiente: true } : {}) };
  }
  if (tab === "confirmadas") return { estado: "CONFIRMADA", orden: "confirmado_en" };
  return {};
}

// ------------------------------- F14 p.3: orden de las tablas comparativas

/** Fila de comparativas con los campos ordenables DERIVADOS: el dinero como
 * número (null = vacío "—") y las rojas del V/A/R. */
export interface FilaComparativa extends GrupoOut {
  confirmado_mxn: number | null;
  rojas: number;
}

export function aFilaComparativa(g: GrupoOut): FilaComparativa {
  // Mismo criterio que la celda: sin serie MXN o en cero → vacío ("—").
  const mxn = g.dinero_confirmado?.["MXN"];
  return {
    ...g,
    confirmado_mxn: mxn !== undefined && Number(mxn) !== 0 ? Number(mxn) : null,
    rojas: g.distribucion_bandas["LENTA"] ?? 0,
  };
}

/** Orden de comparativas (F14 p.3): NUMÉRICO para números (569,939.56 sobre
 * 78,928.45), los vacíos (null/undefined) SIEMPRE al final en ambas
 * direcciones, desempate estable por nombre. */
export function ordenarComparativa<T extends { nombre: string }>(
  filas: T[],
  accessor: string,
  direction: "asc" | "desc",
): T[] {
  const valorDe = (f: T): unknown => (f as Record<string, unknown>)[accessor];
  const comparar = (a: T, b: T): number => {
    const va = valorDe(a);
    const vb = valorDe(b);
    const vaVacio = va === null || va === undefined;
    const vbVacio = vb === null || vb === undefined;
    if (vaVacio && vbVacio) return a.nombre.localeCompare(b.nombre);
    if (vaVacio) return 1; // vacíos al final, SIN importar la dirección
    if (vbVacio) return -1;
    let orden: number;
    if (typeof va === "number" && typeof vb === "number") orden = va - vb;
    else orden = String(va).localeCompare(String(vb));
    if (direction === "desc") orden = -orden;
    return orden !== 0 ? orden : a.nombre.localeCompare(b.nombre);
  };
  return [...filas].sort(comparar);
}

// ----------------------------------- F14 p.2: impresión por estatus vigente

export type DocumentoImpresion = "COTIZACION" | "PEDIDO_CONFIRMADO";

/** El sistema elige el documento por el estatus, sin que el usuario escoja:
 * COTIZADA → Cotización; CONFIRMADA → Pedido confirmado; antes → null (el
 * botón vive deshabilitado con tooltip). */
export function documentoPorEstado(estado: Estado): DocumentoImpresion | null {
  if (estado === "COTIZADA") return "COTIZACION";
  if (estado === "CONFIRMADA") return "PEDIDO_CONFIRMADO";
  return null;
}
