import { describe, expect, it } from "vitest";

import {
  parsearFaltantesCotizacion,
  parsearFaltantesEnvio,
  partidaSchema,
} from "../lib/validacion";

describe("Zod de partida (espejo del backend PartidaIn)", () => {
  const base = { codigo_sap: "", cantidad: "2", unidad: "PZ", tipo_acero: "", descripcion: "PTR", medidas: "" };

  it("acepta una partida válida", () => {
    expect(partidaSchema.safeParse(base).success).toBe(true);
  });
  it("rechaza cantidad <= 0 o no numérica", () => {
    expect(partidaSchema.safeParse({ ...base, cantidad: "0" }).success).toBe(false);
    expect(partidaSchema.safeParse({ ...base, cantidad: "-3" }).success).toBe(false);
    expect(partidaSchema.safeParse({ ...base, cantidad: "abc" }).success).toBe(false);
  });
  it("exige unidad DEL CATÁLOGO y descripción", () => {
    expect(partidaSchema.safeParse({ ...base, unidad: " " }).success).toBe(false);
    expect(partidaSchema.safeParse({ ...base, unidad: "PZA" }).success).toBe(false);
    expect(partidaSchema.safeParse({ ...base, unidad: "LOTE" }).success).toBe(false);
    expect(partidaSchema.safeParse({ ...base, descripcion: "" }).success).toBe(false);
  });
  it("codigo_sap, tipo_acero y medidas son opcionales", () => {
    expect(
      partidaSchema.safeParse({ ...base, codigo_sap: "", tipo_acero: "", medidas: "" }).success,
    ).toBe(true);
  });
});

describe("mapeo del 422 real de cotizar a campos", () => {
  it("parsea opción/campo/partida de cada pieza", () => {
    // Formato REAL del backend (_faltantes_de en cotizaciones/service.py).
    const detail =
      "Cotización incompleta: opción A: falta moneda; opción A: falta precio_unitario " +
      "en la partida 2; opción B: falta tiempo_entrega en la partida 1";
    expect(parsearFaltantesCotizacion(detail)).toEqual([
      { letra: "A", campo: "moneda", num_partida: null },
      { letra: "A", campo: "precio_unitario", num_partida: 2 },
      { letra: "B", campo: "tiempo_entrega", num_partida: 1 },
    ]);
  });
  it("parsea la vigencia sin partida", () => {
    expect(parsearFaltantesCotizacion("Cotización incompleta: opción C: falta vigencia")).toEqual([
      { letra: "C", campo: "vigencia", num_partida: null },
    ]);
  });
});

describe("mapeo del 422 del envío", () => {
  it("detecta cliente y partidas faltantes", () => {
    expect(parsearFaltantesEnvio("No se puede enviar, faltan: cliente, al menos una partida")).toEqual(
      { cliente: true, partidas: true },
    );
    expect(parsearFaltantesEnvio("No se puede enviar, faltan: cliente")).toEqual({
      cliente: true,
      partidas: false,
    });
  });
});
