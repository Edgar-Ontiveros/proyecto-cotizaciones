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
import { useLocation, useNavigate, useParams } from "react-router";

import { useNoConfirmar, useSeleccionar, useSolicitud } from "../../api/hooks";
import { useAuth } from "../../auth/AuthContext";
import { DropzoneComprobante } from "../../components/Comprobante";
import { VolverBoton } from "../../components/Volver";
import { baseSolicitudes } from "../../lib/crm";
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
  confirmarHabilitado,
}: {
  solicitud: SolicitudDetailOut;
  opcion: OpcionOut;
  onConfirmar: (() => void) | null;
  confirmarHabilitado: boolean;
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
      <Text size="24px" fw={700} c="herinox.7">
        {[
          Number(opcion.total_mxn) > 0 ? dinero(opcion.total_mxn, "MXN") : null,
          Number(opcion.total_usd) > 0 ? dinero(opcion.total_usd, "USD") : null,
        ]
          .filter(Boolean)
          .join(" + ") || dinero("0", "MXN")}
      </Text>
      {ganadora && solicitud.tipo_cambio && (
        <Text size="sm" c="dimmed">
          TC {solicitud.tipo_cambio} → total {dinero(solicitud.monto_confirmado ?? "0", "MXN")}
        </Text>
      )}
      <Text size="sm" c="dimmed" mb="xs">
        Vigencia: {opcion.vigencia ? fecha(opcion.vigencia) : "—"}
      </Text>
      <Divider mb="xs" />
      <Table withColumnBorders verticalSpacing={4} fz="xs">
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Partida</Table.Th>
            <Table.Th>Cotizado</Table.Th>
            <Table.Th>P. unitario</Table.Th>
            <Table.Th>Importe</Table.Th>
            <Table.Th>Entrega</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {opcion.renglones.map((r) => {
            const partida = partidasPorId.get(r.partida_id);
            const difiere =
              partida !== undefined &&
              (Number(partida.cantidad) !== Number(r.cantidad) || partida.unidad !== r.unidad);
            return (
              <Table.Tr
                key={r.id}
                bg={
                  r.no_encontrada
                    ? "var(--mantine-color-gray-1)"
                    : r.es_alternativa
                      ? "var(--mantine-color-orange-0)"
                      : undefined
                }
              >
                <Table.Td>
                  {r.num_partida}. {partida?.descripcion ?? ""}
                  {r.es_alternativa && (
                    <>
                      {" "}
                      <Badge size="xs" color="acento.7" variant="filled">
                        ALTERNATIVA
                      </Badge>
                      <Text size="xs" c="acento.8">
                        {r.alternativa_descripcion}
                      </Text>
                    </>
                  )}
                </Table.Td>
                {r.no_encontrada ? (
                  <Table.Td colSpan={4}>
                    <Text size="xs" fw={600} c="dimmed">
                      No disponible — el comprador no consiguió este material
                    </Text>
                  </Table.Td>
                ) : (
                  <>
                    <Table.Td>
                      {difiere && partida ? (
                        <>
                          <Text size="xs" c="dimmed">
                            pedido: {partida.cantidad} {partida.unidad}
                          </Text>
                          <Text size="xs" fw={600}>
                            cotizado: {r.cantidad} {r.unidad}
                          </Text>
                        </>
                      ) : (
                        `${r.cantidad} ${r.unidad}`
                      )}
                    </Table.Td>
                    <Table.Td>
                      {r.precio_unitario ?? "—"} {r.moneda ?? ""}
                    </Table.Td>
                    <Table.Td>
                      {r.importe !== null && r.moneda ? dinero(r.importe, r.moneda) : "—"}
                    </Table.Td>
                    <Table.Td>{r.tiempo_entrega ?? "—"}</Table.Td>
                  </>
                )}
              </Table.Tr>
            );
          })}
        </Table.Tbody>
      </Table>
      {opcion.comentarios && (
        <Text size="xs" c="dimmed" mt="xs">
          {opcion.comentarios}
        </Text>
      )}
      {onConfirmar && (
        // F8g: el botón solo se habilita con el comprobante ya subido (el
        // backend lo exige de todos modos: 422 comprobante_requerido).
        <Button
          mt="md"
          color="acento.6"
          fullWidth
          onClick={onConfirmar}
          disabled={!confirmarHabilitado}
          title={confirmarHabilitado ? undefined : "Sube primero el comprobante del cliente"}
        >
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
  // La vista se reusa bajo /crm (F8d): las navegaciones se quedan en su base.
  const base = baseSolicitudes(useLocation().pathname);
  const { usuario } = useAuth();
  const { data: solicitud } = useSolicitud(solicitudId);
  const seleccionar = useSeleccionar(solicitudId);
  const noConfirmar = useNoConfirmar(solicitudId);

  if (!solicitud) return null;
  if (solicitud.opciones.length === 0) {
    return <Alert color="yellow">Esta solicitud aún no tiene opciones capturadas.</Alert>;
  }

  const ladoVentas =
    usuario !== null &&
    ["vendedor", "gerente_sucursal", "director_ventas", "admin"].includes(usuario.rol);
  const puedeConfirmar = solicitud.estado === "COTIZADA" && ladoVentas;
  const tieneComprobante = solicitud.comprobante !== null;

  const ejecutarConfirmacion = (opcion: OpcionOut) => {
    modals.closeAll();
    void seleccionar
      .mutateAsync({ letra: opcion.letra })
      .then(() => {
        notifications.show({ message: "Pedido confirmado", color: "green" });
        navigate(`${base}/solicitudes/${solicitudId}`);
      })
      // El error lo muestra el handler global (main.tsx).
      .catch(() => undefined);
  };

  const confirmar = (opcion: OpcionOut) => {
    // v3 (F8e): confirmación SIMPLE — el TC ya lo capturó el comprador; el
    // vendedor ve los subtotales por moneda ORIGINAL, nunca la conversión.
    const subtotales = [
      Number(opcion.total_mxn) > 0 ? dinero(opcion.total_mxn, "MXN") : null,
      Number(opcion.total_usd) > 0 ? dinero(opcion.total_usd, "USD") : null,
    ]
      .filter(Boolean)
      .join(" + ");
    modals.openConfirmModal({
      title: `Confirmar con la opción ${opcion.letra}`,
      children: (
        <Text size="sm">
          El pedido quedará confirmado con la opción {opcion.letra} por <b>{subtotales}</b>. Esta
          acción fija el monto oficial y no se puede deshacer.
        </Text>
      ),
      labels: { confirm: "Confirmar pedido", cancel: "Volver" },
      confirmProps: { color: "acento.6" },
      onConfirm: () => ejecutarConfirmacion(opcion),
    });
  };

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
                navigate(`${base}/solicitudes/${solicitudId}`);
              })
              // El error lo muestra el handler global (main.tsx).
              .catch(() => undefined);
          }}
        />
      ),
    });
  };

  return (
    <Stack>
      <Group justify="space-between">
        <Group>
          <VolverBoton />
          <Title order={3}>
            Opciones de {solicitud.folio} · {solicitud.cliente_nombre}
          </Title>
        </Group>
        <Group>
          {puedeConfirmar && (
            <Button variant="outline" color="orange" onClick={abrirNoConcretado}>
              No se concretó
            </Button>
          )}
          <Button variant="default" onClick={() => navigate(`${base}/solicitudes/${solicitudId}`)}>
            Volver
          </Button>
        </Group>
      </Group>
      {puedeConfirmar && (
        <DropzoneComprobante solicitudId={solicitudId} comprobante={solicitud.comprobante} />
      )}
      <SimpleGrid cols={{ base: 1, sm: 2, lg: Math.min(solicitud.opciones.length, 3) }}>
        {solicitud.opciones.map((o) => (
          <CartaOpcion
            key={o.id}
            solicitud={solicitud}
            opcion={o}
            onConfirmar={puedeConfirmar ? () => confirmar(o) : null}
            confirmarHabilitado={tieneComprobante}
          />
        ))}
      </SimpleGrid>
    </Stack>
  );
}
