import { describe, expect, it } from "vitest";

import { bandaColor, bandaTooltip, dinero, folioCliente } from "../lib/format";

describe("dinero por moneda", () => {
  it("formatea MXN y USD con su prefijo, sin mezclar jamás", () => {
    expect(dinero("28325.00", "MXN")).toBe("MX$ 28,325.00");
    expect(dinero("351", "USD")).toBe("US$ 351.00");
    expect(dinero(1234.5, "MXN")).toBe("MX$ 1,234.50");
  });
});

describe("banda → color", () => {
  it("mapea las tres bandas al semáforo", () => {
    expect(bandaColor("ESPERADA")).toBe("green");
    expect(bandaColor("NORMAL")).toBe("yellow");
    expect(bandaColor("LENTA")).toBe("red");
  });
  it("arma el tooltip 'X.X h hábiles · día T'", () => {
    expect(bandaTooltip(25.0, 3)).toBe("25.0 h hábiles · día 3");
  });
});

describe("folio · cliente", () => {
  it("compone la referencia corta", () => {
    expect(folioCliente("CCN-3036", "DINCO")).toBe("CCN-3036 · DINCO");
    expect(folioCliente(null, "DINCO")).toBe("(sin folio) · DINCO");
  });
});
