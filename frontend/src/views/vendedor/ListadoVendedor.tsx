import { Autocomplete, Button, Group, Select, TextInput, Title } from "@mantine/core";
import { DatePickerInput } from "@mantine/dates";
import { useDebouncedValue } from "@mantine/hooks";
import dayjs from "dayjs";
import { DataTable } from "mantine-datatable";
import { useMemo, useState } from "react";
import { useNavigate } from "react-router";

import { useClientes, useSolicitudes } from "../../api/hooks";
import { BadgeEstado, Dinero, SemaforoBanda } from "../../components/compartidos";
import { fecha } from "../../lib/format";
import type { Moneda, SolicitudOut } from "../../lib/types";

const PAGE = 25;

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

/** Monto de la fila: confirmado si existe; si no, referencia (opción A) que el
 * backend expone vía monto_confirmado=null → se muestra "—". */
function montoDe(s: SolicitudOut): { monto: string | null; moneda: Moneda | null } {
  return { monto: s.monto_confirmado, moneda: s.moneda_confirmada };
}

export function ListadoVendedor() {
  const navigate = useNavigate();
  const [pagina, setPagina] = useState(1);
  const [estado, setEstado] = useState<string | null>(null);
  const [clienteTexto, setClienteTexto] = useState("");
  const [clienteId, setClienteId] = useState<number | undefined>();
  const [rango, setRango] = useState<[string | null, string | null]>([null, null]);
  const [buscar, setBuscar] = useState("");
  const [buscarDebounced] = useDebouncedValue(buscar, 300);

  const { data: clientes } = useClientes(clienteTexto);
  const { data, isFetching } = useSolicitudes({
    estado: estado ?? undefined,
    cliente_id: clienteId,
    desde: rango[0] ? dayjs(rango[0]).format("YYYY-MM-DD") : undefined,
    hasta: rango[1] ? dayjs(rango[1]).format("YYYY-MM-DD") : undefined,
    buscar: buscarDebounced || undefined,
    limit: PAGE,
    offset: (pagina - 1) * PAGE,
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
        <DatePickerInput
          type="range"
          placeholder="Rango de fechas"
          value={rango}
          onChange={(v) => {
            setRango(v);
            setPagina(1);
          }}
          clearable
          w={240}
        />
        <TextInput
          placeholder="Buscar folio o cliente"
          value={buscar}
          onChange={(e) => {
            setBuscar(e.currentTarget.value);
            setPagina(1);
          }}
          w={220}
        />
      </Group>
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
          { accessor: "folio", title: "Folio", render: (s) => s.folio ?? "(borrador)" },
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
            render: (s) => {
              const { monto, moneda } = montoDe(s);
              return <Dinero monto={monto} moneda={moneda} />;
            },
          },
        ]}
      />
    </>
  );
}
