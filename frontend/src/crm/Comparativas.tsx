/** Tablas comparativas del CRM (F8d): tabs por dimensión con visibilidad por
 * rol (crm/menu.COMPARATIVAS_POR_ROL) y orden client-side sobre TODO el
 * conjunto del periodo (las tablas no paginan: el backend entrega el set
 * completo). F14: orden numérico en Confirmado (MXN) y V/A/R (rojas), y
 * export a Excel de la sub-pestaña activa. */

import { Button, Group, Stack, Table, Tabs, Text, Title } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { DataTable, type DataTableSortStatus } from "mantine-datatable";
import { useMemo, useState } from "react";

import { descargarExportComparativas, useMateriales, useNoEncontrados, useTabla } from "../api/crmHooks";
import { useAuth } from "../auth/AuthContext";
import {
  type FilaComparativa,
  type PresetFechas,
  aFilaComparativa,
  ordenarComparativa,
  queryFiltrosDashboard,
} from "../lib/crm";
import { ApiError } from "../lib/api";
import { dinero, horas, pct } from "../lib/format";
import type { MaterialOut } from "../lib/types";
import { COMPARATIVAS_POR_ROL, type TabComparativa, esRolCrm } from "./menu";

const TITULOS: Record<TabComparativa, string> = {
  "por-sucursal": "Por sucursal",
  "por-vendedor": "Por vendedor",
  "por-cliente": "Por cliente",
  "por-comprador": "Por comprador",
  materiales: "Materiales",
  "no-encontrados": "No encontrados",
};

function TablaGrupos({
  dimension,
  params,
}: {
  dimension: string;
  params: Record<string, string | number | undefined>;
}) {
  const { data, isFetching } = useTabla(dimension, params, true);
  const [orden, setOrden] = useState<DataTableSortStatus<FilaComparativa>>({
    columnAccessor: "volumen",
    direction: "desc",
  });
  const [exportando, setExportando] = useState(false);
  const filas = useMemo(
    () =>
      ordenarComparativa(
        (data ?? []).map(aFilaComparativa),
        orden.columnAccessor as string,
        orden.direction,
      ),
    [data, orden],
  );
  // F14 p.3: V/A/R es columna de ALARMA — al elegirla, el primer orden es
  // rojas DESCENDENTE (lo urgente arriba); el segundo clic la invierte.
  const cambiarOrden = (nuevo: DataTableSortStatus<FilaComparativa>) => {
    if (nuevo.columnAccessor === "rojas" && orden.columnAccessor !== "rojas") {
      setOrden({ ...nuevo, direction: "desc" });
      return;
    }
    setOrden(nuevo);
  };
  // F14 p.4: exporta la sub-pestaña ACTIVA con periodo, filtros y orden
  // vigentes (el backend replica el mismo comparador sobre todo el set).
  const exportar = () => {
    setExportando(true);
    descargarExportComparativas({
      ...params,
      dimension,
      orden: String(orden.columnAccessor),
      direccion: orden.direction,
    })
      .catch((e: unknown) =>
        notifications.show({
          message: e instanceof ApiError ? e.detail : "No se pudo exportar",
          color: "red",
        }),
      )
      .finally(() => setExportando(false));
  };
  const esComprador = dimension === "comprador";
  const esCliente = dimension === "cliente";
  return (
    <Stack gap="xs">
      <Group justify="flex-end">
        <Button variant="light" size="compact-sm" loading={exportando} onClick={exportar}>
          Exportar a Excel
        </Button>
      </Group>
      <DataTable<FilaComparativa>
        withTableBorder
        highlightOnHover
        minHeight={180}
        records={filas}
        fetching={isFetching}
        sortStatus={orden}
        onSortStatusChange={cambiarOrden}
        idAccessor="id"
        noRecordsText="Sin datos en el periodo"
        columns={[
          { accessor: "nombre", title: "Nombre", sortable: true },
          { accessor: "volumen", title: "Volumen", sortable: true },
          { accessor: "ciclos_cerrados", title: "Ciclos cerrados", sortable: true },
          {
            accessor: "mediana_horas_habiles",
            title: "Mediana (h)",
            sortable: true,
            render: (g) => horas(g.mediana_horas_habiles),
          },
          {
            accessor: "pct_banda_esperada",
            title: "% esperada",
            sortable: true,
            render: (g) => pct(g.pct_banda_esperada),
          },
          {
            // F14 p.3: la flecha ordena por ROJAS (desc primero).
            accessor: "rojas",
            title: "V / A / R",
            sortable: true,
            render: (g) =>
              `${g.distribucion_bandas["ESPERADA"] ?? 0} / ${g.distribucion_bandas["NORMAL"] ?? 0} / ${g.distribucion_bandas["LENTA"] ?? 0}`,
          },
          {
            // F14 p.3: orden NUMÉRICO por el consolidado; vacíos al final.
            accessor: "confirmado_mxn",
            title: "Confirmado (MXN)",
            sortable: true,
            render: (g) => (g.confirmado_mxn !== null ? dinero(g.confirmado_mxn, "MXN") : "—"),
          },
          ...(esComprador
            ? [
                {
                  accessor: "carga_abierta",
                  title: "Carga abierta",
                  sortable: true,
                  render: (g: FilaComparativa) => g.carga_abierta ?? "—",
                },
              ]
            : []),
          ...(esCliente
            ? [
                {
                  accessor: "cotizadas",
                  title: "Cotizadas",
                  sortable: true,
                  render: (g: FilaComparativa) => g.cotizadas ?? "—",
                },
                {
                  accessor: "confirmadas",
                  title: "Confirmadas",
                  sortable: true,
                  render: (g: FilaComparativa) => g.confirmadas ?? "—",
                },
                {
                  accessor: "ratio_confirmacion",
                  title: "Ratio confirmación",
                  sortable: true,
                  render: (g: FilaComparativa) => pct(g.ratio_confirmacion),
                },
              ]
            : []),
        ]}
      />
    </Stack>
  );
}

function TablaMateriales({ params }: { params: Record<string, string | number | undefined> }) {
  const { data } = useMateriales({ ...params, limite: 20 });
  const columna = (titulo: string, filas: MaterialOut[] | undefined) => (
    <div style={{ flex: 1 }}>
      <Title order={6} mb="xs">
        {titulo}
      </Title>
      <Table withTableBorder striped>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Valor</Table.Th>
            <Table.Th>Conteo</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {(filas ?? []).map((m) => (
            <Table.Tr key={m.valor}>
              <Table.Td>{m.valor}</Table.Td>
              <Table.Td>{m.conteo}</Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </div>
  );
  return (
    <div style={{ display: "flex", gap: 16 }}>
      {columna("Por descripción", data?.por_descripcion)}
      {columna("Por código SAP", data?.por_codigo_sap)}
    </div>
  );
}

function TablaNoEncontrados({ params }: { params: Record<string, string | number | undefined> }) {
  const { data, isFetching } = useNoEncontrados(params, true);
  return (
    <Stack gap="sm">
      <Text size="sm" c="dimmed">
        Global: {data ? `${data.no_encontrados} de ${data.total_renglones} renglones` : "—"} (
        {data?.pct === null || data === undefined ? "—" : `${((data.pct ?? 0) * 100).toFixed(1)}%`})
      </Text>
      <DataTable
        withTableBorder
        minHeight={160}
        records={data?.por_comprador ?? []}
        fetching={isFetching}
        idAccessor="id"
        noRecordsText="Sin datos en el periodo"
        columns={[
          { accessor: "nombre", title: "Comprador" },
          { accessor: "total_renglones", title: "Renglones" },
          { accessor: "no_encontrados", title: "No encontrados" },
          {
            accessor: "pct",
            title: "%",
            render: (g) => (g.pct === null ? "—" : `${(g.pct * 100).toFixed(1)}%`),
          },
        ]}
      />
      {data && data.top_materiales.length > 0 && (
        <Text size="sm" c="dimmed">
          Top no encontrados: {data.top_materiales.map((m) => `${m.valor} (${m.conteo})`).join(" · ")}
        </Text>
      )}
    </Stack>
  );
}

export function Comparativas() {
  const { usuario } = useAuth();
  const [preset] = useState<PresetFechas>("mes");
  const params = queryFiltrosDashboard({ preset });
  if (!usuario || !esRolCrm(usuario.rol)) return null;
  const tabs = COMPARATIVAS_POR_ROL[usuario.rol];

  return (
    <Stack>
      <Title order={3}>Comparativas · mes en curso</Title>
      <Tabs defaultValue={tabs[0]}>
        <Tabs.List>
          {tabs.map((t) => (
            <Tabs.Tab key={t} value={t}>
              {TITULOS[t]}
            </Tabs.Tab>
          ))}
        </Tabs.List>
        {tabs.map((t) => (
          <Tabs.Panel key={t} value={t} pt="sm">
            {t === "materiales" ? (
              <TablaMateriales params={params} />
            ) : t === "no-encontrados" ? (
              <TablaNoEncontrados params={params} />
            ) : (
              <TablaGrupos dimension={t.replace("por-", "")} params={params} />
            )}
          </Tabs.Panel>
        ))}
      </Tabs>
    </Stack>
  );
}
