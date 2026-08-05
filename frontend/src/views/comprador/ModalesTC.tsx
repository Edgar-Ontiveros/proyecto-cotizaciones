/** Modales de TIPO DE CAMBIO del comprador (F8e): al marcar la cotización
 * completa con USD el TC es obligatorio y se muestra el consolidado POR
 * OPCIÓN en vivo; en corrección post-cotizada se actualiza vía PATCH. */

import { Button, Stack, Table, Text, TextInput } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useState } from "react";

import { useCorregirTipoCambio } from "../../api/crmHooks";
import { dinero } from "../../lib/format";
import { consolidadoMXN } from "../../lib/renglon";
import type { OpcionOut } from "../../lib/types";

function ConsolidadosEnVivo({ opciones, tc }: { opciones: OpcionOut[]; tc: string }) {
  return (
    <Table withTableBorder>
      <Table.Thead>
        <Table.Tr>
          <Table.Th>Opción</Table.Th>
          <Table.Th>Subtotales</Table.Th>
          <Table.Th>Consolidado MXN</Table.Th>
        </Table.Tr>
      </Table.Thead>
      <Table.Tbody>
        {opciones.map((o) => {
          const consolidado = consolidadoMXN(o.total_mxn, o.total_usd, tc);
          const subtotales = [
            Number(o.total_mxn) > 0 ? dinero(o.total_mxn, "MXN") : null,
            Number(o.total_usd) > 0 ? dinero(o.total_usd, "USD") : null,
          ]
            .filter(Boolean)
            .join(" + ");
          return (
            <Table.Tr key={o.id}>
              <Table.Td>{o.letra}</Table.Td>
              <Table.Td>{subtotales || "—"}</Table.Td>
              <Table.Td fw={600}>
                {consolidado !== null ? dinero(consolidado, "MXN") : "—"}
              </Table.Td>
            </Table.Tr>
          );
        })}
      </Table.Tbody>
    </Table>
  );
}

export function ModalCotizarConTC({
  opciones,
  onAceptar,
  cargando,
}: {
  opciones: OpcionOut[];
  onAceptar: (tc: string) => void;
  cargando: boolean;
}) {
  const [tc, setTc] = useState("");
  const valido = Number(tc) > 0;
  return (
    <Stack gap="sm">
      <Text size="sm">
        Hay renglones en USD: captura el tipo de cambio para publicar la cotización. El vendedor
        NO ve la conversión — el consolidado es para compras y gerencias.
      </Text>
      <TextInput
        label="Tipo de cambio (MXN por USD)"
        placeholder="18.5000"
        value={tc}
        onChange={(e) => setTc(e.currentTarget.value)}
      />
      <ConsolidadosEnVivo opciones={opciones} tc={tc} />
      <Button color="acento.6" disabled={!valido} loading={cargando} onClick={() => onAceptar(tc.trim())}>
        Marcar completa con este tipo de cambio
      </Button>
    </Stack>
  );
}

export function ModalCorregirTCComprador({
  solicitudId,
  tcActual,
  opciones,
  onListo,
}: {
  solicitudId: number;
  tcActual: string | null;
  opciones: OpcionOut[];
  onListo: () => void;
}) {
  const [tc, setTc] = useState("");
  const corregir = useCorregirTipoCambio(solicitudId);
  const valido = Number(tc) > 0;
  return (
    <Stack gap="sm">
      <Text size="sm">
        TC actual: <b>{tcActual ?? "—"}</b>. Al corregirlo se recalculan los consolidados por
        opción y queda evento en el historial.
      </Text>
      <TextInput
        label="Nuevo tipo de cambio (MXN por USD)"
        placeholder="18.5000"
        value={tc}
        onChange={(e) => setTc(e.currentTarget.value)}
      />
      <ConsolidadosEnVivo opciones={opciones} tc={tc} />
      <Button
        disabled={!valido}
        loading={corregir.isPending}
        onClick={() =>
          corregir.mutate(tc.trim(), {
            onSuccess: () => {
              notifications.show({ message: "Tipo de cambio corregido", color: "green" });
              onListo();
            },
          })
        }
      >
        Corregir tipo de cambio
      </Button>
    </Stack>
  );
}

/** F10.3 (FASE B): captura del TC exigida por el backend al RECOTIZAR o al
 * AUTORIZAR un cambio (422 tipo_cambio_requerido). Modal genérico: captura y
 * devuelve; la mutación la reintenta quien lo abrió. */
export function ModalCapturaTC({
  mensaje,
  onAceptar,
}: {
  mensaje: string;
  onAceptar: (tc: string) => void;
}) {
  const [tc, setTc] = useState("");
  return (
    <Stack gap="sm">
      <Text size="sm">{mensaje}</Text>
      <TextInput
        label="Tipo de cambio (MXN por USD)"
        placeholder="18.5000"
        value={tc}
        onChange={(e) => setTc(e.currentTarget.value)}
        data-autofocus
      />
      <Button disabled={!(Number(tc) > 0)} onClick={() => onAceptar(tc.trim())}>
        Aplicar y continuar
      </Button>
    </Stack>
  );
}
