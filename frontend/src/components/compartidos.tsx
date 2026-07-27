/** Componentes compartidos chicos: BadgeEstado, SemaforoBanda, Dinero,
 * FolioCliente. */

import { Badge, Group, Text, Tooltip } from "@mantine/core";

import { bandaColor, bandaTooltip, dinero, folioCliente } from "../lib/format";
import type { Banda, Estado, Moneda, SolicitudOut } from "../lib/types";

const COLOR_ESTADO: Record<Estado, string> = {
  BORRADOR: "gray",
  ENVIADA: "blue",
  EN_PROCESO: "indigo",
  COTIZADA: "teal",
  CONFIRMADA: "green",
  NO_CONFIRMADA: "orange",
  RECHAZADA: "red",
  CANCELADA: "dark",
};

const TEXTO_ESTADO: Record<Estado, string> = {
  BORRADOR: "Borrador",
  ENVIADA: "Enviada",
  EN_PROCESO: "En proceso",
  COTIZADA: "Cotizada",
  CONFIRMADA: "Confirmada",
  NO_CONFIRMADA: "No confirmada",
  RECHAZADA: "Rechazada",
  CANCELADA: "Cancelada",
};

export function BadgeEstado({ estado }: { estado: Estado }) {
  return (
    <Badge color={COLOR_ESTADO[estado]} variant="light">
      {TEXTO_ESTADO[estado]}
    </Badge>
  );
}

export function SemaforoBanda({
  banda,
  horasHabiles,
  dias,
}: {
  banda: Banda | null;
  horasHabiles: number | null;
  dias: number | null;
}) {
  if (banda === null) return null;
  return (
    <Tooltip label={bandaTooltip(horasHabiles ?? 0, dias ?? 0)}>
      <Badge color={bandaColor(banda)} variant="filled" size="sm" data-testid="semaforo">
        {banda === "ESPERADA" ? "Verde" : banda === "NORMAL" ? "Amarillo" : "Rojo"}
      </Badge>
    </Tooltip>
  );
}

export function Dinero({ monto, moneda }: { monto: string | number | null; moneda: Moneda | null }) {
  if (monto === null || moneda === null) return <Text c="dimmed">—</Text>;
  return <Text fw={600}>{dinero(monto, moneda)}</Text>;
}

export function FolioCliente({ folio, cliente }: { folio: string | null; cliente: string | null }) {
  return <Text fw={500}>{folioCliente(folio, cliente)}</Text>;
}

/** Monto de la fila del listado (F8b): confirmado si existe; si no, el de
 * REFERENCIA (opción A de una COTIZADA) con etiqueta "ref.". */
export function MontoSolicitud({ solicitud }: { solicitud: SolicitudOut }) {
  if (solicitud.monto_confirmado !== null && solicitud.moneda_confirmada !== null) {
    return <Dinero monto={solicitud.monto_confirmado} moneda={solicitud.moneda_confirmada} />;
  }
  if (solicitud.monto_referencia !== null && solicitud.moneda_referencia !== null) {
    return (
      <Group gap={4} wrap="nowrap">
        <Dinero monto={solicitud.monto_referencia} moneda={solicitud.moneda_referencia} />
        <Text size="xs" c="dimmed">
          ref.
        </Text>
      </Group>
    );
  }
  return <Text c="dimmed">—</Text>;
}
