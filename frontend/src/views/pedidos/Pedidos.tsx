/** F16a — Sección "Pedidos" (TODOS los roles): solicitudes con OC de SAP.
 * Ruta /pedidos (ventas y compras) y /crm/pedidos (CRM). Scoping igual que el
 * listado de solicitudes (lo hace el backend); el clic va al detalle por rol. */

import { Checkbox, Group, Select, Stack, Text, Title } from "@mantine/core";
import { DataTable } from "mantine-datatable";
import { useState } from "react";
import { useLocation, useNavigate } from "react-router";

import { usePedidos } from "../../api/hooks";
import { useFiltrosCatalogo } from "../../api/crmHooks";
import { useAuth } from "../../auth/AuthContext";
import { BadgeEstatusOC } from "../../components/PedidoSap";
import { opcionesSelect } from "../../crm/FiltrosDashboard";
import { baseSolicitudes } from "../../lib/crm";
import { fecha, fechaHora, folioCliente } from "../../lib/format";
import { ESTATUS_OPCIONES, dondeTexto, paramsPedidos } from "../../lib/pedidos";
import type { EstatusOC, PedidoItemOut } from "../../lib/types";

const POR_PAGINA = 25;

export function Pedidos() {
  const { usuario } = useAuth();
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const [estatus, setEstatus] = useState<EstatusOC | null>(null);
  const [soloVencidas, setSoloVencidas] = useState(false);
  const [sucursalId, setSucursalId] = useState<number | null>(null);
  const [pagina, setPagina] = useState(1);
  const esCrm = pathname.startsWith("/crm");
  const { data: catalogos } = useFiltrosCatalogo();
  const { data, isFetching } = usePedidos(
    paramsPedidos({ estatus, soloVencidas, sucursalId, pagina, porPagina: POR_PAGINA }),
  );
  const base = baseSolicitudes(pathname);
  if (!usuario) return null;

  return (
    <Stack>
      <Title order={3}>Pedidos en SAP</Title>
      <Group gap="sm">
        <Select
          placeholder="Estatus"
          data={ESTATUS_OPCIONES}
          value={estatus}
          onChange={(v) => {
            setEstatus(v as EstatusOC | null);
            setPagina(1);
          }}
          clearable
          w={220}
        />
        <Checkbox
          label="Solo vencidas"
          checked={soloVencidas}
          onChange={(e) => {
            setSoloVencidas(e.currentTarget.checked);
            setPagina(1);
          }}
        />
        {esCrm && (
          <Select
            placeholder="Sucursal"
            data={opcionesSelect(catalogos?.sucursales)}
            value={sucursalId !== null ? String(sucursalId) : null}
            onChange={(v) => {
              setSucursalId(v === null ? null : Number(v));
              setPagina(1);
            }}
            clearable
            searchable
            w={200}
          />
        )}
      </Group>
      <DataTable<PedidoItemOut>
        withTableBorder
        highlightOnHover
        minHeight={180}
        records={data?.items ?? []}
        fetching={isFetching}
        idAccessor="solicitud_id"
        totalRecords={data?.total ?? 0}
        recordsPerPage={POR_PAGINA}
        page={pagina}
        onPageChange={setPagina}
        noRecordsText="Sin pedidos con OC vinculada"
        onRowClick={({ record }) => navigate(`${base}/solicitudes/${record.solicitud_id}`)}
        columns={[
          {
            accessor: "folio",
            title: "Folio · cliente",
            render: (p) => folioCliente(p.folio, p.cliente_nombre),
          },
          { accessor: "sucursal_nombre", title: "Sucursal" },
          {
            accessor: "ocs",
            title: "OC(s)",
            render: (p) => p.ocs.map((o) => o.doc_num).join(", "),
          },
          {
            accessor: "estatus",
            title: "Estatus",
            render: (p) => (
              <Stack gap={2}>
                {p.ocs.map((o) => (
                  <BadgeEstatusOC key={o.id} estatus={o.estatus_derivado} vencida={o.vencida} />
                ))}
              </Stack>
            ),
          },
          {
            accessor: "entrega",
            title: "Entrega",
            render: (p) => (
              <Stack gap={2}>
                {p.ocs.map((o) => (
                  <Text key={o.id} size="sm" c={o.vencida ? "red" : undefined} fw={o.vencida ? 600 : undefined}>
                    {o.fecha_entrega ? fecha(o.fecha_entrega) : "—"}
                  </Text>
                ))}
              </Stack>
            ),
          },
          {
            accessor: "donde",
            title: "Dónde",
            render: (p) => (
              <Stack gap={2}>
                {p.ocs.map((o) => (
                  <Text key={o.id} size="xs">
                    {dondeTexto(o)}
                  </Text>
                ))}
              </Stack>
            ),
          },
          {
            accessor: "sync",
            title: "Última actualización",
            render: (p) => {
              const ultima = p.ocs.map((o) => o.ultimo_sync_en).sort().at(-1);
              return ultima ? fechaHora(ultima) : "—";
            },
          },
        ]}
      />
    </Stack>
  );
}
