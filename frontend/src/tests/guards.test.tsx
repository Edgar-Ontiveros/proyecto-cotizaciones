/** Guard por rol: un vendedor navegando a /comprador termina en /vendedor. */

import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { describe, expect, it, vi } from "vitest";

import { RequireRol } from "../auth/guards";
import type { UsuarioMe } from "../lib/types";

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
        <Route element={<RequireRol roles={["comprador"]} />}>
          <Route path="/comprador" element={<div>PAGINA COMPRADOR</div>} />
        </Route>
      </Routes>
    </MemoryRouter>
  );
}

const vendedor: UsuarioMe = {
  id: 1,
  nombre: "Vendedora",
  email: "v@herinox.demo",
  rol: "vendedor",
  sucursal_id: 1,
  activo: true,
  must_change_password: false,
};

describe("RequireRol", () => {
  it("redirige al vendedor que intenta entrar a /comprador", () => {
    usuarioMock.actual = vendedor;
    render(<Arbol inicial="/comprador" />);
    expect(screen.getByText("PAGINA VENDEDOR")).toBeInTheDocument();
    expect(screen.queryByText("PAGINA COMPRADOR")).not.toBeInTheDocument();
  });

  it("deja pasar al rol correcto", () => {
    usuarioMock.actual = vendedor;
    render(<Arbol inicial="/vendedor" />);
    expect(screen.getByText("PAGINA VENDEDOR")).toBeInTheDocument();
  });

  it("sin sesión manda a login", () => {
    usuarioMock.actual = null;
    render(<Arbol inicial="/vendedor" />);
    expect(screen.getByText("PAGINA LOGIN")).toBeInTheDocument();
  });
});
