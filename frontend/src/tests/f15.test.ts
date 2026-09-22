/** F15 — p.1: armado de params del periodo de Comparativas (rango libre o
 * mes en curso); p.3: helpers puros de la recotización completa del lado
 * compras (valor final por partida, regla de la unidad, texto del diff). */

import { describe, expect, it } from "vitest";

import {
  armarAjustesPartida,
  filaPartidaFinal,
  textoAjusteCompras,
  unidadInvalidaPrecio,
  type FilaPartidaFinal,
} from "../lib/cambios";
import { periodoComparativas } from "../lib/crm";
import type { CambioPartidaOut } from "../lib/types";

describe("periodoComparativas (F15 p.1)", () => {
  it("sin rango = mes en curso (mismo preset del dashboard) y el título lo dice", () => {
    const periodo = periodoComparativas([null, null], "2026-09-22");
    expect(periodo.params).toMatchObject({ desde: "2026-09-01", hasta: "2026-09-22" });
    expect(periodo.titulo).toBe("mes en curso");
    expect(periodo.personalizado).toBe(false);
  });

  it("con rango completo manda desde/hasta y el título deja de decir 'mes en curso'", () => {
    const periodo = periodoComparativas(["2026-07-01", "2026-08-15"], "2026-09-22");
    expect(periodo.params).toEqual({ desde: "2026-07-01", hasta: "2026-08-15" });
    expect(periodo.titulo).not.toContain("mes en curso");
    expect(periodo.titulo).toMatch(/^del .* al .*$/);
    expect(periodo.personalizado).toBe(true);
  });

  it("un extremo vacío queda abierto (el backend acepta desde o hasta solos)", () => {
    const soloDesde = periodoComparativas(["2026-07-01", null], "2026-09-22");
    expect(soloDesde.params).toEqual({ desde: "2026-07-01", hasta: undefined });
    expect(soloDesde.titulo).toMatch(/^desde el /);
    const soloHasta = periodoComparativas([null, "2026-08-15"], "2026-09-22");
    expect(soloHasta.params).toEqual({ desde: undefined, hasta: "2026-08-15" });
    expect(soloHasta.titulo).toMatch(/^hasta el /);
  });

  it("acepta la fecha como la entrega el DatePickerInput (ISO con hora) y la normaliza", () => {
    const periodo = periodoComparativas(
      ["2026-07-01T06:00:00.000Z", "2026-08-15T06:00:00.000Z"],
      "2026-09-22",
    );
    expect(periodo.params.desde).toBe("2026-07-01");
    expect(periodo.params.hasta).toBe("2026-08-15");
  });
});

function renglonMod(sobre: Partial<CambioPartidaOut> = {}): CambioPartidaOut {
  return {
    id: 7,
    tipo: "MODIFICACION",
    partida_id: 11,
    num_partida: 1,
    descripcion: "SOLERA 1/8 X 1",
    descripcion_nueva: null,
    cantidad_anterior: "20.000",
    cantidad_nueva: "25.000",
    unidad_anterior: "PZ",
    unidad_nueva: "PZ",
    cantidad_ajustada: null,
    unidad_ajustada: null,
    descripcion_ajustada: null,
    ...sobre,
  };
}

describe("recotización completa (F15 p.3)", () => {
  it("la fila final arranca en lo PEDIDO por ventas (o lo anterior si no cambió)", () => {
    const fila = filaPartidaFinal(renglonMod());
    expect(fila).toMatchObject({
      partida_id: 11,
      cantidadPedida: "25.000",
      unidadPedida: "PZ",
      descripcionPedida: "SOLERA 1/8 X 1",
      cantidad: "25.000",
      unidad: "PZ",
      descripcion: "SOLERA 1/8 X 1",
    });
    const conDescr = filaPartidaFinal(renglonMod({ descripcion_nueva: "SOLERA INOX" }));
    expect(conDescr?.descripcion).toBe("SOLERA INOX");
    expect(filaPartidaFinal(renglonMod({ tipo: "ALTA", partida_id: null }))).toBeNull();
    expect(filaPartidaFinal(renglonMod({ tipo: "BAJA" }))).toBeNull();
  });

  const base: FilaPartidaFinal = {
    partida_id: 11,
    num: 1,
    cantidadPedida: "25.000",
    unidadPedida: "PZ",
    descripcionPedida: "SOLERA 1/8 X 1",
    cantidad: "25.000",
    unidad: "PZ",
    descripcion: "SOLERA 1/8 X 1",
  };

  it("sin apartarse de lo pedido no viaja nada (escenario viejo intacto)", () => {
    expect(armarAjustesPartida([base])).toEqual({ partidas: [], error: null });
    // "25" y "25.000" son la misma cantidad; espacios en la descripción no cuentan.
    expect(
      armarAjustesPartida([{ ...base, cantidad: "25", descripcion: " SOLERA 1/8 X 1 " }]).partidas,
    ).toEqual([]);
  });

  it("solo unidad → viaja solo la unidad; unidad + cantidad + descripción → los tres", () => {
    expect(armarAjustesPartida([{ ...base, unidad: "KG" }]).partidas).toEqual([
      { partida_id: 11, unidad: "KG" },
    ]);
    expect(
      armarAjustesPartida([
        { ...base, unidad: "KG", cantidad: "30", descripcion: "SOLERA 1/8 X 1 INOX 304" },
      ]).partidas,
    ).toEqual([
      { partida_id: 11, cantidad: "30", unidad: "KG", descripcion: "SOLERA 1/8 X 1 INOX 304" },
    ]);
  });

  it("valida cantidad > 0 y descripción no vacía", () => {
    expect(armarAjustesPartida([{ ...base, cantidad: "0" }]).error).toMatch(/mayor a 0/);
    expect(armarAjustesPartida([{ ...base, cantidad: "abc" }]).error).toMatch(/mayor a 0/);
    expect(armarAjustesPartida([{ ...base, descripcion: "   " }]).error).toMatch(/descripción/);
  });

  it("la unidad final distinta a la del renglón invalida el precio anterior", () => {
    expect(unidadInvalidaPrecio("KG", "PZ")).toBe(true);
    expect(unidadInvalidaPrecio("PZ", "PZ")).toBe(false);
  });

  it("el diff enuncia el ajuste de compras solo cuando existe", () => {
    expect(textoAjusteCompras(renglonMod())).toBeNull();
    expect(textoAjusteCompras(renglonMod({ unidad_ajustada: "KG" }))).toBe(
      "compras ajustó a 25.000 KG",
    );
    expect(
      textoAjusteCompras(
        renglonMod({ cantidad_ajustada: "30.000", descripcion_ajustada: "SOLERA INOX 304" }),
      ),
    ).toBe("compras ajustó a 30.000 PZ · descripción final: “SOLERA INOX 304”");
  });
});
