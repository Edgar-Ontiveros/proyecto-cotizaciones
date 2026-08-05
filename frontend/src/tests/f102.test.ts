/** F10.2 — lógica pura de los fixes:
 * p.1: armarAjustes NO pierde los ajustes de solo-tiempo (bug de producción).
 * p.3b: proveedoresGanadora arma la lista ÚNICA y omite renglones sin dato. */

import { describe, expect, it } from "vitest";

import { proveedoresGanadora } from "../lib/crm";
import { armarAjustes, type FilaAjusteEditor } from "../lib/renglon";

function fila(sobre: Partial<FilaAjusteEditor>): FilaAjusteEditor {
  return {
    letra: "A",
    partida_id: 1,
    unidadCambia: false,
    precioActual: "250.0000",
    tiempoActual: "1 semana",
    precio: "250.0000",
    tiempo: "1 semana",
    ...sobre,
  };
}

describe("armarAjustes (F10.2 p.1)", () => {
  it("BUG de producción: el ajuste de SOLO tiempo ahora viaja", () => {
    const ajustes = armarAjustes([fila({ tiempo: "3 semanas" })]);
    expect(ajustes).toEqual([{ opcion_letra: "A", partida_id: 1, tiempo_entrega: "3 semanas" }]);
  });

  it("precio y tiempo juntos viajan completos", () => {
    const ajustes = armarAjustes([fila({ precio: "240", tiempo: "3 semanas" })]);
    expect(ajustes).toEqual([
      { opcion_letra: "A", partida_id: 1, precio_unitario: "240", tiempo_entrega: "3 semanas" },
    ]);
  });

  it("sin cambios reales no viaja nada (250.0000 == 250 numéricamente)", () => {
    expect(armarAjustes([fila({ precio: "250" })])).toEqual([]);
  });

  it("cambio de unidad SIEMPRE manda el precio nuevo", () => {
    const ajustes = armarAjustes([fila({ unidadCambia: true, precio: "94.80", tiempo: "" })]);
    expect(ajustes).toEqual([{ opcion_letra: "A", partida_id: 1, precio_unitario: "94.80" }]);
  });
});

describe("proveedoresGanadora (F10.2 p.3b)", () => {
  const solicitud = {
    opcion_seleccionada_id: 2,
    opciones: [
      { id: 1, renglones: [{ proveedor: "Otro" }] },
      {
        id: 2,
        renglones: [
          { proveedor: "Aceros del Norte" },
          { proveedor: "Rolled Alloys" },
          { proveedor: "Aceros del Norte" }, // duplicado → una sola vez
          { proveedor: null }, // sin dato → se omite
          {}, // clave ausente (rol vendedor) → se omite
        ],
      },
    ],
  };

  it("lista ÚNICA de la ganadora, sin nulos ni duplicados", () => {
    expect(proveedoresGanadora(solicitud)).toEqual(["Aceros del Norte", "Rolled Alloys"]);
  });

  it("sin seleccionada o sin claves (vendedor) → lista vacía", () => {
    expect(proveedoresGanadora({ ...solicitud, opcion_seleccionada_id: null })).toEqual([]);
    expect(
      proveedoresGanadora({
        opcion_seleccionada_id: 2,
        opciones: [{ id: 2, renglones: [{}, {}] }],
      }),
    ).toEqual([]);
  });
});

describe("paramsPestanaComprador (F10.2 p.4)", () => {
  it("Cotizadas sin y con el filtro de cambio solicitado", async () => {
    const { paramsPestanaComprador } = await import("../lib/crm");
    expect(paramsPestanaComprador("cotizadas")).toEqual({ estado: "COTIZADA" });
    expect(paramsPestanaComprador("cotizadas", true)).toEqual({
      estado: "COTIZADA",
      cambio_pendiente: true,
    });
  });

  it("Confirmadas ordena por confirmado_en; Todas sin filtros", async () => {
    const { paramsPestanaComprador } = await import("../lib/crm");
    expect(paramsPestanaComprador("confirmadas")).toEqual({
      estado: "CONFIRMADA",
      orden: "confirmado_en",
    });
    expect(paramsPestanaComprador("todas")).toEqual({});
  });
});
