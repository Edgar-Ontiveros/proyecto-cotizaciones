/** F12 — fincado (p.5) y eliminación definitiva (p.4) del lado frontend:
 * quién ve la sección FINCADA, el candado del modal de eliminación (folio mal
 * tecleado NO habilita) y el estilo teal de las filas fincadas. */

import { MantineProvider } from "@mantine/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

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

const usuarioMock: { actual: { rol: string } | null } = { actual: null };

vi.mock("../auth/AuthContext", async (importOriginal) => {
  const original = await importOriginal<typeof import("../auth/AuthContext")>();
  return {
    ...original,
    useAuth: () => ({
      usuario: usuarioMock.actual,
      cargando: false,
      mustChangePassword: false,
      login: vi.fn(),
      cambiarPassword: vi.fn(),
      logout: vi.fn(),
    }),
  };
});

import { SeccionFincada } from "../components/Pedido";
import { estiloFilaFincada } from "../components/compartidos";
import { habilitaEliminar } from "../lib/crm";
import type { SolicitudDetailOut } from "../lib/types";

function solicitud(sobre: Partial<SolicitudDetailOut>): SolicitudDetailOut {
  return {
    id: 5,
    folio: "CCN-3036",
    estado: "CONFIRMADA",
    fincada: false,
    fincada_por: null,
    fincada_en: null,
    fincada_por_nombre: null,
    ...sobre,
  } as unknown as SolicitudDetailOut;
}

function pintar(s: SolicitudDetailOut) {
  return render(
    <MantineProvider>
      <QueryClientProvider client={new QueryClient()}>
        <SeccionFincada solicitud={s} />
      </QueryClientProvider>
    </MantineProvider>,
  );
}

describe("SeccionFincada — visibilidad por rol (F12 p.5)", () => {
  it("comprador, gerente_compras y admin la ven en CONFIRMADA", () => {
    for (const rol of ["comprador", "gerente_compras", "admin"]) {
      usuarioMock.actual = { rol };
      const { unmount } = render(
        <MantineProvider>
          <QueryClientProvider client={new QueryClient()}>
            <SeccionFincada solicitud={solicitud({})} />
          </QueryClientProvider>
        </MantineProvider>,
      );
      expect(screen.getByText("Marcar como FINCADA")).toBeInTheDocument();
      unmount();
    }
  });

  it("el lado ventas NO la renderiza aunque la clave viniera", () => {
    for (const rol of ["vendedor", "gerente_sucursal", "director_ventas"]) {
      usuarioMock.actual = { rol };
      const { unmount } = pintar(solicitud({}));
      expect(screen.queryByTestId("seccion-fincada")).not.toBeInTheDocument();
      unmount();
    }
  });

  it("sin la clave fincada en el JSON (ventas) no se monta ni para admin", () => {
    usuarioMock.actual = { rol: "admin" };
    pintar(solicitud({ fincada: undefined }));
    expect(screen.queryByTestId("seccion-fincada")).not.toBeInTheDocument();
  });

  it("fuera de CONFIRMADA no se monta", () => {
    usuarioMock.actual = { rol: "comprador" };
    pintar(solicitud({ estado: "COTIZADA" }));
    expect(screen.queryByTestId("seccion-fincada")).not.toBeInTheDocument();
  });

  it("fincada muestra el badge y el rótulo 'Fincada por X el …'", () => {
    usuarioMock.actual = { rol: "gerente_compras" };
    pintar(
      solicitud({
        fincada: true,
        fincada_por: 7,
        fincada_en: "2026-08-17T18:00:00Z",
        fincada_por_nombre: "Heidy Ruelas",
      }),
    );
    expect(screen.getByText("FINCADA")).toBeInTheDocument();
    expect(screen.getByText(/Fincada por Heidy Ruelas el/)).toBeInTheDocument();
    expect(screen.getByText("Quitar FINCADA")).toBeInTheDocument();
  });
});

describe("habilitaEliminar — el candado del modal (F12 p.4)", () => {
  const objetivo = { folio: "CCN-3036", id: 5 };
  const motivo = "Duplicado creado por error";

  it("folio exacto + motivo con sustancia habilita", () => {
    expect(habilitaEliminar("CCN-3036", motivo, objetivo)).toBe(true);
    expect(habilitaEliminar("  CCN-3036  ", motivo, objetivo)).toBe(true);
  });

  it("folio mal tecleado NO habilita", () => {
    expect(habilitaEliminar("CCN-3037", motivo, objetivo)).toBe(false);
    expect(habilitaEliminar("ccn-3036", motivo, objetivo)).toBe(false);
    expect(habilitaEliminar("", motivo, objetivo)).toBe(false);
  });

  it("motivo corto NO habilita", () => {
    expect(habilitaEliminar("CCN-3036", "corto", objetivo)).toBe(false);
    expect(habilitaEliminar("CCN-3036", "         x", objetivo)).toBe(false);
  });

  it("un borrador sin folio exige teclear #id", () => {
    expect(habilitaEliminar("#5", motivo, { folio: null, id: 5 })).toBe(true);
    expect(habilitaEliminar("5", motivo, { folio: null, id: 5 })).toBe(false);
  });
});

describe("estiloFilaFincada — teal fino solo en fincadas", () => {
  it("fincada pinta teal; sin fincar o sin clave (ventas) queda normal", () => {
    expect(estiloFilaFincada({ fincada: true })?.backgroundColor).toContain("teal");
    expect(estiloFilaFincada({ fincada: false })).toBeUndefined();
    expect(estiloFilaFincada({})).toBeUndefined();
  });
});
