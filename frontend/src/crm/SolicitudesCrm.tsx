/** Tabla GLOBAL de solicitudes del CRM (F8d): todos los filtros del backend +
 * export a Excel con los filtros ACTUALES. El alcance real lo pone el
 * backend (scoping por rol). */

import { Button, Group, Select, Title } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { DataTable } from "mantine-datatable";
import { useState } from "react";
import { useNavigate } from "react-router";

import { useSolicitudes } from "../api/hooks";
import { descargarExport, useFiltrosCatalogo } from "../api/crmHooks";
import { useAuth } from "../auth/AuthContext";
import { BadgeEstado, MontoSolicitud, SemaforoBanda } from "../components/compartidos";
import { FiltrosRangoBusqueda, PAGE, useFiltrosListado } from "../components/filtrosListado";
import { ApiError } from "../lib/api";
import { fecha } from "../lib/format";
import type { SolicitudOut } from "../lib/types";
import { opcionesSelect } from "./FiltrosDashboard";

const ESTADOS = [
  "BORRADOR",
  "ENVIADA",
  "EN_PROCESO",
  "COTIZADA",
  "CONFIRMADA",
  "NO_CONFIRMADA",
  "RECHAZADA",
  "CANCELADA",
];

export function SolicitudesCrm() {
  const navigate = useNavigate();
  const { usuario } = useAuth();
  const listado = useFiltrosListado();
  const { pagina, setPagina } = listado;
  const { data: catalogos } = useFiltrosCatalogo();
  const [estado, setEstado] = useState<string | null>(null);
  const [prioridad, setPrioridad] = useState<string | null>(null);
  const [sucursalId, setSucursalId] = useState<string | null>(null);
  const [compradorId, setCompradorId] = useState<string | null>(null);
  const [vendedorId, setVendedorId] = useState<string | null>(null);
  const [exportando, setExportando] = useState(false);

  const filtrosQuery = {
    estado: estado ?? undefined,
    prioridad: prioridad ?? undefined,
    sucursal_id: sucursalId !== null ? Number(sucursalId) : undefined,
    comprador_id: compradorId !== null ? Number(compradorId) : undefined,
    vendedor_id: vendedorId !== null ? Number(vendedorId) : undefined,
    ...listado.filtros,
  };
  const { data, isFetching } = useSolicitudes({
    ...filtrosQuery,
    limit: PAGE,
    offset: listado.offset,
  });

  const exportar = () => {
    setExportando(true);
    descargarExport(filtrosQuery)
      .catch((e: unknown) => {
        // El 422 de límite pide filtrar más — se muestra tal cual.
        notifications.show({
          message: e instanceof ApiError ? e.detail : "No se pudo exportar",
          color: e instanceof ApiError && e.status === 422 ? "yellow" : "red",
        });
      })
      .finally(() => setExportando(false));
  };

  const limpiarPagina = <T,>(setter: (v: T) => void) => {
    return (v: T) => {
      setter(v);
      setPagina(1);
    };
  };

  return (
    <>
      <Group justify="space-between" mb="md">
        <Title order={3}>Solicitudes</Title>
        <Group gap="sm">
          {usuario?.rol === "gerente_sucursal" && (
            // v3 (F8e): el gerente crea solicitudes — nacen con ÉL como
            // vendedor, en su sucursal.
            <Button color="acento.6" onClick={() => navigate("/crm/nueva")}>
              Nueva solicitud
            </Button>
          )}
          <Button variant="light" loading={exportando} onClick={exportar}>
            Exportar a Excel
          </Button>
        </Group>
      </Group>
      <Group mb={4} gap="sm">
        <Select
          placeholder="Estado"
          data={ESTADOS}
          value={estado}
          onChange={limpiarPagina(setEstado)}
          clearable
          w={150}
        />
        <Select
          placeholder="Prioridad"
          data={["NORMAL", "URGENTE"]}
          value={prioridad}
          onChange={limpiarPagina(setPrioridad)}
          clearable
          w={130}
        />
        <Select
          placeholder="Sucursal"
          data={opcionesSelect(catalogos?.sucursales)}
          value={sucursalId}
          onChange={limpiarPagina(setSucursalId)}
          clearable
          searchable
          w={180}
        />
        {catalogos?.compradores && (
          <Select
            placeholder="Comprador"
            data={opcionesSelect(catalogos.compradores)}
            value={compradorId}
            onChange={limpiarPagina(setCompradorId)}
            clearable
            searchable
            w={180}
          />
        )}
        {catalogos?.vendedores && (
          <Select
            placeholder="Vendedor"
            data={opcionesSelect(catalogos.vendedores)}
            value={vendedorId}
            onChange={limpiarPagina(setVendedorId)}
            clearable
            searchable
            w={180}
          />
        )}
      </Group>
      <FiltrosRangoBusqueda estado={listado} />
      <DataTable<SolicitudOut>
        withTableBorder
        highlightOnHover
        minHeight={200}
        records={data?.items ?? []}
        fetching={isFetching}
        totalRecords={data?.total ?? 0}
        recordsPerPage={PAGE}
        page={pagina}
        onPageChange={setPagina}
        onRowClick={({ record }) => navigate(`/crm/solicitudes/${record.id}`)}
        noRecordsText="Sin solicitudes"
        columns={[
          { accessor: "folio", title: "Folio", render: (s) => s.folio ?? "(borrador)" },
          { accessor: "cliente_nombre", title: "Cliente", render: (s) => s.cliente_nombre ?? "—" },
          { accessor: "creado_en", title: "Fecha", render: (s) => fecha(s.creado_en) },
          { accessor: "estado", title: "Estado", render: (s) => <BadgeEstado estado={s.estado} /> },
          {
            accessor: "banda",
            title: "Banda",
            render: (s) => (
              <SemaforoBanda
                banda={s.banda}
                horasHabiles={s.horas_habiles}
                dias={s.dias_transcurridos}
              />
            ),
          },
          {
            accessor: "prioridad",
            title: "Prioridad",
            render: (s) => (s.prioridad === "URGENTE" ? "URGENTE" : "Normal"),
          },
          { accessor: "monto", title: "Monto", render: (s) => <MontoSolicitud solicitud={s} /> },
        ]}
      />
    </>
  );
}
