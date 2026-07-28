import { describe, expect, it, vi } from "vitest";

import {
  aplicarNoEncontrada,
  consolidadoMXN,
  corregirYReenviar,
  renglonABody,
  validarRenglonLocal,
  type RenglonForm,
} from "../lib/renglon";

const base: RenglonForm = {
  cantidad: "20",
  unidad: "PZ",
  moneda: "MXN",
  precio: "",
  tiempo: "",
  proveedor: "",
  noEncontrada: false,
  esAlternativa: false,
  alternativaDescripcion: "",
};

describe("validación local del renglón rico (espejo del backend)", () => {
  it("no_encontrada es incompatible con alternativa y con precio", () => {
    expect(
      validarRenglonLocal({ ...base, noEncontrada: true, esAlternativa: true }),
    ).toMatch(/no puede ser alternativa/);
    expect(validarRenglonLocal({ ...base, noEncontrada: true, precio: "10" })).toMatch(
      /no lleva precio/,
    );
  });
  it("la alternativa exige descripción y precio", () => {
    expect(validarRenglonLocal({ ...base, esAlternativa: true, precio: "10" })).toMatch(
      /Describe qué alternativa/,
    );
    expect(
      validarRenglonLocal({
        ...base,
        esAlternativa: true,
        alternativaDescripcion: "PTR similar",
      }),
    ).toMatch(/exige precio/);
    expect(
      validarRenglonLocal({
        ...base,
        esAlternativa: true,
        alternativaDescripcion: "PTR similar",
        precio: "10",
      }),
    ).toBeNull();
  });
  it("un renglón normal o uno no-encontrado limpio son válidos", () => {
    expect(validarRenglonLocal(base)).toBeNull();
    expect(validarRenglonLocal({ ...base, noEncontrada: true })).toBeNull();
  });
});

describe("toggle No encontrada", () => {
  it("limpia precio/tiempo/proveedor/alternativa al activarse", () => {
    const sucio: RenglonForm = {
      ...base,
      precio: "10",
      tiempo: "1 semana",
      proveedor: "Aceros",
      esAlternativa: true,
      alternativaDescripcion: "algo",
    };
    const limpio = aplicarNoEncontrada(sucio, true);
    expect(limpio).toMatchObject({
      noEncontrada: true,
      precio: "",
      tiempo: "",
      proveedor: "",
      esAlternativa: false,
      alternativaDescripcion: "",
    });
    // Cantidad y unidad se conservan (siguen describiendo lo pedido).
    expect(limpio.cantidad).toBe("20");
  });
});

describe("renglonABody", () => {
  it("vacíos → null y banderas tal cual", () => {
    expect(renglonABody(7, { ...base, precio: " 10.5 ", noEncontrada: false })).toEqual({
      partida_id: 7,
      cantidad: "20",
      unidad: "PZ",
      moneda: "MXN",
      precio_unitario: "10.5",
      tiempo_entrega: null,
      proveedor: null,
      no_encontrada: false,
      es_alternativa: false,
      alternativa_descripcion: null,
    });
  });
});

describe("corregir-y-reenviar (F8b)", () => {
  it("llama PATCH (editar) ANTES que enviar", async () => {
    const orden: string[] = [];
    const editar = vi.fn(async () => {
      orden.push("editar");
    });
    const enviar = vi.fn(async () => {
      orden.push("enviar");
      return { folio: "JRZ-9" };
    });
    const resultado = await corregirYReenviar({ editar, enviar });
    expect(orden).toEqual(["editar", "enviar"]);
    expect(resultado.folio).toBe("JRZ-9");
  });

  it("si la edición falla, NO se reenvía", async () => {
    const enviar = vi.fn();
    await expect(
      corregirYReenviar({ editar: () => Promise.reject(new Error("422")), enviar }),
    ).rejects.toThrow("422");
    expect(enviar).not.toHaveBeenCalled();
  });
});

describe("consolidadoMXN (F8c)", () => {
  it("consolida MXN + USD x TC con redondeo a 2", () => {
    expect(consolidadoMXN("12000.00", "500.00", "18.5")).toBe(21250);
    expect(consolidadoMXN("0.00", "351.00", "18.50")).toBe(6493.5);
  });
  it("sin TC con USD presente no hay consolidado; 100% MXN lo ignora", () => {
    expect(consolidadoMXN("100.00", "50.00", "")).toBeNull();
    expect(consolidadoMXN("100.00", "0.00", "")).toBe(100);
  });
});
