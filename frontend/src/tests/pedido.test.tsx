/** F10.2 p.2/3a — el test de mapeo ganadora→estilos que habría cazado el
 * reporte de producción: VistaPedido DEBE distinguir la elegida (verde, badge
 * GANADORA, expandida) de las no elegidas (atenuadas y colapsadas). */

import { MantineProvider } from "@mantine/core";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

// jsdom no trae matchMedia y MantineProvider lo usa (patrón de
// modal-providers.test).
window.matchMedia = vi.fn().mockImplementation((query: string) => ({
  matches: false,
  media: query,
  addEventListener: vi.fn(),
  removeEventListener: vi.fn(),
  addListener: vi.fn(),
  removeListener: vi.fn(),
  dispatchEvent: vi.fn(),
  onchange: null,
}));

import { VistaPedido } from "../components/Pedido";
import type { OpcionOut, RenglonOut, SolicitudDetailOut } from "../lib/types";

function renglon(sobre: Partial<RenglonOut>): RenglonOut {
  return {
    id: 1,
    partida_id: 1,
    num_partida: 1,
    cantidad: "30",
    unidad: "PZ",
    moneda: "MXN",
    precio_unitario: "240.0000",
    importe: "7200.00",
    tiempo_entrega: "3 semanas",
    no_encontrada: false,
    es_alternativa: false,
    alternativa_descripcion: null,
    con_observacion: false,
    observacion: null,
    proveedor: "Aceros del Norte",
    ...sobre,
  };
}

function opcion(sobre: Partial<OpcionOut>): OpcionOut {
  return {
    id: 1,
    letra: "A",
    vigencia: "2026-09-30",
    comentarios: null,
    total_mxn: "8200.00",
    total_usd: "0.00",
    completa: true,
    consolidado_mxn: "8200.00",
    renglones: [renglon({})],
    ...sobre,
  };
}

/** Espejo del JSON real de la reproducción F10.2 (URGENTE + proyecto +
 * cambio aprobado + confirmada con B). Solo los campos que la vista usa. */
function solicitudConfirmada(): SolicitudDetailOut {
  return {
    opcion_seleccionada_id: 2,
    estado: "CONFIRMADA",
    tipo_cambio: null,
    opciones: [
      opcion({ id: 1, letra: "A" }),
      opcion({
        id: 2,
        letra: "B",
        total_mxn: "8650.00",
        consolidado_mxn: "8650.00",
        renglones: [renglon({ id: 2, precio_unitario: "255.0000", importe: "7650.00" })],
      }),
    ],
  } as unknown as SolicitudDetailOut;
}

function pintar(solicitud: SolicitudDetailOut) {
  return render(
    <MantineProvider>
      <VistaPedido solicitud={solicitud} />
    </MantineProvider>,
  );
}

describe("VistaPedido — mapeo ganadora→estilos (F10.2)", () => {
  it("la elegida lleva badge GANADORA y su tabla visible (verde)", () => {
    pintar(solicitudConfirmada());
    expect(screen.getByText(/GANADORA — genera la orden de compra/)).toBeInTheDocument();
    // La tabla de la ganadora (B) está expandida: su proveedor es visible.
    expect(screen.getAllByText("Aceros del Norte").length).toBeGreaterThan(0);
  });

  it("las no elegidas quedan colapsadas con botón 'Ver detalle' (gris)", () => {
    pintar(solicitudConfirmada());
    expect(screen.getByText("Ver detalle")).toBeInTheDocument();
  });

  it("la observación del renglón (F11) es visible en el pedido", () => {
    const solicitud = solicitudConfirmada();
    solicitud.opciones[1]!.renglones = [
      renglon({ id: 2, con_observacion: true, observacion: "Sujeto a disponibilidad" }),
    ];
    pintar(solicitud);
    expect(screen.getByText(/OBSERVACIÓN: Sujeto a disponibilidad/)).toBeInTheDocument();
  });

  it("sin seleccionada (COTIZADA) no hay badge ni colapsadas", () => {
    const solicitud = solicitudConfirmada();
    (solicitud as { opcion_seleccionada_id: number | null }).opcion_seleccionada_id = null;
    (solicitud as { estado: string }).estado = "COTIZADA";
    pintar(solicitud);
    expect(screen.queryByText(/GANADORA/)).not.toBeInTheDocument();
    expect(screen.queryByText("Ver detalle")).not.toBeInTheDocument();
  });
});
