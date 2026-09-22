/** F16a — pedidos en SAP: helpers puros (params, validación, badge, dónde) y
 * render por rol de la sección "Pedido en SAP" + el flujo del botón FINCADA
 * (sin OC abre el modal; fincada legado sin OC ofrece "Agregar OC"). */

import { MantineProvider } from "@mantine/core";
import { ModalsProvider } from "@mantine/modals";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen } from "@testing-library/react";
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

const usuarioMock = vi.hoisted(() => ({ actual: { id: 1, nombre: "Comprador", rol: "comprador" } }));
vi.mock("../auth/AuthContext", () => ({
  useAuth: () => ({ usuario: usuarioMock.actual }),
}));

import { SeccionFincada } from "../components/Pedido";
import { SeccionPedidoSap } from "../components/PedidoSap";
import {
  ETIQUETA_ESTATUS,
  administraOC,
  colorEstatus,
  dondeTexto,
  paramsPedidos,
  validarBusquedaOC,
} from "../lib/pedidos";
import type { EstatusOC, OCOut, SolicitudDetailOut } from "../lib/types";

function oc(sobre: Partial<OCOut> = {}): OCOut {
  return {
    id: 1,
    doc_num: 31000103,
    serie: "CH.",
    sucursal_sap: "CH",
    estatus_derivado: "FACTURADA",
    vencida: false,
    fecha_creacion: "2026-08-07",
    fecha_contabilizacion: "2026-08-07",
    fecha_entrega: "2026-08-17",
    donde_oc: "MATRIZ",
    donde_entrada: "MONTERREY CEDIS",
    ultimo_sync_en: "2026-09-22T18:00:00Z",
    ultimo_error: null,
    vinculada_por_nombre: "Michelle Monarrez",
    vinculada_en: "2026-09-22T18:00:00Z",
    lineas: [],
    entradas: [{ doc_num: 41000196, fecha: "2026-08-12", cancelada: false, donde: ["MONTERREY CEDIS"], cantidad_total: "7" }],
    facturas: [{ doc_num: 41000250, fecha: "2026-08-12", cancelada: false, ligada_a: "entrada" }],
    ...sobre,
  };
}

function solicitud(sobre: Partial<SolicitudDetailOut> = {}): SolicitudDetailOut {
  return {
    id: 5,
    folio: "MTZ-1",
    estado: "CONFIRMADA",
    fincada: false,
    fincada_por: null,
    fincada_en: null,
    fincada_por_nombre: null,
    sucursal_serie_sap: "CH",
    ocs: [],
    ...sobre,
  } as unknown as SolicitudDetailOut;
}

// Mismo orden que Providers (regresión F8e p.0): QueryClientProvider POR
// ENCIMA de ModalsProvider, porque el modal usa hooks de TanStack Query.
function pintar(ui: React.ReactElement) {
  return render(
    <MantineProvider>
      <QueryClientProvider client={new QueryClient()}>
        <ModalsProvider modalProps={{ transitionProps: { duration: 0 } }}>{ui}</ModalsProvider>
      </QueryClientProvider>
    </MantineProvider>,
  );
}

describe("helpers de pedidos (F16a)", () => {
  it("paramsPedidos manda solo lo elegido y pagina con offset", () => {
    expect(paramsPedidos({ soloVencidas: false, pagina: 1, porPagina: 25 })).toEqual({
      estatus: undefined,
      vencidas: undefined,
      sucursal_id: undefined,
      limit: 25,
      offset: 0,
    });
    expect(
      paramsPedidos({ estatus: "ABIERTA", soloVencidas: true, sucursalId: 3, pagina: 3, porPagina: 25 }),
    ).toEqual({ estatus: "ABIERTA", vencidas: true, sucursal_id: 3, limit: 25, offset: 50 });
  });

  it("validarBusquedaOC exige entero > 0 y normaliza la serie (sin punto, mayúsculas)", () => {
    expect(validarBusquedaOC("31000103", "ch.")).toEqual({ doc_num: 31000103, sucursal_sap: "CH" });
    expect(validarBusquedaOC("abc", "CH")).toHaveProperty("error");
    expect(validarBusquedaOC("0", "CH")).toHaveProperty("error");
    expect(validarBusquedaOC("12", "  ")).toHaveProperty("error");
  });

  it("todo estatus tiene etiqueta y color; solo compras administra OC", () => {
    const todos: EstatusOC[] = ["ABIERTA", "PARCIALMENTE_RECIBIDA", "RECIBIDA", "FACTURADA", "CERRADA_SIN_RECIBIR", "CANCELADA"];
    for (const e of todos) {
      expect(ETIQUETA_ESTATUS[e]).toBeTruthy();
      expect(colorEstatus(e)).toBeTruthy();
    }
    expect(colorEstatus("CANCELADA")).toBe("red");
    expect(["comprador", "gerente_compras", "admin"].every(administraOC)).toBe(true);
    expect(["vendedor", "gerente_sucursal", "director_ventas"].some(administraOC)).toBe(false);
  });

  it("dondeTexto combina OC y entrada", () => {
    expect(dondeTexto({ donde_oc: "MATRIZ", donde_entrada: "MONTERREY CEDIS" })).toBe(
      "OC: MATRIZ · entró en: MONTERREY CEDIS",
    );
    expect(dondeTexto({ donde_oc: "MATRIZ" })).toBe("OC: MATRIZ");
    expect(dondeTexto({ donde_oc: null, donde_entrada: null })).toBe("—");
  });
});

describe("sección Pedido en SAP por rol", () => {
  it("compras ve proveedor/monto y las acciones; el JSON de ventas no trae esas claves y no se pintan", () => {
    usuarioMock.actual = { id: 1, nombre: "Comprador", rol: "comprador" };
    const compras = oc({ proveedor: "ORGANIZACIÓN EN VÁLVULAS. S.A. DE C.V.", total: "26.10", moneda: "USD", tipo_cambio: "17.2317" });
    pintar(<SeccionPedidoSap solicitud={solicitud({ ocs: [compras] })} />);
    expect(screen.getByText(/ORGANIZACIÓN EN VÁLVULAS/)).toBeInTheDocument();
    expect(screen.getByText(/US\$ 26\.10/)).toBeInTheDocument();
    expect(screen.getByText("Actualizar desde SAP")).toBeInTheDocument();
    expect(screen.getByText("Agregar OC")).toBeInTheDocument();
    expect(screen.getByText("Desvincular")).toBeInTheDocument();
    expect(screen.getByText("Facturada")).toBeInTheDocument();
  });

  it("el vendedor ve la card con cadena y sin acciones ni dinero", () => {
    usuarioMock.actual = { id: 2, nombre: "Vendedor", rol: "vendedor" };
    pintar(<SeccionPedidoSap solicitud={solicitud({ ocs: [oc()] })} />);
    expect(screen.getByText(/OC 31000103/)).toBeInTheDocument();
    expect(screen.getByText(/41000196/)).toBeInTheDocument();
    expect(screen.getByText(/41000250/)).toBeInTheDocument();
    expect(screen.queryByText("Actualizar desde SAP")).not.toBeInTheDocument();
    expect(screen.queryByText("Desvincular")).not.toBeInTheDocument();
    expect(screen.queryByText(/US\$/)).not.toBeInTheDocument();
  });

  it("sin OC y sin permisos de compras la sección no se monta", () => {
    usuarioMock.actual = { id: 2, nombre: "Vendedor", rol: "vendedor" };
    pintar(<SeccionPedidoSap solicitud={solicitud()} />);
    expect(screen.queryByTestId("seccion-pedido-sap")).not.toBeInTheDocument();
  });

  it("VENCIDA se marca en rojo", () => {
    usuarioMock.actual = { id: 1, nombre: "Comprador", rol: "comprador" };
    pintar(<SeccionPedidoSap solicitud={solicitud({ ocs: [oc({ estatus_derivado: "ABIERTA", vencida: true })] })} />);
    expect(screen.getByText("VENCIDA")).toBeInTheDocument();
  });
});

describe("fincar exige OC (F16a §4)", () => {
  it("sin OC, 'Marcar como FINCADA' abre el modal Buscar → Vincular → Fincar", async () => {
    usuarioMock.actual = { id: 1, nombre: "Comprador", rol: "comprador" };
    pintar(<SeccionFincada solicitud={solicitud()} />);
    await act(async () => {
      screen.getByText("Marcar como FINCADA").click();
    });
    expect(await screen.findByText(/vincula su orden de compra/)).toBeInTheDocument();
    expect(screen.getByLabelText("Número de OC")).toBeInTheDocument();
    // La sucursal SAP viene precargada con la serie de la sucursal de la solicitud.
    expect(screen.getByLabelText("Sucursal SAP")).toHaveValue("CH");
    expect(screen.getByRole("button", { name: "Fincar" })).toBeDisabled(); // sin OC no se finca
  });

  it("fincada legado sin OC sigue válida y ofrece 'Agregar OC'", () => {
    usuarioMock.actual = { id: 1, nombre: "Comprador", rol: "comprador" };
    pintar(<SeccionFincada solicitud={solicitud({ fincada: true, fincada_por_nombre: "X", fincada_en: "2026-08-01T00:00:00Z" })} />);
    expect(screen.getByText("FINCADA")).toBeInTheDocument();
    expect(screen.getByText(/Sin OC vinculada/)).toBeInTheDocument();
    expect(screen.getByTestId("boton-agregar-oc")).toBeInTheDocument();
  });
});
