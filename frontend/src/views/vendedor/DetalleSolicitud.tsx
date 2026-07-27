/** Detalle del vendedor: generales, partidas, acciones por estado, línea de
 * tiempo del historial y comentarios. El comparador A–E vive en su ruta. */

import {
  Alert,
  Button,
  Group,
  Paper,
  Stack,
  Table,
  Text,
  Textarea,
  Timeline,
  Title,
} from "@mantine/core";
import { modals } from "@mantine/modals";
import { notifications } from "@mantine/notifications";
import { useState } from "react";
import { useNavigate, useParams } from "react-router";

import { useAccionSolicitud, useComentar, useSolicitud } from "../../api/hooks";
import { BadgeEstado, Dinero, SemaforoBanda } from "../../components/compartidos";
import { ApiError } from "../../lib/api";
import { fecha, fechaHora, folioCliente } from "../../lib/format";
import type { SolicitudDetailOut } from "../../lib/types";

function TablaPartidas({ solicitud }: { solicitud: SolicitudDetailOut }) {
  return (
    <Table withTableBorder withColumnBorders>
      <Table.Thead>
        <Table.Tr>
          <Table.Th>No.</Table.Th>
          <Table.Th>Código SAP</Table.Th>
          <Table.Th>Cantidad</Table.Th>
          <Table.Th>Unidad</Table.Th>
          <Table.Th>Tipo de acero</Table.Th>
          <Table.Th>Descripción</Table.Th>
          <Table.Th>Medidas</Table.Th>
        </Table.Tr>
      </Table.Thead>
      <Table.Tbody>
        {solicitud.partidas.map((p) => (
          <Table.Tr key={p.id}>
            <Table.Td>{p.num_partida}</Table.Td>
            <Table.Td>{p.codigo_sap ?? "SERVICIO"}</Table.Td>
            <Table.Td>{p.cantidad}</Table.Td>
            <Table.Td>{p.unidad}</Table.Td>
            <Table.Td>{p.tipo_acero ?? "—"}</Table.Td>
            <Table.Td>{p.descripcion}</Table.Td>
            <Table.Td>{p.medidas ?? "—"}</Table.Td>
          </Table.Tr>
        ))}
      </Table.Tbody>
    </Table>
  );
}

export function HistorialComentarios({ solicitud }: { solicitud: SolicitudDetailOut }) {
  const comentar = useComentar(solicitud.id);
  const [texto, setTexto] = useState("");

  return (
    <Group align="flex-start" grow>
      <Paper withBorder p="md">
        <Title order={5} mb="sm">
          Historial
        </Title>
        <Timeline bulletSize={18} lineWidth={2}>
          {solicitud.historial.map((h) => (
            <Timeline.Item
              key={h.id}
              title={h.de === null ? "Creada" : h.de === h.a ? h.comentario ?? "Actualizada" : `${h.de} → ${h.a}`}
            >
              <Text size="xs" c="dimmed">
                {h.usuario_nombre} · {fechaHora(h.timestamp)}
              </Text>
              {h.motivo_texto && (
                <Text size="sm" c="red">
                  Motivo: {h.motivo_texto}
                </Text>
              )}
              {h.de !== h.a && h.comentario && <Text size="sm">{h.comentario}</Text>}
            </Timeline.Item>
          ))}
        </Timeline>
      </Paper>
      <Paper withBorder p="md">
        <Title order={5} mb="sm">
          Comentarios
        </Title>
        <Stack gap="xs">
          {solicitud.comentarios.length === 0 && (
            <Text c="dimmed" size="sm">
              Sin comentarios
            </Text>
          )}
          {solicitud.comentarios.map((c) => (
            <Paper key={c.id} bg="gray.1" p="xs" radius="sm">
              <Text size="xs" c="dimmed">
                {c.usuario_nombre} · {fechaHora(c.creado_en)}
              </Text>
              <Text size="sm">{c.texto}</Text>
            </Paper>
          ))}
          <Textarea
            placeholder="Escribe un comentario"
            value={texto}
            onChange={(e) => setTexto(e.currentTarget.value)}
            autosize
            minRows={2}
          />
          <Button
            size="compact-sm"
            disabled={!texto.trim()}
            loading={comentar.isPending}
            onClick={() => {
              comentar.mutate(texto.trim(), { onSuccess: () => setTexto("") });
            }}
          >
            Comentar
          </Button>
        </Stack>
      </Paper>
    </Group>
  );
}

export function DetalleSolicitud() {
  const { id } = useParams();
  const solicitudId = Number(id);
  const navigate = useNavigate();
  const { data: solicitud, error } = useSolicitud(solicitudId);
  const cancelar = useAccionSolicitud("cancelar");

  if (error instanceof ApiError) return <Alert color="red">{error.detail}</Alert>;
  if (!solicitud) return null;

  const motivoRechazo = solicitud.historial.filter((h) => h.a === "RECHAZADA").at(-1);
  const puedeEditar = ["BORRADOR", "ENVIADA", "EN_PROCESO"].includes(solicitud.estado);
  const puedeCancelar = ["BORRADOR", "ENVIADA", "EN_PROCESO", "RECHAZADA"].includes(
    solicitud.estado,
  );

  const confirmarCancelar = () =>
    modals.openConfirmModal({
      title: "Cancelar solicitud",
      children: <Text size="sm">La cancelación es definitiva. ¿Cancelar esta solicitud?</Text>,
      labels: { confirm: "Sí, cancelar", cancel: "No" },
      confirmProps: { color: "red" },
      onConfirm: () =>
        void cancelar
          .mutateAsync(solicitud.id)
          .then(() => notifications.show({ message: "Solicitud cancelada", color: "gray" }))
          .catch((e: unknown) =>
            notifications.show({
              message: e instanceof ApiError ? e.detail : "No se pudo cancelar",
              color: "red",
            }),
          ),
    });

  return (
    <Stack>
      <Group justify="space-between">
        <Group>
          <Title order={3}>{folioCliente(solicitud.folio, solicitud.cliente_nombre)}</Title>
          <BadgeEstado estado={solicitud.estado} />
          <SemaforoBanda
            banda={solicitud.banda}
            horasHabiles={solicitud.horas_habiles}
            dias={solicitud.dias_transcurridos}
          />
          {solicitud.prioridad === "URGENTE" && (
            <Text c="acento.7" fw={700}>
              URGENTE
            </Text>
          )}
        </Group>
        <Group>
          {puedeEditar && (
            <Button variant="light" onClick={() => navigate(`/vendedor/solicitudes/${solicitud.id}/editar`)}>
              Editar
            </Button>
          )}
          {solicitud.estado === "RECHAZADA" && (
            <Button color="acento.6" onClick={() => navigate(`/vendedor/solicitudes/${solicitud.id}/editar`)}>
              Corregir y reenviar
            </Button>
          )}
          {(solicitud.estado === "COTIZADA" || solicitud.estado === "CONFIRMADA") && (
            <Button onClick={() => navigate(`/vendedor/solicitudes/${solicitud.id}/comparador`)}>
              {solicitud.estado === "COTIZADA" ? "Comparar opciones" : "Ver opciones"}
            </Button>
          )}
          {puedeCancelar && (
            <Button variant="subtle" color="red" onClick={confirmarCancelar}>
              Cancelar
            </Button>
          )}
        </Group>
      </Group>

      {solicitud.estado === "RECHAZADA" && motivoRechazo && (
        <Alert color="red" title="Rechazada por el comprador">
          <Text fw={600}>{motivoRechazo.motivo_texto ?? "(sin motivo)"}</Text>
          {motivoRechazo.comentario && <Text size="sm">{motivoRechazo.comentario}</Text>}
        </Alert>
      )}
      {solicitud.estado === "CONFIRMADA" && (
        <Alert color="green" title="Pedido confirmado">
          <Group gap="xs">
            <Text size="sm">Monto oficial:</Text>
            <Dinero monto={solicitud.monto_confirmado} moneda={solicitud.moneda_confirmada} />
          </Group>
        </Alert>
      )}
      {solicitud.estado === "NO_CONFIRMADA" && (
        <Alert color="orange" title="No se concretó">
          Motivo: {solicitud.motivo_no_confirmada ?? "—"}
        </Alert>
      )}

      <Paper withBorder p="md">
        <Group gap="xl">
          <Text size="sm">
            <b>Fecha:</b> {fecha(solicitud.creado_en)}
          </Text>
          <Text size="sm">
            <b>Prioridad:</b> {solicitud.prioridad}
          </Text>
          {solicitud.notas && (
            <Text size="sm">
              <b>Notas:</b> {solicitud.notas}
            </Text>
          )}
        </Group>
      </Paper>

      <Title order={5}>Partidas</Title>
      <TablaPartidas solicitud={solicitud} />
      <HistorialComentarios solicitud={solicitud} />
    </Stack>
  );
}
