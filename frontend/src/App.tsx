import { Navigate, Route, Routes } from "react-router";

import { rutaPorRol, useAuth } from "./auth/AuthContext";
import { CambioPasswordPage } from "./auth/CambioPasswordPage";
import { RequireRol } from "./auth/guards";
import { LoginPage } from "./auth/LoginPage";
import { Layout } from "./components/Layout";
import { PlaceholderAdmin } from "./views/admin/Placeholder";
import { CapturaCotizacion } from "./views/comprador/CapturaCotizacion";
import { PanelComprador } from "./views/comprador/PanelComprador";
import { CapturaSolicitud } from "./views/vendedor/CapturaSolicitud";
import { Comparador } from "./views/vendedor/Comparador";
import { DetalleSolicitud } from "./views/vendedor/DetalleSolicitud";
import { ListadoVendedor } from "./views/vendedor/ListadoVendedor";

function HomePorRol() {
  const { usuario, cargando, mustChangePassword } = useAuth();
  if (cargando) return null;
  if (mustChangePassword) return <Navigate to="/cambiar-password" replace />;
  if (!usuario) return <Navigate to="/login" replace />;
  return <Navigate to={rutaPorRol(usuario.rol)} replace />;
}

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/cambiar-password" element={<CambioPasswordPage />} />
      <Route path="/" element={<HomePorRol />} />

      <Route element={<RequireRol roles={["vendedor"]} />}>
        <Route element={<Layout />}>
          <Route path="/vendedor" element={<ListadoVendedor />} />
          <Route path="/vendedor/nueva" element={<CapturaSolicitud modo="nueva" />} />
          <Route path="/vendedor/solicitudes/:id" element={<DetalleSolicitud />} />
          <Route path="/vendedor/solicitudes/:id/editar" element={<CapturaSolicitud modo="editar" />} />
          <Route path="/vendedor/solicitudes/:id/comparador" element={<Comparador />} />
        </Route>
      </Route>

      <Route element={<RequireRol roles={["comprador"]} />}>
        <Route element={<Layout />}>
          <Route path="/comprador" element={<PanelComprador />} />
          <Route path="/comprador/solicitudes/:id" element={<CapturaCotizacion />} />
        </Route>
      </Route>

      <Route element={<RequireRol roles={["admin", "gerente"]} />}>
        <Route element={<Layout />}>
          <Route path="/admin" element={<PlaceholderAdmin />} />
        </Route>
      </Route>

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
