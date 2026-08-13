/** Regresión F11 p.2 — el botón "Rechazar" del comprador no funcionaba: el
 * modal abría pero el Select de motivos quedaba VACÍO porque el frontend
 * pedía el catálogo a /catalogos/motivos-rechazo (404: esa ruta jamás existió
 * en el backend) y, sin motivo seleccionable, "Rechazar solicitud" nunca se
 * habilitaba. Mismo 404 que rompía las altas de catálogos del admin (p.3).
 * Este test recorre el flujo del modal contra las rutas REALES del backend:
 * carga del catálogo → elegir motivo → submit al endpoint de rechazo. */

import { MantineProvider } from "@mantine/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

// jsdom no trae matchMedia y MantineProvider lo usa.
window.matchMedia = vi.fn().mockImplementation((query: string) => ({
  matches: false,
  media: query,
  addEventListener: vi.fn(),
  removeEventListener: vi.fn(),
  addListener: vi.fn(),
  removeListener: vi.fn(),
  dispatchEvent: vi.fn(),
  onchange: null,
}));

// jsdom tampoco trae ResizeObserver (el dropdown del Select lo usa).
window.ResizeObserver = vi.fn().mockImplementation(() => ({
  observe: vi.fn(),
  unobserve: vi.fn(),
  disconnect: vi.fn(),
}));

import { ModalRechazo } from "../views/comprador/CapturaCotizacion";

const MOTIVOS = [
  { id: 1, familia: "falta_informacion", texto: "Faltan medidas", activo: true },
  { id: 4, familia: "no_procede", texto: "Material fuera de línea", activo: true },
  { id: 5, familia: "no_procede", texto: "Motivo inactivo", activo: false },
];

function fetchFalso() {
  // El segundo parámetro (RequestInit) solo existe para tipar mock.calls.
  return vi.fn(async (...args: [RequestInfo | URL, RequestInit?]) => {
    const url = String(args[0]);
    if (url.endsWith("/api/v1/motivos-rechazo")) {
      return new Response(JSON.stringify(MOTIVOS), { status: 200 });
    }
    if (url.endsWith("/api/v1/solicitudes/7/rechazar")) {
      return new Response(JSON.stringify({ id: 7, estado: "RECHAZADA" }), { status: 200 });
    }
    // Cualquier otra ruta (p. ej. /catalogos/…) es el bug: 404 como en el
    // backend real.
    return new Response(JSON.stringify({ detail: "Not Found", code: "not_found" }), {
      status: 404,
    });
  });
}

function pintar(onListo: () => void) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <MantineProvider>
      <QueryClientProvider client={qc}>
        <ModalRechazo solicitudId={7} onListo={onListo} />
      </QueryClientProvider>
    </MantineProvider>,
  );
  return qc;
}

describe("ModalRechazo (F11 p.2)", () => {
  it("carga el catálogo de la ruta real, habilita el botón y rechaza", async () => {
    const fetchMock = fetchFalso();
    vi.stubGlobal("fetch", fetchMock);
    const onListo = vi.fn();
    const usuario = userEvent.setup();
    const qc = pintar(onListo);

    // El botón nace deshabilitado (sin motivo elegido).
    const boton = await screen.findByRole("button", { name: /Rechazar solicitud/ });
    expect(boton).toBeDisabled();

    // El catálogo vino de /api/v1/motivos-rechazo (la ruta REAL, sin
    // /catalogos): el Select ofrece los motivos activos.
    await waitFor(() => {
      expect(qc.getQueryState(["motivos-rechazo"])?.status).toBe("success");
    });
    expect(
      fetchMock.mock.calls.some((c) => String(c[0]).endsWith("/api/v1/motivos-rechazo")),
    ).toBe(true);
    // El dropdown flotante queda display:none en jsdom (no corre el
    // posicionador), así que las opciones se localizan por TEXTO.
    await usuario.click(screen.getByRole("combobox", { name: /Motivo del catálogo/ }));
    await usuario.click(await screen.findByText("Material fuera de línea"));
    expect(screen.queryByText("Motivo inactivo")).not.toBeInTheDocument();

    // Con motivo elegido el botón se habilita y el submit pega al endpoint
    // real de rechazo con el motivo_id del catálogo.
    expect(boton).toBeEnabled();
    await usuario.click(boton);
    await waitFor(() => {
      expect(onListo).toHaveBeenCalled();
    });
    const llamadaRechazo = fetchMock.mock.calls.find((c) =>
      String(c[0]).endsWith("/api/v1/solicitudes/7/rechazar"),
    );
    expect(llamadaRechazo).toBeDefined();
    const cuerpo = JSON.parse(String(llamadaRechazo?.[1]?.body));
    expect(cuerpo).toEqual({ motivo_id: 4, comentario: null });
    vi.unstubAllGlobals();
  });
});
