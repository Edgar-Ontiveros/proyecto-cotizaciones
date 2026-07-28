/** Vista principal del comprador: MI PANEL (los números con los que lo
 * evalúan) arriba y su COLA abajo (urgentes primero, luego T descendente). */

import {
  Alert,
  Badge,
  Card,
  Group,
  SimpleGrid,
  Stack,
  Tabs,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { DatePickerInput } from "@mantine/dates";
import { useDebouncedValue } from "@mantine/hooks";
import dayjs from "dayjs";
import { DataTable } from "mantine-datatable";
import { useMemo, useState } from "react";
import { useNavigate } from "react-router";

import { useMiPanel, useSolicitudes } from "../../api/hooks";
import { BadgeEstado, MontoSolicitud, SemaforoBanda } from "../../components/compartidos";
import { fecha, horas, pct } from "../../lib/format";
import type { SolicitudOut } from "../../lib/types";

function Indicador({ titulo, valor }: { titulo: string; valor: string }) {
  return (
    <Card withBorder p="sm">
      <Text size="xs" c="dimmed">
        {titulo}
      </Text>
      <Text size="xl" fw={700}>
        {valor}
      </Text>
    </Card>
  );
}

function MiPanel() {
  const { data } = useMiPanel(true);
  if (!data) return null;
  const dist = data.distribucion_bandas;
  return (
    <Stack gap="xs">
      <Title order={4}>Mi panel · {data.mes}</Title>
      <SimpleGrid cols={{ base: 2, md: 5 }}>
        <Indicador titulo="Ciclos cerrados" valor={String(data.ciclos_cerrados)} />
        <Indicador titulo="Mediana (h hábiles)" valor={horas(data.mediana_horas_habiles)} />
        <Indicador titulo="% banda esperada" valor={pct(data.pct_banda_esperada)} />
        <Indicador titulo="Carga abierta" valor={String(data.carga_abierta)} />
        <Card withBorder p="sm">
          <Text size="xs" c="dimmed">
            Distribución
          </Text>
          <Group gap={6} mt={4}>
            <Badge color="green" variant="light">
              {dist["ESPERADA"] ?? 0}
            </Badge>
            <Badge color="yellow" variant="light">
              {dist["NORMAL"] ?? 0}
            </Badge>
            <Badge color="red" variant="light">
              {dist["LENTA"] ?? 0}
            </Badge>
          </Group>
        </Card>
      </SimpleGrid>
      {data.rojas.length > 0 && (
        <Alert color="red" title={`Tienes ${data.rojas.length} solicitud(es) en rojo`}>
          {data.rojas.map((r) => (
            <Text key={r.solicitud_id} size="sm">
              {r.folio ?? `#${r.solicitud_id}`} · día {r.dias_transcurridos} (
              {r.horas_habiles.toFixed(1)} h hábiles)
            </Text>
          ))}
        </Alert>
      )}
    </Stack>
  );
}

const PAGE = 25;

function FiltrosTabla({
  rango,
  setRango,
  buscar,
  setBuscar,
}: {
  rango: [string | null, string | null];
  setRango: (v: [string | null, string | null]) => void;
  buscar: string;
  setBuscar: (v: string) => void;
}) {
  return (
    <Group mb="sm" gap="sm">
      <DatePickerInput
        type="range"
        placeholder="Rango de fechas"
        value={rango}
        onChange={setRango}
        clearable
        w={240}
      />
      <TextInput
        placeholder="Buscar folio o cliente"
        value={buscar}
        onChange={(e) => setBuscar(e.currentTarget.value)}
        w={220}
      />
    </Group>
  );
}

export function PanelComprador() {
  const navigate = useNavigate();
  const [tab, setTab] = useState<string | null>("cola");
  const [pagina, setPagina] = useState(1);
  // Fix 2b (F8c): rango de fechas + buscar para Cotizadas y Todas.
  const [rango, setRango] = useState<[string | null, string | null]>([null, null]);
  const [buscar, setBuscar] = useState("");
  const [buscarDebounced] = useDebouncedValue(buscar, 300);
  const filtros = {
    desde: rango[0] ? dayjs(rango[0]).format("YYYY-MM-DD") : undefined,
    hasta: rango[1] ? dayjs(rango[1]).format("YYYY-MM-DD") : undefined,
    buscar: buscarDebounced || undefined,
  };

  // Cola: hasta 100 abiertas de cada estado, orden en cliente.
  const enviadas = useSolicitudes({ estado: "ENVIADA", limit: 100 });
  const enProceso = useSolicitudes({ estado: "EN_PROCESO", limit: 100 });
  const cotizadas = useSolicitudes({
    estado: "COTIZADA",
    ...filtros,
    limit: PAGE,
    offset: (pagina - 1) * PAGE,
  });
  const todas = useSolicitudes({ ...filtros, limit: PAGE, offset: (pagina - 1) * PAGE });

  const cola = useMemo(() => {
    const items = [...(enviadas.data?.items ?? []), ...(enProceso.data?.items ?? [])];
    // URGENTE primero; luego T (días transcurridos) descendente.
    return items.sort((a, b) => {
      if (a.prioridad !== b.prioridad) return a.prioridad === "URGENTE" ? -1 : 1;
      return (b.dias_transcurridos ?? 0) - (a.dias_transcurridos ?? 0);
    });
  }, [enviadas.data, enProceso.data]);

  const colaExcedida =
    (enviadas.data?.total ?? 0) > 100 || (enProceso.data?.total ?? 0) > 100;

  const columnas = [
    {
      accessor: "folio",
      title: "Folio",
      render: (s: SolicitudOut) => s.folio ?? "—",
    },
    {
      accessor: "cliente_nombre",
      title: "Cliente",
      render: (s: SolicitudOut) => s.cliente_nombre ?? "—",
    },
    { accessor: "creado_en", title: "Fecha", render: (s: SolicitudOut) => fecha(s.creado_en) },
    {
      accessor: "estado",
      title: "Estado",
      render: (s: SolicitudOut) => <BadgeEstado estado={s.estado} />,
    },
    {
      accessor: "banda",
      title: "Semáforo",
      render: (s: SolicitudOut) => (
        <SemaforoBanda banda={s.banda} horasHabiles={s.horas_habiles} dias={s.dias_transcurridos} />
      ),
    },
    {
      accessor: "prioridad",
      title: "Prioridad",
      render: (s: SolicitudOut) =>
        s.prioridad === "URGENTE" ? (
          <Badge color="acento.6" variant="filled">
            URGENTE
          </Badge>
        ) : (
          "Normal"
        ),
    },
    {
      accessor: "monto",
      title: "Monto",
      render: (s: SolicitudOut) => <MontoSolicitud solicitud={s} />,
    },
  ];

  return (
    <Stack>
      <MiPanel />
      <Tabs value={tab} onChange={(v) => { setTab(v); setPagina(1); }}>
        <Tabs.List>
          <Tabs.Tab value="cola">Cola ({cola.length})</Tabs.Tab>
          <Tabs.Tab value="cotizadas">Cotizadas</Tabs.Tab>
          <Tabs.Tab value="todas">Todas</Tabs.Tab>
        </Tabs.List>
        <Tabs.Panel value="cola" pt="sm">
          {colaExcedida && (
            <Alert color="yellow" mb="sm">
              Hay más de 100 solicitudes abiertas: la cola muestra las primeras 100 por estado.
            </Alert>
          )}
          <DataTable<SolicitudOut>
            withTableBorder
            highlightOnHover
            minHeight={180}
            records={cola}
            fetching={enviadas.isFetching || enProceso.isFetching}
            onRowClick={({ record }) => navigate(`/comprador/solicitudes/${record.id}`)}
            noRecordsText="Sin pendientes — cola limpia"
            columns={columnas}
          />
        </Tabs.Panel>
        <Tabs.Panel value="cotizadas" pt="sm">
          <FiltrosTabla
            rango={rango}
            setRango={(v) => {
              setRango(v);
              setPagina(1);
            }}
            buscar={buscar}
            setBuscar={(v) => {
              setBuscar(v);
              setPagina(1);
            }}
          />
          <DataTable<SolicitudOut>
            withTableBorder
            highlightOnHover
            minHeight={180}
            records={cotizadas.data?.items ?? []}
            fetching={cotizadas.isFetching}
            totalRecords={cotizadas.data?.total ?? 0}
            recordsPerPage={PAGE}
            page={pagina}
            onPageChange={setPagina}
            onRowClick={({ record }) => navigate(`/comprador/solicitudes/${record.id}`)}
            noRecordsText="Sin cotizadas"
            columns={columnas}
          />
        </Tabs.Panel>
        <Tabs.Panel value="todas" pt="sm">
          <FiltrosTabla
            rango={rango}
            setRango={(v) => {
              setRango(v);
              setPagina(1);
            }}
            buscar={buscar}
            setBuscar={(v) => {
              setBuscar(v);
              setPagina(1);
            }}
          />
          <DataTable<SolicitudOut>
            withTableBorder
            highlightOnHover
            minHeight={180}
            records={todas.data?.items ?? []}
            fetching={todas.isFetching}
            totalRecords={todas.data?.total ?? 0}
            recordsPerPage={PAGE}
            page={pagina}
            onPageChange={setPagina}
            onRowClick={({ record }) => navigate(`/comprador/solicitudes/${record.id}`)}
            noRecordsText="Sin solicitudes"
            columns={columnas}
          />
        </Tabs.Panel>
      </Tabs>
    </Stack>
  );
}
