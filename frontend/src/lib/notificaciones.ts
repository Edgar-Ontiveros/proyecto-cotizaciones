/** Notificaciones (F7 · F16b): helpers puros de la campana. */

import type { NotificacionOut, Rol } from "./types";

/** Ancla de la sección "Pedido en SAP" del detalle (F16b): las notificaciones
 * de OC navegan directo a ella. */
export const ANCLA_PEDIDO_SAP = "pedido-sap";

/** F16b: tipos generados por el sondeo de OC de SAP (oc_recibida,
 * oc_parcialmente_recibida, oc_facturada, oc_cancelada,
 * oc_cerrada_sin_recibir, oc_vencida). Se pintan como los demás; solo el
 * destino del clic cambia (sección Pedido en SAP). */
export function esNotificacionOC(tipo: string): boolean {
  return tipo.startsWith("oc_");
}

/** Ruta del detalle de la solicitud para el rol (comprador y vendedor tienen
 * su vista; los roles CRM, F8d, ven el detalle bajo /crm). null si la
 * notificación no lleva solicitud (p. ej. seguridad). */
export function rutaNotificacion(rol: Rol, n: Pick<NotificacionOut, "solicitud_id" | "tipo">): string | null {
  if (n.solicitud_id === null) return null;
  const base = rol === "comprador" ? "/comprador" : rol === "vendedor" ? "/vendedor" : "/crm";
  const ruta = `${base}/solicitudes/${n.solicitud_id}`;
  return esNotificacionOC(n.tipo) ? `${ruta}#${ANCLA_PEDIDO_SAP}` : ruta;
}
