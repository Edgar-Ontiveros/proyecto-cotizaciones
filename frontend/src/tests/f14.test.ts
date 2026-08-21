/** F14 — p.2: documento de impresión elegido por el ESTATUS (sin que el
 * usuario escoja); p.3: comparador de orden de Comparativas — numérico, con
 * vacíos SIEMPRE al final en ambas direcciones y el criterio V/A/R (rojas). */

import { describe, expect, it } from "vitest";

import {
  type FilaComparativa,
  aFilaComparativa,
  documentoPorEstado,
  ordenarComparativa,
} from "../lib/crm";
import type { Estado, GrupoOut } from "../lib/types";

function grupo(sobre: Partial<GrupoOut> & { id: number; nombre: string }): GrupoOut {
  return {
    volumen: 0,
    ciclos_cerrados: 0,
    mediana_horas_habiles: null,
    pct_banda_esperada: null,
    distribucion_bandas: {},
    dinero_confirmado: {},
    carga_abierta: null,
    cotizadas: null,
    confirmadas: null,
    no_confirmadas: null,
    sin_desenlace: null,
    ratio_confirmacion: null,
    ...sobre,
  };
}

const filas: FilaComparativa[] = [
  grupo({ id: 1, nombre: "Matriz", dinero_confirmado: { MXN: "78928.45" } }),
  grupo({ id: 2, nombre: "Norte", dinero_confirmado: { MXN: "569939.56" } }),
  grupo({ id: 3, nombre: "León", dinero_confirmado: {} }), // vacío ("—")
  grupo({ id: 4, nombre: "Mexicali", dinero_confirmado: { MXN: "0" } }), // 0 = vacío
].map(aFilaComparativa);

describe("ordenarComparativa (F14 p.3)", () => {
  it("Confirmado (MXN) ordena NUMÉRICO: 569,939.56 sobre 78,928.45", () => {
    const desc = ordenarComparativa(filas, "confirmado_mxn", "desc");
    // Alfabéticamente "78..." > "569..." — el orden numérico lo corrige.
    expect(desc.map((f) => f.nombre)).toEqual(["Norte", "Matriz", "León", "Mexicali"]);
  });

  it("los vacíos van al FINAL en ambas direcciones", () => {
    const asc = ordenarComparativa(filas, "confirmado_mxn", "asc");
    expect(asc.map((f) => f.nombre)).toEqual(["Matriz", "Norte", "León", "Mexicali"]);
    const desc = ordenarComparativa(filas, "confirmado_mxn", "desc");
    expect(desc.slice(-2).map((f) => f.nombre)).toEqual(["León", "Mexicali"]);
  });

  it("V/A/R ordena por ROJAS (LENTA) — lo urgente arriba en desc", () => {
    const conBandas = [
      grupo({ id: 1, nombre: "A", distribucion_bandas: { ESPERADA: 5, LENTA: 0 } }),
      grupo({ id: 2, nombre: "B", distribucion_bandas: { NORMAL: 1, LENTA: 3 } }),
      grupo({ id: 3, nombre: "C", distribucion_bandas: { LENTA: 1 } }),
    ].map(aFilaComparativa);
    expect(conBandas.map((f) => f.rojas)).toEqual([0, 3, 1]);
    const desc = ordenarComparativa(conBandas, "rojas", "desc");
    expect(desc.map((f) => f.nombre)).toEqual(["B", "C", "A"]);
  });

  it("desempata estable por nombre y no muta el arreglo original", () => {
    const empatadas = [
      grupo({ id: 1, nombre: "Zeta", volumen: 7 }),
      grupo({ id: 2, nombre: "Alfa", volumen: 7 }),
    ].map(aFilaComparativa);
    const orden = ordenarComparativa(empatadas, "volumen", "desc");
    expect(orden.map((f) => f.nombre)).toEqual(["Alfa", "Zeta"]);
    expect(empatadas.map((f) => f.nombre)).toEqual(["Zeta", "Alfa"]); // intacto
  });

  it("el vendedor sin la clave dinero_confirmado produce vacío, no error", () => {
    const sinClave = aFilaComparativa(grupo({ id: 9, nombre: "V", dinero_confirmado: undefined }));
    expect(sinClave.confirmado_mxn).toBeNull();
  });
});

describe("documentoPorEstado (F14 p.2)", () => {
  it("COTIZADA → Cotización; CONFIRMADA → Pedido confirmado", () => {
    expect(documentoPorEstado("COTIZADA")).toBe("COTIZACION");
    expect(documentoPorEstado("CONFIRMADA")).toBe("PEDIDO_CONFIRMADO");
  });

  it("estatus previos y terminales sin documento → null (botón inactivo)", () => {
    const previos: Estado[] = ["BORRADOR", "ENVIADA", "EN_PROCESO", "RECHAZADA", "CANCELADA"];
    for (const estado of previos) expect(documentoPorEstado(estado)).toBeNull();
  });
});
