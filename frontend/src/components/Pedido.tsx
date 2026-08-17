/** Vista de PEDIDO unificada (F10.1 p.4/5) — el ÚNICO componente con el que
 * comprador, gerente_compras y admin consultan una cotización publicada o un
 * pedido confirmado: TODAS las opciones con TODO su detalle (renglones,
 * proveedor, subtotales por moneda, TC, consolidado). Con ganadora fijada, la
 * ELEGIDA va en VERDE con fondo y las demás en GRIS OPACO, colapsadas pero
 * expandibles. Se monta en la pantalla del comprador (CapturaCotizacion en
 * estados no capturables) y en el detalle del CRM (DetalleCrm, CONFIRMADA).
 * El lado ventas NO usa este componente (sus reglas de visibilidad viven en
 * el Comparador y en los schemas del backend). */

import { Badge, Button, Group, Paper, Stack, Table, Text, Title } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useState } from "react";

import { useMarcarFincada } from "../api/hooks";
import { useAuth } from "../auth/AuthContext";
import { ApiError } from "../lib/api";
import { dinero, fecha } from "../lib/format";
import type { OpcionOut, SolicitudDetailOut } from "../lib/types";

// F12 p.5: el fincado es interno del área compras — los mismos roles a los
// que el backend manda las claves (el resto ni siquiera las recibe).
const ROLES_FINCADA = ["comprador", "gerente_compras", "admin"];

/** Marcado interno FINCADA (F12 p.5): switch reversible sobre un pedido
 * CONFIRMADO, en TEAL propio (distinto del verde ganadora y el morado
 * proyecto). Sin notificaciones ni historial: el rastro visible es
 * "Fincada por X el DD/MM". */
export function SeccionFincada({ solicitud }: { solicitud: SolicitudDetailOut }) {
  const { usuario } = useAuth();
  const marcar = useMarcarFincada(solicitud.id);
  if (
    usuario === null ||
    !ROLES_FINCADA.includes(usuario.rol) ||
    solicitud.estado !== "CONFIRMADA" ||
    solicitud.fincada === undefined
  ) {
    return null;
  }
  const fincada = solicitud.fincada;
  return (
    <Paper
      withBorder
      p="sm"
      data-testid="seccion-fincada"
      style={
        fincada
          ? {
              borderColor: "var(--mantine-color-teal-6)",
              backgroundColor: "var(--mantine-color-teal-0)",
            }
          : undefined
      }
    >
      <Group justify="space-between" wrap="nowrap">
        <div>
          <Group gap="xs">
            {fincada && (
              <Badge color="teal" variant="filled">
                FINCADA
              </Badge>
            )}
            <Text size="sm" fw={600}>
              {fincada ? "Pedido fincado" : "Pedido sin fincar"}
            </Text>
          </Group>
          {solicitud.fincada_por_nombre != null && solicitud.fincada_en != null && (
            <Text size="xs" c="dimmed">
              {fincada ? "Fincada" : "Movida"} por {solicitud.fincada_por_nombre} el{" "}
              {fecha(solicitud.fincada_en)}
            </Text>
          )}
        </div>
        <Button
          variant={fincada ? "light" : "filled"}
          color="teal"
          loading={marcar.isPending}
          onClick={() =>
            marcar.mutate(!fincada, {
              onError: (e: unknown) => {
                notifications.show({
                  message: e instanceof ApiError ? e.detail : "No se pudo actualizar el fincado",
                  color: "red",
                });
              },
            })
          }
        >
          {fincada ? "Quitar FINCADA" : "Marcar como FINCADA"}
        </Button>
      </Group>
    </Paper>
  );
}

function TablaRenglones({ opcion: o }: { opcion: OpcionOut }) {
  return (
    <Table withColumnBorders fz="sm">
      <Table.Thead>
        <Table.Tr>
          <Table.Th>No.</Table.Th>
          <Table.Th>Cotizado</Table.Th>
          <Table.Th>Moneda</Table.Th>
          <Table.Th>Precio unit.</Table.Th>
          <Table.Th>Importe</Table.Th>
          <Table.Th>Entrega</Table.Th>
          <Table.Th>Proveedor</Table.Th>
        </Table.Tr>
      </Table.Thead>
      <Table.Tbody>
        {o.renglones.map((r) => (
          <Table.Tr key={r.id} bg={r.no_encontrada ? "var(--mantine-color-gray-1)" : undefined}>
            <Table.Td>{r.num_partida}</Table.Td>
            <Table.Td>
              {r.no_encontrada ? (
                <Text size="sm" c="dimmed">
                  No encontrada
                </Text>
              ) : (
                `${r.cantidad} ${r.unidad}`
              )}
              {r.es_alternativa && (
                <Text size="xs" c="acento.8">
                  ALTERNATIVA: {r.alternativa_descripcion}
                </Text>
              )}
              {r.con_observacion && (
                <Text size="xs" c="blue.8">
                  OBSERVACIÓN: {r.observacion}
                </Text>
              )}
            </Table.Td>
            <Table.Td>{r.moneda ?? "—"}</Table.Td>
            <Table.Td>{r.precio_unitario ?? "—"}</Table.Td>
            <Table.Td>{r.importe !== null && r.moneda ? dinero(r.importe, r.moneda) : "—"}</Table.Td>
            <Table.Td>{r.tiempo_entrega ?? "—"}</Table.Td>
            <Table.Td>{r.proveedor ?? "—"}</Table.Td>
          </Table.Tr>
        ))}
      </Table.Tbody>
    </Table>
  );
}

/** Una opción: verde si es la elegida; gris opaco, colapsada y expandible si
 * no lo es (cuando ya hay ganadora). Toda la información sigue disponible. */
function PaperOpcion({
  solicitud,
  opcion: o,
}: {
  solicitud: SolicitudDetailOut;
  opcion: OpcionOut;
}) {
  const haySeleccion = solicitud.opcion_seleccionada_id !== null;
  const ganadora = solicitud.opcion_seleccionada_id === o.id;
  const atenuada = haySeleccion && !ganadora;
  const [expandida, setExpandida] = useState(!atenuada);
  return (
    <Paper
      withBorder
      p="sm"
      style={
        ganadora
          ? {
              borderColor: "var(--mantine-color-green-6)",
              backgroundColor: "var(--mantine-color-green-0)",
            }
          : atenuada
            ? { opacity: 0.65, backgroundColor: "var(--mantine-color-gray-0)" }
            : undefined
      }
    >
      <Group gap="xs" mb={expandida ? "xs" : 0}>
        <Badge variant="filled" color={ganadora ? "green" : atenuada ? "gray" : undefined}>
          Opción {o.letra}
        </Badge>
        {ganadora && <Badge color="green">GANADORA — genera la orden de compra</Badge>}
        <Text size="sm" fw={600}>
          {[
            Number(o.total_mxn) > 0 ? dinero(o.total_mxn, "MXN") : null,
            Number(o.total_usd) > 0 ? dinero(o.total_usd, "USD") : null,
          ]
            .filter(Boolean)
            .join(" + ") || dinero("0", "MXN")}
        </Text>
        {/* Consolidado POR OPCIÓN (el backend lo manda a los roles
            autorizados; la clave no existe para el vendedor). */}
        {o.consolidado_mxn != null && solicitud.tipo_cambio && (
          <Text size="sm" c="dimmed">
            TC {solicitud.tipo_cambio} → consolidado {dinero(o.consolidado_mxn, "MXN")}
          </Text>
        )}
        <Text size="xs" c="dimmed">
          Vigencia: {o.vigencia ? fecha(o.vigencia) : "—"}
        </Text>
        {atenuada && (
          <Button
            size="compact-xs"
            variant="subtle"
            color="gray"
            onClick={() => setExpandida(!expandida)}
          >
            {expandida ? "Ocultar detalle" : "Ver detalle"}
          </Button>
        )}
      </Group>
      {expandida && <TablaRenglones opcion={o} />}
      {expandida && o.comentarios && (
        <Text size="xs" c="dimmed" mt="xs">
          {o.comentarios}
        </Text>
      )}
    </Paper>
  );
}

export function VistaPedido({ solicitud }: { solicitud: SolicitudDetailOut }) {
  if (solicitud.opciones.length === 0) return null;
  return (
    <Stack gap="sm">
      <Title order={5}>
        {solicitud.estado === "CONFIRMADA" ? "Pedido — opciones cotizadas" : "Opciones cotizadas"}
      </Title>
      {solicitud.opciones.map((o) => (
        <PaperOpcion key={o.id} solicitud={solicitud} opcion={o} />
      ))}
    </Stack>
  );
}
