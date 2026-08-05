/** F10 p.1 — regresión del bug de producción: tras aprobar un cambio en el
 * navegador del comprador, la vista abierta del vendedor debe refrescarse
 * sola (polling condicionado a cambio_pendiente). */

import { describe, expect, it } from "vitest";

import { intervaloDetalle } from "../api/hooks";

describe("intervaloDetalle (F10 p.1)", () => {
  it("con cambio pendiente hace polling cada 15 s", () => {
    expect(intervaloDetalle({ cambio_pendiente: true })).toBe(15_000);
  });

  it("sin cambio pendiente NO hay polling (se detiene solo al resolverse)", () => {
    expect(intervaloDetalle({ cambio_pendiente: false })).toBe(false);
    expect(intervaloDetalle({})).toBe(false);
    expect(intervaloDetalle(undefined)).toBe(false);
  });
});
