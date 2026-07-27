/** Comparador A–E lado a lado (la pieza central del vendedor): total GRANDE
 * con su moneda, vigencia, desglose por partida, comentarios. SIN proveedor
 * (el backend no lo manda a este rol). Confirmar UNA opción o "No se
 * concretó" con motivo. */

import {
  Alert,
  Badge,
  Button,
  Card,
  Divider,
  Group,
  Radio,
  SimpleGrid,
  Stack,
  Table,
  Text,
  Textarea,
  Title,
} from "@mantine/core";
import { modals } from "@mantine/modals";
import { notifications } from "@mantine/notifications";
import { useState } from "react";
import { useNavigate, useParams } from "react-router";

import { useNoConfirmar, useSeleccionar, useSolicitud } from "../../api/hooks";
import { ApiError } from "../../lib/api";
import { dinero, fecha } from "../../lib/format";
import type { MotivoNoConfirmada, OpcionOut, SolicitudDetailOut } from "../../lib/types";

const MOTIVOS_NO: { value: MotivoNoConfirmada; label: string }[] = [
  { value: "PRECIO", label: "Precio" },
  { value: "TIEMPO_ENTREGA", label: "Tiempo de entrega" },
  { value: "CLIENTE_DESISTIO", label: "El cliente desistió" },
  { value: "OTRO", label: "Otro" },
];

function CartaOpcion({
  solicitud,
  opcion,
  onConfirmar,
}: {
  solicitud: SolicitudDetailOut;
  opcion: OpcionOut;
  onConfirmar: (() => void) | null;
}) {
  const ganadora = solicitud.opcion_seleccionada_id === opcion.id;
  const partidasPorId = new Map(solicitud.partidas.map((p) => [p.id, p]));
  return (
    <Card withBorder shadow={ganadora ? "md" : "xs"} style={ganadora ? { borderColor: "var(--mantine-color-green-6)" } : undefined}>
      <Group justify="space-between" mb="xs">
        <Badge size="lg" variant="filled">
          Opción {opcion.letra}
        </Badge>
        {ganadora && <Badge color="green">Seleccionada</Badge>}
      </Group>
      <Text size="28px" fw={700} c="herinox.7">
        {opcion.moneda ? dinero(opcion.total, opcion.moneda) : opcion.total}
      </Text>
      <Text size="sm" c="dimmed" mb="xs">
        Vigencia: {opcion.vigencia ? fecha(opcion.vigencia) : "—"}
      </Text>
      <Divider mb="xs" />
      <Table withColumnBorders verticalSpacing={4} fz="xs">
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Partida</Table.Th>
            <Table.Th>P. unitario</Table.Th>
            <Table.Th>Importe</Table.Th>
            <Table.Th>Entrega</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {opcion.renglones.map((r) => (
            <Table.Tr key={r.id}>
              <Table.Td>
                {r.num_partida}. {partidasPorId.get(r.partida_id)?.descripcion ?? ""}
              </Table.Td>
              <Table.Td>{r.precio_unitario ?? "—"}</Table.Td>
              <Table.Td>
                {r.importe !== null && opcion.moneda ? dinero(r.importe, opcion.moneda) : "—"}
              </Table.Td>
              <Table.Td>{r.tiempo_entrega ?? "—"}</Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
      {opcion.comentarios && (
        <Text size="xs" c="dimmed" mt="xs">
          {opcion.comentarios}
        </Text>
      )}
      {onConfirmar && (
        <Button mt="md" color="acento.6" fullWidth onClick={onConfirmar}>
          Confirmar pedido con esta opción
        </Button>
      )}
    </Card>
  );
}

function ModalNoConcretado({ onAceptar }: { onAceptar: (m: MotivoNoConfirmada, c: string) => void }) {
  const [motivo, setMotivo] = useState<MotivoNoConfirmada>("PRECIO");
  const [comentario, setComentario] = useState("");
  return (
    <Stack>
      <Radio.Group value={motivo} onChange={(v) => setMotivo(v as MotivoNoConfirmada)}>
        <Stack gap="xs">
          {MOTIVOS_NO.map((m) => (
            <Radio key={m.value} value={m.value} label={m.label} />
          ))}
        </Stack>
      </Radio.Group>
      <Textarea
        placeholder="Comentario (opcional)"
        value={comentario}
        onChange={(e) => setComentario(e.currentTarget.value)}
      />
      <Button onClick={() => onAceptar(motivo, comentario)}>Marcar como no concretada</Button>
    </Stack>
  );
}

export function Comparador() {
  const { id } = useParams();
  const solicitudId = Number(id);
  const navigate = useNavigate();
  const { data: solicitud } = useSolicitud(solicitudId);
  const seleccionar = useSeleccionar(solicitudId);
  const noConfirmar = useNoConfirmar(solicitudId);

  if (!solicitud) return null;
  if (solicitud.opciones.length === 0) {
    return <Alert color="yellow">Esta solicitud aún no tiene opciones capturadas.</Alert>;
  }

  const puedeConfirmar = solicitud.estado === "COTIZADA";

  const confirmar = (opcion: OpcionOut) =>
    modals.openConfirmModal({
      title: `Confirmar con la opción ${opcion.letra}`,
      children: (
        <Text size="sm">
          El pedido quedará confirmado con la opción {opcion.letra} por{" "}
          <b>{opcion.moneda ? dinero(opcion.total, opcion.moneda) : opcion.total}</b>. Esta acción
          fija el monto oficial y no se puede deshacer.
        </Text>
      ),
      labels: { confirm: "Confirmar pedido", cancel: "Volver" },
      confirmProps: { color: "acento.6" },
      onConfirm: () =>
        void seleccionar
          .mutateAsync(opcion.letra)
          .then(() => {
            notifications.show({ message: "Pedido confirmado", color: "green" });
            navigate(`/vendedor/solicitudes/${solicitudId}`);
          })
          .catch((e: unknown) =>
            notifications.show({
              message: e instanceof ApiError ? e.detail : "No se pudo confirmar",
              color: "red",
            }),
          ),
    });

  const abrirNoConcretado = () => {
    modals.open({
      title: "No se concretó el pedido",
      children: (
        <ModalNoConcretado
          onAceptar={(motivo, comentario) => {
            modals.closeAll();
            void noConfirmar
              .mutateAsync({ motivo, comentario: comentario.trim() || null })
              .then(() => {
                notifications.show({ message: "Marcada como no confirmada", color: "orange" });
                navigate(`/vendedor/solicitudes/${solicitudId}`);
              })
              .catch((e: unknown) =>
                notifications.show({
                  message: e instanceof ApiError ? e.detail : "No se pudo marcar",
                  color: "red",
                }),
              );
          }}
        />
      ),
    });
  };

  return (
    <Stack>
      <Group justify="space-between">
        <Title order={3}>
          Opciones de {solicitud.folio} · {solicitud.cliente_nombre}
        </Title>
        <Group>
          {puedeConfirmar && (
            <Button variant="outline" color="orange" onClick={abrirNoConcretado}>
              No se concretó
            </Button>
          )}
          <Button variant="default" onClick={() => navigate(`/vendedor/solicitudes/${solicitudId}`)}>
            Volver
          </Button>
        </Group>
      </Group>
      <SimpleGrid cols={{ base: 1, sm: 2, lg: Math.min(solicitud.opciones.length, 3) }}>
        {solicitud.opciones.map((o) => (
          <CartaOpcion
            key={o.id}
            solicitud={solicitud}
            opcion={o}
            onConfirmar={puedeConfirmar ? () => confirmar(o) : null}
          />
        ))}
      </SimpleGrid>
    </Stack>
  );
}
