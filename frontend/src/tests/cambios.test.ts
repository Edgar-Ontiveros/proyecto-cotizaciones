import { describe, expect, it } from "vitest";

import {
  altaConDatos,
  construirCambio,
  filaModificada,
  nuevoRenglonBody,
  renglonFormVacio,
  type FilaAltaEditor,
  type FilaPartidaEditor,
} from "../lib/cambios";

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
