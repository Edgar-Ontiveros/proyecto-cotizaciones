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

/** Badge PROYECTO (F8f): identifica la solicitud en listados, cola, detalle
 * y CRM. Devuelve null si no es proyecto. */
export function BadgeProyecto({ esProyecto }: { esProyecto: boolean }) {
  if (!esProyecto) return null;
  return (
    <Badge color="grape" variant="filled" size="sm" data-testid="badge-proyecto">
      PROYECTO
    </Badge>
  );
}

/** F10 p.7b: estado visible del flujo de cambios — derivado SIEMPRE de
 * cambio_pendiente (nunca materializado en otro lado). */
export function BadgeCambioPendiente({ pendiente }: { pendiente: boolean }) {
  if (!pendiente) return null;
  return (
    <Badge color="orange" variant="filled" size="sm" data-testid="badge-cambio">
      CAMBIO SOLICITADO
    </Badge>
  );
}

/** F10.1 p.2b: desenlace visible — el último cambio quedó APROBADO y la
 * solicitud sigue en COTIZADA (el backend lo deriva; solo aprobado lleva
 * badge — el rechazado no se pidió). */
export function BadgeCambioAprobado({ aprobado }: { aprobado: boolean }) {
  if (!aprobado) return null;
  return (
    <Badge color="green" variant="filled" size="sm" data-testid="badge-cambio-aprobado">
      CAMBIO APROBADO
    </Badge>
  );
}

/** Folio + badges PROYECTO y CAMBIO SOLICITADO para las columnas de listado
 * (vendedor, cola del comprador y tabla del CRM usan este componente). */
export function FolioConProyecto({ solicitud }: { solicitud: SolicitudOut }) {
  return (
    <Group gap={6} wrap="nowrap">
      <Text fw={500}>{solicitud.folio ?? "(borrador)"}</Text>
      <BadgeProyecto esProyecto={solicitud.es_proyecto} />
      <BadgeCambioPendiente pendiente={solicitud.cambio_pendiente} />
      <BadgeCambioAprobado aprobado={solicitud.cambio_aprobado} />
    </Group>
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

/** Monto de la fila del listado (F8c): confirmado CONSOLIDADO en MXN si
 * existe; si no, la REFERENCIA por moneda ("MX$ … + US$ …") con "ref.". */
export function MontoSolicitud({ solicitud }: { solicitud: SolicitudOut }) {
  // F8e: para el rol vendedor el consolidado NO llega (claves ausentes) —
  // cae a la referencia por moneda original (ganadora en CONFIRMADA).
  if (solicitud.monto_confirmado != null && solicitud.moneda_confirmada != null) {
    return <Dinero monto={solicitud.monto_confirmado} moneda={solicitud.moneda_confirmada} />;
  }
  const partes = [
    solicitud.referencia_mxn !== null ? dinero(solicitud.referencia_mxn, "MXN") : null,
    solicitud.referencia_usd !== null ? dinero(solicitud.referencia_usd, "USD") : null,
  ].filter(Boolean);
  if (partes.length > 0) {
    return (
      <Group gap={4} wrap="nowrap">
        <Text fw={600}>{partes.join(" + ")}</Text>
        <Text size="xs" c="dimmed">
          ref.
        </Text>
      </Group>
    );
  }
  return <Text c="dimmed">—</Text>;
}

/** F12 p.5: la fila de un pedido FINCADO se distingue en TEAL (fino: fondo
 * suave + filete izquierdo). Solo el área compras recibe la clave `fincada`;
 * para el resto de roles esto regresa undefined y la fila queda normal. */
export function estiloFilaFincada({ fincada }: { fincada?: boolean }) {
  return fincada
    ? {
        backgroundColor: "var(--mantine-color-teal-0)",
        boxShadow: "inset 3px 0 0 var(--mantine-color-teal-6)",
      }
    : undefined;
}
