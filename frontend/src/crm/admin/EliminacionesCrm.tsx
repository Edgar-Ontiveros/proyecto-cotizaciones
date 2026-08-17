/** Bitácora de eliminaciones definitivas (F12 p.4): vista SIMPLE y de solo
 * lectura, exclusiva de los admin maestros (el menú la esconde al resto y el
 * backend responde 404). No existe forma de editar ni borrar una fila. */

import { Text, Title, Tooltip } from "@mantine/core";
import { DataTable } from "mantine-datatable";
import { useState } from "react";

import { useEliminadas } from "../../api/crmHooks";
import { PAGE } from "../../components/filtrosListado";
import { dinero, fechaHora } from "../../lib/format";
import type { EliminacionOut } from "../../lib/types";

export function EliminacionesCrm() {
  const [pagina, setPagina] = useState(1);
  const { data, isFetching } = useEliminadas({ limit: PAGE, offset: (pagina - 1) * PAGE });
  return (
    <>
      <Title order={3} mb={4}>
        Eliminaciones
      </Title>
      <Text size="sm" c="dimmed" mb="md">
        Registro permanente de solicitudes eliminadas definitivamente. Estas filas no pueden
        editarse ni borrarse; el folio eliminado no se reutiliza.
      </Text>
      <DataTable<EliminacionOut>
        withTableBorder
        minHeight={200}
        records={data?.items ?? []}
        fetching={isFetching}
        totalRecords={data?.total ?? 0}
        recordsPerPage={PAGE}
        page={pagina}
        onPageChange={setPagina}
        noRecordsText="Sin eliminaciones registradas"
        columns={[
          { accessor: "folio", title: "Folio", render: (e) => e.folio ?? `#${e.solicitud_id}` },
          { accessor: "cliente", title: "Cliente", render: (e) => e.cliente ?? "—" },
          { accessor: "sucursal", title: "Sucursal" },
          { accessor: "estado_final", title: "Estado al morir" },
          {
            accessor: "monto_confirmado",
            title: "Monto confirmado",
            render: (e) => (e.monto_confirmado !== null ? dinero(e.monto_confirmado, "MXN") : "—"),
          },
          { accessor: "vendedor", title: "Vendedor" },
          { accessor: "comprador", title: "Comprador", render: (e) => e.comprador ?? "—" },
          {
            accessor: "contenido",
            title: "Contenido",
            render: (e) =>
              `${e.num_partidas} partida(s) · ${e.num_opciones} opción(es) · ` +
              `${e.num_comprobantes} comprobante(s)`,
          },
          {
            accessor: "motivo",
            title: "Motivo",
            render: (e) => (
              <Tooltip label={e.motivo} multiline maw={360} withArrow>
                <Text size="sm" lineClamp={2} style={{ maxWidth: 260 }}>
                  {e.motivo}
                </Text>
              </Tooltip>
            ),
          },
          { accessor: "eliminado_por", title: "Eliminó" },
          {
            accessor: "eliminado_en",
            title: "Cuándo",
            render: (e) => fechaHora(e.eliminado_en),
          },
        ]}
      />
    </>
  );
}
