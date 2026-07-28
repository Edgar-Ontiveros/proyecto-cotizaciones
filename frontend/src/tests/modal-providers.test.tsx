/** Regresión del bug F8e punto 0: los formularios del CRM viven en
 * modals.open y usan hooks de TanStack Query; con ModalsProvider FUERA de
 * QueryClientProvider el portal del modal no ve el QueryClient y truena
 * ("editar usuario/sucursal da error"). El stack real (Providers) debe
 * mantener QueryClientProvider POR ENCIMA de ModalsProvider. */

import { MantineProvider } from "@mantine/core";
import { ModalsProvider, modals } from "@mantine/modals";
import { QueryClient, QueryClientProvider, useQueryClient } from "@tanstack/react-query";
import { act, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { Providers } from "../Providers";

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

function ContenidoConHook() {
  useQueryClient(); // truena si el modal no ve el QueryClientProvider
  return <div>CONTENIDO MODAL</div>;
}

const SIN_TRANSICION = { transitionProps: { duration: 0 } };

describe("providers y modals.open", () => {
  it("el orden viejo (ModalsProvider fuera) reproducía el bug", async () => {
    const qc = new QueryClient();
    render(
      <MantineProvider>
        <ModalsProvider modalProps={SIN_TRANSICION}>
          <QueryClientProvider client={qc}>
            <div>app</div>
          </QueryClientProvider>
        </ModalsProvider>
      </MantineProvider>,
    );
    let error: unknown = null;
    try {
      await act(async () => {
        modals.open({ title: "x", children: <ContenidoConHook /> });
      });
    } catch (e) {
      error = e;
    }
    expect(String(error)).toMatch(/No QueryClient/i);
  });

  it("el stack REAL de la app renderiza modales con hooks de query", async () => {
    render(
      <Providers>
        <div>app</div>
      </Providers>,
    );
    await act(async () => {
      modals.open({ title: "x", children: <ContenidoConHook />, ...SIN_TRANSICION });
    });
    expect(await screen.findByText("CONTENIDO MODAL")).toBeInTheDocument();
  });
});
