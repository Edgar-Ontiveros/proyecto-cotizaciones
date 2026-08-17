/** F8d: mapa menú-por-rol, parseo del 409 de baja segura, armado de query de
 * filtros del dashboard y guard de /crm. */

import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { describe, expect, it, vi } from "vitest";

import { RequireRol } from "../auth/guards";
import {
  COMPARATIVAS_POR_ROL,
  MENU_CRM,
  ROLES_CRM,
  SECCIONES_POR_ROL,
  menuDe,
} from "../crm/menu";
import {
  ROLES_GESTIONABLES,
  accionesDetalleCrm,
  baseSolicitudes,
  parseBajaSegura,
  queryFiltrosDashboard,
} from "../lib/crm";
import type { UsuarioMe } from "../lib/types";

describe("mapa del menú por rol", () => {
  it("todo rol CRM tiene secciones y todas existen en MENU_CRM", () => {
    const secciones = MENU_CRM.map((i) => i.seccion);
    for (const rol of ROLES_CRM) {
      expect(SECCIONES_POR_ROL[rol].length).toBeGreaterThan(0);
      for (const s of SECCIONES_POR_ROL[rol]) expect(secciones).toContain(s);
    }
  });

  it("admin ve TODO; los demás no", () => {
    expect(menuDe("admin")).toHaveLength(MENU_CRM.length);
    expect(menuDe("director_ventas").length).toBeLessThan(MENU_CRM.length);
  });

  it("director_ventas sin nada de compras; gerente_compras sin ventas-personal", () => {
    expect(SECCIONES_POR_ROL.director_ventas).not.toContain("territorios");
    expect(COMPARATIVAS_POR_ROL.director_ventas).not.toContain("por-comprador");
    expect(COMPARATIVAS_POR_ROL.director_ventas).not.toContain("no-encontrados");
    expect(COMPARATIVAS_POR_ROL.gerente_compras).not.toContain("por-vendedor");
    // Sucursales y catálogos: SOLO admin.
    for (const rol of ["director_ventas", "gerente_compras", "gerente_sucursal"] as const) {
      expect(SECCIONES_POR_ROL[rol]).not.toContain("sucursales");
      expect(SECCIONES_POR_ROL[rol]).not.toContain("catalogos");
    }
    // gerente_sucursal: su mini-mundo (por-vendedor y por-cliente).
    expect(COMPARATIVAS_POR_ROL.gerente_sucursal).toEqual(["por-vendedor", "por-cliente"]);
  });

  it("ROLES_GESTIONABLES espeja la matriz del backend", () => {
    expect(ROLES_GESTIONABLES["gerente_compras"]).toEqual(["comprador"]);
    expect(ROLES_GESTIONABLES["gerente_sucursal"]).toEqual(["vendedor"]);
    expect(ROLES_GESTIONABLES["director_ventas"]).toEqual(["vendedor", "gerente_sucursal"]);
    expect(ROLES_GESTIONABLES["admin"]).toContain("admin");
  });
});

describe("mapa de acciones del detalle CRM", () => {
  it("cada rol ve exactamente sus botones (F12: eliminar SOLO admin)", () => {
    expect(accionesDetalleCrm("admin")).toEqual({
      capturar: true,
      reasignarComprador: true,
      reasignarVendedor: true,
      corregirTC: true,
      eliminar: true,
    });
    expect(accionesDetalleCrm("gerente_compras")).toEqual({
      capturar: true,
      reasignarComprador: true,
      reasignarVendedor: false,
      corregirTC: false,
      eliminar: false,
    });
    expect(accionesDetalleCrm("gerente_sucursal")).toEqual({
      capturar: false,
      reasignarComprador: false,
      reasignarVendedor: true,
      corregirTC: false,
      eliminar: false,
    });
    expect(accionesDetalleCrm("director_ventas")).toEqual({
      capturar: false,
      reasignarComprador: false,
      reasignarVendedor: true, // F9-prep: nuevo — el backend lo permite desde F5
      corregirTC: false,
      eliminar: false,
    });
  });
});

describe("parseBajaSegura", () => {
  it("comprador con titularidades y abiertas pide ambos destinos", () => {
    const detail =
      "No se puede desactivar al comprador sin reasignar: es titular de: Cd. Juárez " +
      "(envía titularidades_a); tiene 3 solicitud(es) abiertas (envía solicitudes_a)";
    expect(parseBajaSegura(detail)).toEqual({
      requiereTitularidades: true,
      requiereSolicitudes: true,
    });
  });

  it("vendedor solo pide solicitudes_a", () => {
    const detail =
      "No se puede desactivar al vendedor: tiene 2 solicitud(es) no terminales " +
      "(envía solicitudes_a)";
    expect(parseBajaSegura(detail)).toEqual({
      requiereTitularidades: false,
      requiereSolicitudes: true,
    });
  });
});

describe("queryFiltrosDashboard", () => {
  it("preset mes = del 1° del mes a hoy", () => {
    expect(queryFiltrosDashboard({ preset: "mes" }, "2026-07-28")).toMatchObject({
      desde: "2026-07-01",
      hasta: "2026-07-28",
    });
  });

  it("preset 30d y trimestre", () => {
    expect(queryFiltrosDashboard({ preset: "30d" }, "2026-07-28").desde).toBe("2026-06-28");
    expect(queryFiltrosDashboard({ preset: "trimestre" }, "2026-07-28").desde).toBe("2026-07-01");
    expect(queryFiltrosDashboard({ preset: "trimestre" }, "2026-09-15").desde).toBe("2026-07-01");
  });

  it("propaga los ids seleccionados", () => {
    const q = queryFiltrosDashboard({ preset: "mes", sucursal_id: 3, comprador_id: 7 }, "2026-07-28");
    expect(q.sucursal_id).toBe(3);
    expect(q.comprador_id).toBe(7);
    expect(q.vendedor_id).toBeUndefined();
  });
});

describe("baseSolicitudes", () => {
  it("distingue crm / comprador / vendedor", () => {
    expect(baseSolicitudes("/crm/solicitudes/5")).toBe("/crm");
    expect(baseSolicitudes("/comprador/solicitudes/5")).toBe("/comprador");
    expect(baseSolicitudes("/vendedor/solicitudes/5")).toBe("/vendedor");
  });
});

// ------------------------------------------------------------- guard de /crm

const usuarioMock: { actual: UsuarioMe | null } = { actual: null };

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

function Arbol({ inicial }: { inicial: string }) {
  return (
    <MemoryRouter initialEntries={[inicial]}>
      <Routes>
        <Route path="/login" element={<div>PAGINA LOGIN</div>} />
        <Route element={<RequireRol roles={["vendedor"]} />}>
          <Route path="/vendedor" element={<div>PAGINA VENDEDOR</div>} />
        </Route>
        <Route element={<RequireRol roles={ROLES_CRM} />}>
          <Route path="/crm" element={<div>PAGINA CRM</div>} />
        </Route>
      </Routes>
    </MemoryRouter>
  );
}

const base: Omit<UsuarioMe, "rol"> = {
  id: 9,
  nombre: "Gestora",
  email: "g@herinox.demo",
  sucursal_id: null,
  activo: true,
  must_change_password: false,
};

describe("guard de /crm", () => {
  it("deja pasar a los 4 roles CRM", () => {
    for (const rol of ROLES_CRM) {
      usuarioMock.actual = { ...base, rol };
      const { unmount } = render(<Arbol inicial="/crm" />);
      expect(screen.getByText("PAGINA CRM")).toBeInTheDocument();
      unmount();
    }
  });

  it("un vendedor que intenta /crm regresa a su home", () => {
    usuarioMock.actual = { ...base, rol: "vendedor", sucursal_id: 1 };
    render(<Arbol inicial="/crm" />);
    expect(screen.getByText("PAGINA VENDEDOR")).toBeInTheDocument();
  });
});
