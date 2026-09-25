/** F16b — notificaciones del sondeo de OC: la campana las pinta como a las
 * demás (solo cambia el destino del clic: sección "Pedido en SAP"). */

import { describe, expect, it } from "vitest";

import { ANCLA_PEDIDO_SAP, esNotificacionOC, rutaNotificacion } from "../lib/notificaciones";

const TIPOS_OC = [
  "oc_recibida",
  "oc_parcialmente_recibida",
  "oc_facturada",
  "oc_cancelada",
  "oc_cerrada_sin_recibir",
  "oc_vencida",
];

describe("rutaNotificacion", () => {
  it("las de OC navegan al detalle por rol con el ancla de Pedido en SAP", () => {
    for (const tipo of TIPOS_OC) {
      expect(esNotificacionOC(tipo)).toBe(true);
      const n = { solicitud_id: 191, tipo };
      expect(rutaNotificacion("vendedor", n)).toBe(`/vendedor/solicitudes/191#${ANCLA_PEDIDO_SAP}`);
      expect(rutaNotificacion("comprador", n)).toBe(`/comprador/solicitudes/191#${ANCLA_PEDIDO_SAP}`);
      // Gerentes de sucursal/compras, director y admin ven el detalle bajo /crm.
      expect(rutaNotificacion("gerente_sucursal", n)).toBe(`/crm/solicitudes/191#${ANCLA_PEDIDO_SAP}`);
      expect(rutaNotificacion("gerente_compras", n)).toBe(`/crm/solicitudes/191#${ANCLA_PEDIDO_SAP}`);
    }
  });

  it("los tipos anteriores siguen igual: detalle sin ancla", () => {
    for (const tipo of ["cotizada", "banda_roja", "comentario_nuevo", "pedido_confirmado"]) {
      expect(esNotificacionOC(tipo)).toBe(false);
      expect(rutaNotificacion("vendedor", { solicitud_id: 7, tipo })).toBe("/vendedor/solicitudes/7");
      expect(rutaNotificacion("admin", { solicitud_id: 7, tipo })).toBe("/crm/solicitudes/7");
    }
  });

  it("sin solicitud (seguridad) no navega", () => {
    expect(rutaNotificacion("admin", { solicitud_id: null, tipo: "seguridad" })).toBeNull();
  });
});
