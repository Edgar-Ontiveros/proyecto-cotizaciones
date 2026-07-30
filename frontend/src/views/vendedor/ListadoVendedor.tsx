import { Autocomplete, Button, Group, Select, Title } from "@mantine/core";
import { DataTable } from "mantine-datatable";
import { useMemo, useState } from "react";
import { useNavigate } from "react-router";

import { useClientes, useSolicitudes } from "../../api/hooks";
import {
  BadgeEstado,
  FolioConProyecto,
  MontoSolicitud,
  SemaforoBanda,
} from "../../components/compartidos";
import { FiltrosRangoBusqueda, PAGE, useFiltrosListado } from "../../components/filtrosListado";
import { fecha } from "../../lib/format";
import type { SolicitudOut } from "../../lib/types";

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

export function ListadoVendedor() {
  const navigate = useNavigate();
  const listado = useFiltrosListado();
  const { pagina, setPagina } = listado;
  const [estado, setEstado] = useState<string | null>(null);
  const [tipo, setTipo] = useState<string | null>(null);
  const [clienteTexto, setClienteTexto] = useState("");
  const [clienteId, setClienteId] = useState<number | undefined>();

  const { data: clientes } = useClientes(clienteTexto);
  const { data, isFetching } = useSolicitudes({
    estado: estado ?? undefined,
    es_proyecto: tipo !== null ? tipo === "PROYECTO" : undefined,
    cliente_id: clienteId,
    ...listado.filtros,
    limit: PAGE,
    offset: listado.offset,
  });

  const opcionesCliente = useMemo(
    () => (clientes ?? []).map((c) => c.nombre_normalizado),
    [clientes],
  );

  return (
    <>
      <Group justify="space-between" mb="md">
        <Title order={3}>Mis solicitudes</Title>
        <Button color="acento.6" onClick={() => navigate("/vendedor/nueva")}>
          Nueva solicitud
        </Button>
      </Group>
      <Group mb="sm" gap="sm">
        <Select
          placeholder="Estado"
          data={ESTADOS}
          value={estado}
          onChange={(v) => {
            setEstado(v);
            setPagina(1);
          }}
          clearable
          w={160}
        />
        <Select
          placeholder="Tipo"
          data={[
            { value: "PROYECTO", label: "Proyectos" },
            { value: "NORMAL", label: "Normales" },
          ]}
          value={tipo}
          onChange={(v) => {
            setTipo(v);
            setPagina(1);
          }}
          clearable
          w={140}
        />
        <Autocomplete
          placeholder="Cliente"
          data={opcionesCliente}
          value={clienteTexto}
          onChange={(v) => {
            setClienteTexto(v);
            const encontrado = (clientes ?? []).find((c) => c.nombre_normalizado === v);
            setClienteId(encontrado?.id);
            setPagina(1);
          }}
          w={220}
        />
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
        onRowClick={({ record }) => navigate(`/vendedor/solicitudes/${record.id}`)}
        noRecordsText="Sin solicitudes"
        columns={[
          { accessor: "folio", title: "Folio", render: (s) => <FolioConProyecto solicitud={s} /> },
          { accessor: "cliente_nombre", title: "Cliente", render: (s) => s.cliente_nombre ?? "—" },
          { accessor: "creado_en", title: "Fecha", render: (s) => fecha(s.creado_en) },
          { accessor: "estado", title: "Estado", render: (s) => <BadgeEstado estado={s.estado} /> },
          {
            accessor: "banda",
            title: "Banda",
            render: (s) => (
              <SemaforoBanda banda={s.banda} horasHabiles={s.horas_habiles} dias={s.dias_transcurridos} />
            ),
          },
          {
            accessor: "prioridad",
            title: "Prioridad",
            render: (s) => (s.prioridad === "URGENTE" ? "URGENTE" : "Normal"),
          },
          {
            accessor: "monto",
            title: "Monto",
            render: (s) => <MontoSolicitud solicitud={s} />,
          },
        ]}
      />
    </>
  );
}
