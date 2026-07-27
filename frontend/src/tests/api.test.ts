/** El contrato del wrapper: refresh SINGLE-FLIGHT ante 401 concurrentes y
 * logout ante refresh fallido. */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api, configurarCallbacks, setAccessToken } from "../lib/api";

function respuesta(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("wrapper de fetch", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    vi.stubGlobal("fetch", fetchMock);
    fetchMock.mockReset();
    setAccessToken("token-viejo");
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    configurarCallbacks({ sesionExpirada: () => {}, passwordChangeRequired: () => {} });
  });

  it("dos 401 simultáneos disparan EXACTAMENTE un refresh y ambos reintentan", async () => {
    fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/auth/refresh")) {
        return Promise.resolve(respuesta(200, { access_token: "token-nuevo" }));
      }
      const auth = (init?.headers as Record<string, string>)?.["Authorization"];
      if (auth === "Bearer token-nuevo") {
        return Promise.resolve(respuesta(200, { ok: url }));
      }
      return Promise.resolve(respuesta(401, { detail: "expirado", code: "invalid_token" }));
    });

    const [a, b] = await Promise.all([
      api<{ ok: string }>("/solicitudes"),
      api<{ ok: string }>("/notificaciones"),
    ]);

    const llamadasRefresh = fetchMock.mock.calls.filter((c) =>
      String(c[0]).includes("/auth/refresh"),
    );
    expect(llamadasRefresh).toHaveLength(1); // single-flight
    expect(a.ok).toContain("/solicitudes");
    expect(b.ok).toContain("/notificaciones");
    // Cada request: intento original + reintento = 2; más 1 refresh = 5.
    expect(fetchMock).toHaveBeenCalledTimes(5);
  });

  it("refresh fallido limpia la sesión y avisa (logout)", async () => {
    const sesionExpirada = vi.fn();
    configurarCallbacks({ sesionExpirada });
    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/auth/refresh")) {
        return Promise.resolve(respuesta(401, { detail: "revocado", code: "invalid_refresh" }));
      }
      return Promise.resolve(respuesta(401, { detail: "expirado", code: "invalid_token" }));
    });

    await expect(api("/solicitudes")).rejects.toMatchObject({ code: "session_expired" });
    expect(sesionExpirada).toHaveBeenCalledTimes(1);
  });

  it("los errores del backend llegan tipados {detail, code}", async () => {
    fetchMock.mockResolvedValue(
      respuesta(409, { detail: "La solicitud está en estado COTIZADA", code: "estado_conflicto" }),
    );
    await expect(api("/solicitudes/1/enviar", { method: "POST" })).rejects.toMatchObject({
      status: 409,
      detail: "La solicitud está en estado COTIZADA",
      code: "estado_conflicto",
    });
  });
});
