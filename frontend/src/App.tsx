import { lazy } from "react";
import { Navigate, Route, Routes } from "react-router";

import { rutaPorRol, useAuth } from "./auth/AuthContext";
import { CambioPasswordPage } from "./auth/CambioPasswordPage";
import { RequireRol } from "./auth/guards";
import { LoginPage } from "./auth/LoginPage";
import { Layout } from "./components/Layout";
import { NoEncontrada } from "./components/NoEncontrada";
import { CrmLayout } from "./crm/CrmLayout";
import { ROLES_CRM } from "./crm/menu";
import { CapturaCotizacion } from "./views/comprador/CapturaCotizacion";
import { PanelComprador } from "./views/comprador/PanelComprador";
import { CapturaSolicitud } from "./views/vendedor/CapturaSolicitud";
import { Comparador } from "./views/vendedor/Comparador";
import { DetalleSolicitud } from "./views/vendedor/DetalleSolicitud";
import { ListadoVendedor } from "./views/vendedor/ListadoVendedor";

// Code-splitting (F9-prep): las secciones del CRM (incluido recharts, que
// solo usa el dashboard) se cargan bajo demanda. El Suspense vive en
// CrmLayout, alrededor del Outlet.
const Dashboard = lazy(() => import("./crm/Dashboard").then((m) => ({ default: m.Dashboard })));
const Comparativas = lazy(() =>
  import("./crm/Comparativas").then((m) => ({ default: m.Comparativas })),
);
const SolicitudesCrm = lazy(() =>
  import("./crm/SolicitudesCrm").then((m) => ({ default: m.SolicitudesCrm })),
);
const DetalleCrm = lazy(() => import("./crm/DetalleCrm").then((m) => ({ default: m.DetalleCrm })));
const UsuariosCrm = lazy(() =>
  import("./crm/admin/UsuariosCrm").then((m) => ({ default: m.UsuariosCrm })),
);
const SucursalesCrm = lazy(() =>
  import("./crm/admin/SucursalesCrm").then((m) => ({ default: m.SucursalesCrm })),
);
const TerritoriosCrm = lazy(() =>
  import("./crm/admin/TerritoriosCrm").then((m) => ({ default: m.TerritoriosCrm })),
);
const MasivasCrm = lazy(() =>
  import("./crm/admin/MasivasCrm").then((m) => ({ default: m.MasivasCrm })),
);
const CatalogosCrm = lazy(() =>
  import("./crm/admin/CatalogosCrm").then((m) => ({ default: m.CatalogosCrm })),
);

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

      <Route element={<RequireRol roles={ROLES_CRM} />}>
        <Route element={<CrmLayout />}>
          <Route path="/crm" element={<Dashboard />} />
          <Route path="/crm/comparativas" element={<Comparativas />} />
          <Route path="/crm/solicitudes" element={<SolicitudesCrm />} />
          <Route path="/crm/nueva" element={<CapturaSolicitud modo="nueva" />} />
          <Route path="/crm/solicitudes/:id" element={<DetalleCrm />} />
          <Route path="/crm/solicitudes/:id/editar" element={<CapturaSolicitud modo="editar" />} />
          <Route path="/crm/solicitudes/:id/comparador" element={<Comparador />} />
          <Route path="/crm/solicitudes/:id/capturar" element={<CapturaCotizacion />} />
          <Route path="/crm/usuarios" element={<UsuariosCrm />} />
          <Route path="/crm/sucursales" element={<SucursalesCrm />} />
          <Route path="/crm/territorios" element={<TerritoriosCrm />} />
          <Route path="/crm/reasignaciones" element={<MasivasCrm />} />
          <Route path="/crm/catalogos" element={<CatalogosCrm />} />
        </Route>
      </Route>

      {/* /admin era el placeholder pre-F8d: redirige al CRM. */}
      <Route path="/admin" element={<Navigate to="/crm" replace />} />
      <Route path="*" element={<NoEncontrada />} />
    </Routes>
  );
}
