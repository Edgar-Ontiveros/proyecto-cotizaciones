/** F16a: lógica pura de Pedidos en SAP (sin React, testeable). */

import type { EstatusOC, Rol } from "./types";

/** Roles que administran OC (los mismos a los que el backend manda OCComprasOut). */
export const ROLES_OC = ["comprador", "gerente_compras", "admin"];

export function administraOC(rol: Rol | string): boolean {
  return ROLES_OC.includes(rol);
}

export const ETIQUETA_ESTATUS: Record<EstatusOC, string> = {
  ABIERTA: "Abierta",
  PARCIALMENTE_RECIBIDA: "Parcialmente recibida",
  RECIBIDA: "Recibida",
  FACTURADA: "Facturada",
  CERRADA_SIN_RECIBIR: "Cerrada sin recibir",
  CANCELADA: "Cancelada",
};

/** Color del badge por estatus derivado (precedencia de F16a §2). */
export function colorEstatus(estatus: EstatusOC): string {
  switch (estatus) {
    case "FACTURADA":
      return "green";
    case "RECIBIDA":
      return "teal";
    case "PARCIALMENTE_RECIBIDA":
      return "yellow";
    case "ABIERTA":
      return "blue";
    case "CERRADA_SIN_RECIBIR":
      return "gray";
    case "CANCELADA":
      return "red";
  }
}

export const ESTATUS_OPCIONES: { value: EstatusOC; label: string }[] = (
  Object.keys(ETIQUETA_ESTATUS) as EstatusOC[]
).map((e) => ({ value: e, label: ETIQUETA_ESTATUS[e] }));

/** "Dónde": OC en X · entró en Y (o solo lo que haya). */
export function dondeTexto(oc: { donde_oc: string | null; donde_entrada?: string | null }): string {
  const partes: string[] = [];
  if (oc.donde_oc) partes.push(`OC: ${oc.donde_oc}`);
  if (oc.donde_entrada) partes.push(`entró en: ${oc.donde_entrada}`);
  return partes.join(" · ") || "—";
}

/** F16a.1: la OC existe en SAP solo como BORRADOR (ODRF); el backend responde
 * 422 con uno de estos códigos y un mensaje accionable. No es error del
 * usuario: se muestra en ámbar con "Volver a buscar". Nunca se vincula. */
export const CODIGOS_OC_BORRADOR = [
  "oc_aprobada_sin_anadir",
  "oc_pendiente_autorizacion",
  "oc_rechazada",
  "oc_borrador_convertido",
] as const;

export function esAvisoBorradorOC(code: string): boolean {
  return (CODIGOS_OC_BORRADOR as readonly string[]).includes(code);
}

export interface FiltrosPedidos {
  estatus?: EstatusOC | null;
  soloVencidas: boolean;
  sucursalId?: number | null;
  pagina: number;
  porPagina: number;
}

/** Params de GET /pedidos: solo viaja lo elegido; `vencidas` solo en true. */
export function paramsPedidos(
  f: FiltrosPedidos,
): Record<string, string | number | boolean | undefined> {
  return {
    estatus: f.estatus ?? undefined,
    vencidas: f.soloVencidas ? true : undefined,
    sucursal_id: f.sucursalId ?? undefined,
    limit: f.porPagina,
    offset: (f.pagina - 1) * f.porPagina,
  };
}

/** Valida y normaliza la captura del modal: número entero > 0 y serie SAP. */
export function validarBusquedaOC(
  docNum: string,
  sucursalSap: string,
): { doc_num: number; sucursal_sap: string } | { error: string } {
  const numero = Number(docNum.trim());
  if (!Number.isInteger(numero) || numero <= 0) return { error: "Captura el número de OC (entero)" };
  const serie = sucursalSap.trim().replace(/\.$/, "").toUpperCase();
  if (!serie) return { error: "Indica la sucursal SAP (serie: CH, CN, LE…)" };
  return { doc_num: numero, sucursal_sap: serie };
}
