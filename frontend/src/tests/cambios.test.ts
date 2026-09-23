import { describe, expect, it } from "vitest";

import {
  altaConDatos,
  armarAjustesAlta,
  construirCambio,
  filaAltaFinal,
  filaModificada,
  nuevoRenglonBody,
  renglonFormVacio,
  textoAjusteCompras,
  type FilaAltaEditor,
  type FilaAltaFinal,
  type FilaPartidaEditor,
} from "../lib/cambios";
import type { CambioPartidaOut } from "../lib/types";

function existente(sobre: Partial<FilaPartidaEditor> = {}): FilaPartidaEditor {
  return {
    partida_id: 1,
    num: 1,
    descripcionOriginal: "SOLERA",
    cantidadOriginal: "20",
    unidadOriginal: "PZ",
    descripcion: "SOLERA",
    cantidad: "20",
    unidad: "PZ",
    eliminar: false,
    ...sobre,
  };
}

function alta(sobre: Partial<FilaAltaEditor> = {}): FilaAltaEditor {
  return { key: 1, descripcion: "", cantidad: "", unidad: "PZ", ...sobre };
}

describe("filaModificada", () => {
  it("detecta cambio de cantidad, unidad o descripción", () => {
    expect(filaModificada(existente())).toBe(false);
    expect(filaModificada(existente({ cantidad: "40" }))).toBe(true);
    expect(filaModificada(existente({ unidad: "KG" }))).toBe(true);
    expect(filaModificada(existente({ descripcion: "SOLERA 1/4" }))).toBe(true);
    // "20" vs "20.0" es el mismo número.
    expect(filaModificada(existente({ cantidad: "20.0" }))).toBe(false);
    // Una fila marcada para baja no cuenta como modificada.
    expect(filaModificada(existente({ cantidad: "40", eliminar: true }))).toBe(false);
  });
});

describe("construirCambio", () => {
  it("arma modificaciones, altas y bajas y omite lo no cambiado", () => {
    const { partidas, error } = construirCambio(
      [
        existente({ partida_id: 1, num: 1, cantidad: "40" }), // modifica
        existente({ partida_id: 2, num: 2 }), // sin cambio → se omite
        existente({ partida_id: 3, num: 3, eliminar: true }), // baja
      ],
      [alta({ key: 9, descripcion: "TORNILLO", cantidad: "5", unidad: "PZ" })],
    );
    expect(error).toBeNull();
    expect(partidas).toEqual([
      {
        tipo: "MODIFICACION",
        partida_id: 1,
        cantidad_nueva: "40",
        unidad_nueva: "PZ",
        descripcion_nueva: "SOLERA",
      },
      { tipo: "BAJA", partida_id: 3 },
      { tipo: "ALTA", descripcion_nueva: "TORNILLO", cantidad_nueva: "5", unidad_nueva: "PZ" },
    ]);
  });

  it("rechaza un cambio vacío", () => {
    const { error } = construirCambio([existente()], []);
    expect(error).toMatch(/al menos una partida/);
  });

  it("no permite dar de baja todas las partidas", () => {
    const { error } = construirCambio(
      [existente({ partida_id: 1, eliminar: true }), existente({ partida_id: 2, eliminar: true })],
      [],
    );
    expect(error).toMatch(/todas las partidas/);
  });

  it("exige cantidad > 0 en una modificación y en un alta", () => {
    expect(construirCambio([existente({ cantidad: "0" })], []).error).toMatch(/mayor a 0/);
    expect(
      construirCambio([], [alta({ descripcion: "X", cantidad: "0" })]).error,
    ).toMatch(/mayor a 0/);
  });

  it("un alta sin descripción es error; una fila de alta vacía se ignora", () => {
    expect(altaConDatos(alta())).toBe(false);
    // fila de alta vacía ignorada → queda solo la modificación.
    const { partidas, error } = construirCambio(
      [existente({ cantidad: "40" })],
      [alta()],
    );
    expect(error).toBeNull();
    expect(partidas).toHaveLength(1);
    // alta con cantidad pero sin descripción → error.
    expect(construirCambio([], [alta({ cantidad: "5" })]).error).toMatch(/descripción/);
  });
});

describe("nuevoRenglonBody", () => {
  it("mapea el RenglonForm cotizado a la captura del alta", () => {
    const form = { ...renglonFormVacio(), moneda: "USD" as const, precio: "12.00", tiempo: "3 sem" };
    expect(nuevoRenglonBody(7, "B", form)).toEqual({
      cambio_partida_id: 7,
      opcion_letra: "B",
      moneda: "USD",
      precio_unitario: "12.00",
      tiempo_entrega: "3 sem",
      proveedor: null,
      no_encontrada: false,
      es_alternativa: false,
      alternativa_descripcion: null,
      con_observacion: false,
      observacion: null,
    });
  });

  it("una partida no encontrada no lleva moneda ni precio", () => {
    const form = { ...renglonFormVacio(), noEncontrada: true };
    const body = nuevoRenglonBody(3, "A", form);
    expect(body.moneda).toBeNull();
    expect(body.precio_unitario).toBeNull();
    expect(body.no_encontrada).toBe(true);
  });
});

// ------------------------------------------------ F15.1: valor final de las altas

function altaSnapshot(sobre: Partial<CambioPartidaOut> = {}): CambioPartidaOut {
  return {
    id: 7,
    tipo: "ALTA",
    partida_id: null,
    num_partida: null,
    descripcion: "TORNILLO 1/2",
    descripcion_nueva: null,
    cantidad_anterior: null,
    cantidad_nueva: "5.000",
    unidad_anterior: null,
    unidad_nueva: "PZ",
    cantidad_ajustada: null,
    unidad_ajustada: null,
    descripcion_ajustada: null,
    ...sobre,
  } as CambioPartidaOut;
}

describe("filaAltaFinal", () => {
  it("arranca en lo que pidió ventas y solo aplica a ALTA", () => {
    const f = filaAltaFinal(altaSnapshot());
    expect(f).toEqual({
      cambio_partida_id: 7,
      cantidadPedida: "5.000",
      unidadPedida: "PZ",
      descripcionPedida: "TORNILLO 1/2",
      cantidad: "5.000",
      unidad: "PZ",
      descripcion: "TORNILLO 1/2",
    });
    expect(filaAltaFinal(altaSnapshot({ tipo: "MODIFICACION", partida_id: 1 }))).toBeNull();
  });
});

describe("armarAjustesAlta", () => {
  const base = (): FilaAltaFinal => filaAltaFinal(altaSnapshot())!;

  it("sin apartarse de lo pedido no manda nada (misma cantidad aunque cambie el formato)", () => {
    expect(armarAjustesAlta([{ ...base(), cantidad: "5", descripcion: " TORNILLO 1/2 " }])).toEqual({
      altas: [],
      error: null,
    });
  });

  it("manda solo los campos que difieren, por id del renglón de cambio", () => {
    const { altas, error } = armarAjustesAlta([
      { ...base(), unidad: "KG" },
      { ...base(), cambio_partida_id: 8, cantidad: "8", descripcion: "TORNILLO 1/2 INOX 304" },
    ]);
    expect(error).toBeNull();
    expect(altas).toEqual([
      { cambio_partida_id: 7, unidad: "KG" },
      { cambio_partida_id: 8, cantidad: "8", descripcion: "TORNILLO 1/2 INOX 304" },
    ]);
  });

  it("exige cantidad > 0 y descripción no vacía", () => {
    expect(armarAjustesAlta([{ ...base(), cantidad: "0" }]).error).toMatch(/mayor a 0/);
    expect(armarAjustesAlta([{ ...base(), descripcion: "  " }]).error).toMatch(/descripción/);
  });
});

describe("textoAjusteCompras en un ALTA", () => {
  it("describe el ajuste de compras respecto a lo pedido", () => {
    expect(textoAjusteCompras(altaSnapshot())).toBeNull();
    expect(textoAjusteCompras(altaSnapshot({ unidad_ajustada: "KG" }))).toBe("compras ajustó a 5.000 KG");
    expect(
      textoAjusteCompras(altaSnapshot({ cantidad_ajustada: "8.000", descripcion_ajustada: "TORNILLO 1/2 INOX 304" })),
    ).toBe("compras ajustó a 8.000 PZ · descripción final: “TORNILLO 1/2 INOX 304”");
  });
});
