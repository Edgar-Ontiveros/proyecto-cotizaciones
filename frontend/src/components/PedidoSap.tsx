/** F16a — Pedidos en SAP: card "Pedido en SAP" por OC vinculada (con su
 * cadena: entradas y facturas), modal Buscar → Vincular → Fincar, y acciones
 * de compras/admin (Actualizar desde SAP, agregar y desvincular OC).
 * VISIBILIDAD (patrón proveedor): el lado ventas recibe OCVentasOut sin
 * proveedor/montos/TC/precios — aquí solo se pinta lo que llega en el JSON. */

import {
  Alert,
  Badge,
  Button,
  Group,
  Paper,
  Stack,
  Table,
  Text,
  TextInput,
  Title,
  Tooltip,
} from "@mantine/core";
import { modals } from "@mantine/modals";
import { notifications } from "@mantine/notifications";
import { useState } from "react";

import {
  useBuscarOC,
  useDesvincularOC,
  useMarcarFincada,
  useSincronizarOCs,
  useVincularOC,
} from "../api/hooks";
import { useAuth } from "../auth/AuthContext";
import { ApiError } from "../lib/api";
import { dinero, fecha, fechaHora } from "../lib/format";
import {
  ETIQUETA_ESTATUS,
  administraOC,
  colorEstatus,
  dondeTexto,
  validarBusquedaOC,
} from "../lib/pedidos";
import type { EstatusOC, Moneda, OCBusquedaOut, OCOut, SolicitudDetailOut } from "../lib/types";

export function BadgeEstatusOC({ estatus, vencida }: { estatus: EstatusOC; vencida: boolean }) {
  return (
    <Group gap={4} wrap="nowrap">
      <Badge color={colorEstatus(estatus)} variant="filled" size="sm">
        {ETIQUETA_ESTATUS[estatus]}
      </Badge>
      {vencida && (
        <Badge color="red" variant="outline" size="sm">
          VENCIDA
        </Badge>
      )}
    </Group>
  );
}

function montoOC(total: string | null | undefined, moneda: string | null | undefined): string | null {
  if (total == null || !moneda) return null;
  return dinero(total, moneda as Moneda);
}

// ----------------------------------------------------------- modal de OC

/** Tarjeta de la OC encontrada (antes de vincular). */
function TarjetaOC({ oc }: { oc: OCBusquedaOut }) {
  return (
    <Paper withBorder p="sm" data-testid="tarjeta-oc">
      <Group justify="space-between" align="flex-start">
        <div>
          <Text fw={600}>
            OC {oc.doc_num} · sucursal SAP {oc.sucursal_sap ?? "—"}
          </Text>
          <Text size="sm">{oc.proveedor ?? "—"}</Text>
          <Text size="xs" c="dimmed">
            Contabilizada {oc.fecha_contabilizacion ? fecha(oc.fecha_contabilizacion) : "—"} ·
            entrega {oc.fecha_entrega ? fecha(oc.fecha_entrega) : "—"} · {dondeTexto(oc)}
          </Text>
          {oc.encargado_compras && (
            <Text size="xs" c="dimmed">
              Encargado de compras: {oc.encargado_compras}
            </Text>
          )}
        </div>
        <Stack gap={4} align="flex-end">
          <BadgeEstatusOC estatus={oc.estatus_derivado} vencida={oc.vencida} />
          <Text fw={600}>{montoOC(oc.total, oc.moneda) ?? "—"}</Text>
        </Stack>
      </Group>
      {oc.advertencia_encargado && (
        <Alert color="yellow" mt="xs" p="xs">
          {oc.advertencia_encargado}
        </Alert>
      )}
      {oc.ya_vinculada_aqui && (
        <Alert color="blue" mt="xs" p="xs">
          Esta OC ya está vinculada a esta solicitud.
        </Alert>
      )}
    </Paper>
  );
}

/** Flujo Buscar → Vincular (→ otra OC) → Fincar. `alFincar` opcional: cuando
 * se abre desde "Marcar como FINCADA"; desde Pedidos solo agrega OC. */
export function ModalVincularOC({
  solicitud,
  conFincar,
  onListo,
}: {
  solicitud: SolicitudDetailOut;
  conFincar: boolean;
  onListo: () => void;
}) {
  const buscar = useBuscarOC(solicitud.id);
  const vincular = useVincularOC(solicitud.id);
  const marcar = useMarcarFincada(solicitud.id);
  const [docNum, setDocNum] = useState("");
  const [sucursalSap, setSucursalSap] = useState(solicitud.sucursal_serie_sap ?? "");
  const [error, setError] = useState<string | null>(null);
  const [tarjeta, setTarjeta] = useState<OCBusquedaOut | null>(null);
  const [vinculadas, setVinculadas] = useState<number[]>(solicitud.ocs.map((o) => o.doc_num));

  const mensajeError = (e: unknown) =>
    e instanceof ApiError ? e.detail : "No se pudo consultar SAP";

  const ejecutarBusqueda = () => {
    setError(null);
    setTarjeta(null);
    const v = validarBusquedaOC(docNum, sucursalSap);
    if ("error" in v) {
      setError(v.error);
      return;
    }
    buscar.mutate(v, {
      onSuccess: (t) => setTarjeta(t),
      onError: (e) => setError(mensajeError(e)),
    });
  };

  const ejecutarVincular = () => {
    if (!tarjeta) return;
    setError(null);
    vincular.mutate(
      { doc_num: tarjeta.doc_num, sucursal_sap: tarjeta.sucursal_sap ?? sucursalSap },
      {
        onSuccess: (oc) => {
          setVinculadas((prev) => [...prev, oc.doc_num]);
          setTarjeta(null);
          setDocNum("");
          notifications.show({ message: `OC ${oc.doc_num} vinculada`, color: "green" });
        },
        onError: (e) => setError(mensajeError(e)),
      },
    );
  };

  const ejecutarFincar = () =>
    marcar.mutate(true, {
      onSuccess: () => {
        notifications.show({ message: "Pedido fincado", color: "teal" });
        onListo();
      },
      onError: (e) => setError(mensajeError(e)),
    });

  return (
    <Stack gap="sm">
      <Text size="sm" c="dimmed">
        Captura el número de la orden de compra en SAP y la sucursal SAP (serie de la OC).
        Se consulta HANA en solo lectura; si SAP no responde, no se puede fincar.
      </Text>
      <Group align="flex-end" gap="sm">
        <TextInput
          label="Número de OC"
          placeholder="31000103"
          value={docNum}
          onChange={(e) => setDocNum(e.currentTarget.value)}
          w={160}
          data-autofocus
        />
        <TextInput
          label="Sucursal SAP"
          description="Serie de la OC (CH, CN, LE…)"
          value={sucursalSap}
          onChange={(e) => setSucursalSap(e.currentTarget.value.toUpperCase())}
          w={140}
        />
        <Button variant="light" loading={buscar.isPending} onClick={ejecutarBusqueda}>
          Buscar
        </Button>
      </Group>
      {tarjeta && (
        <>
          <TarjetaOC oc={tarjeta} />
          <Group justify="flex-end">
            <Button
              color="acento.6"
              disabled={tarjeta.ya_vinculada_aqui}
              loading={vincular.isPending}
              onClick={ejecutarVincular}
            >
              Vincular
            </Button>
          </Group>
        </>
      )}
      {vinculadas.length > 0 && (
        <Text size="sm">
          OC vinculadas a esta solicitud: <b>{vinculadas.join(", ")}</b>
          {tarjeta === null && " · puedes buscar otra OC (una por proveedor)"}
        </Text>
      )}
      {error && <Alert color="red">{error}</Alert>}
      <Group justify="flex-end">
        <Button variant="subtle" color="gray" onClick={onListo}>
          {conFincar ? "Cancelar" : "Cerrar"}
        </Button>
        {conFincar && (
          <Button
            color="teal"
            disabled={vinculadas.length === 0}
            loading={marcar.isPending}
            onClick={ejecutarFincar}
          >
            Fincar
          </Button>
        )}
      </Group>
    </Stack>
  );
}

export function abrirModalOC(solicitud: SolicitudDetailOut, conFincar: boolean) {
  modals.open({
    title: conFincar ? "Fincar pedido — vincula su orden de compra" : "Agregar orden de compra de SAP",
    size: "lg",
    children: (
      <ModalVincularOC solicitud={solicitud} conFincar={conFincar} onListo={() => modals.closeAll()} />
    ),
  });
}

// ---------------------------------------------------------- cards de OC

function CadenaOC({ oc }: { oc: OCOut }) {
  return (
    <Stack gap={4}>
      {oc.entradas.length > 0 ? (
        oc.entradas.map((e) => (
          <Text size="xs" key={e.doc_num} td={e.cancelada ? "line-through" : undefined}>
            Entrada de mercancías <b>{e.doc_num}</b> · {e.fecha ? fecha(e.fecha) : "—"} · entró en{" "}
            {e.donde.join(", ") || "—"} · {e.cantidad_total} uds
          </Text>
        ))
      ) : (
        <Text size="xs" c="dimmed">
          Sin entradas de mercancías
        </Text>
      )}
      {oc.facturas.length > 0 ? (
        oc.facturas.map((f) => (
          <Text size="xs" key={f.doc_num} td={f.cancelada ? "line-through" : undefined}>
            Factura de proveedor <b>{f.doc_num}</b> · {f.fecha ? fecha(f.fecha) : "—"}
            {montoOC(f.total, f.moneda) ? ` · ${montoOC(f.total, f.moneda)}` : ""}
          </Text>
        ))
      ) : (
        <Text size="xs" c="dimmed">
          Sin factura de proveedor
        </Text>
      )}
    </Stack>
  );
}

function TablaLineasOC({ oc }: { oc: OCOut }) {
  const conPrecio = oc.lineas.some((l) => l.precio !== undefined);
  return (
    <Table fz="xs" withColumnBorders>
      <Table.Thead>
        <Table.Tr>
          <Table.Th>Artículo</Table.Th>
          <Table.Th>Cantidad</Table.Th>
          <Table.Th>Pendiente</Table.Th>
          <Table.Th>Almacén</Table.Th>
          <Table.Th>Entrega</Table.Th>
          {conPrecio && <Table.Th>Precio</Table.Th>}
          {conPrecio && <Table.Th>Importe</Table.Th>}
        </Table.Tr>
      </Table.Thead>
      <Table.Tbody>
        {oc.lineas.map((l) => (
          <Table.Tr key={l.num_linea}>
            <Table.Td>
              {l.articulo} <Text span c="dimmed">{l.descripcion}</Text>
            </Table.Td>
            <Table.Td>{l.cantidad}</Table.Td>
            <Table.Td>{l.cantidad_abierta}</Table.Td>
            <Table.Td>{l.almacen ?? "—"}</Table.Td>
            <Table.Td>{l.fecha_entrega ? fecha(l.fecha_entrega) : "—"}</Table.Td>
            {conPrecio && <Table.Td>{l.precio ?? "—"}</Table.Td>}
            {conPrecio && <Table.Td>{montoOC(l.importe, l.moneda) ?? "—"}</Table.Td>}
          </Table.Tr>
        ))}
      </Table.Tbody>
    </Table>
  );
}

export function CardOC({
  oc,
  solicitudId,
  puedeAdministrar,
}: {
  oc: OCOut;
  solicitudId: number;
  puedeAdministrar: boolean;
}) {
  const desvincular = useDesvincularOC(solicitudId);
  const [detalle, setDetalle] = useState(false);
  return (
    <Paper withBorder p="sm" data-testid="card-oc">
      <Group justify="space-between" align="flex-start" wrap="nowrap">
        <div>
          <Group gap="xs">
            <Text fw={600}>Pedido en SAP · OC {oc.doc_num}</Text>
            <Text size="xs" c="dimmed">
              sucursal SAP {oc.sucursal_sap ?? "—"}
            </Text>
            <BadgeEstatusOC estatus={oc.estatus_derivado} vencida={oc.vencida} />
          </Group>
          {oc.proveedor !== undefined && (
            <Text size="sm">
              {oc.proveedor ?? "—"}
              {montoOC(oc.total, oc.moneda) ? ` · ${montoOC(oc.total, oc.moneda)}` : ""}
              {oc.tipo_cambio ? ` · TC ${oc.tipo_cambio}` : ""}
            </Text>
          )}
          <Text size="xs" c="dimmed">
            Contabilizada {oc.fecha_contabilizacion ? fecha(oc.fecha_contabilizacion) : "—"} · entrega{" "}
            <Text span c={oc.vencida ? "red" : undefined} fw={oc.vencida ? 600 : undefined}>
              {oc.fecha_entrega ? fecha(oc.fecha_entrega) : "—"}
            </Text>{" "}
            · {dondeTexto(oc)}
          </Text>
          {oc.encargado_compras !== undefined && oc.encargado_compras && (
            <Text size="xs" c="dimmed">
              Encargado de compras: {oc.encargado_compras}
            </Text>
          )}
        </div>
        <Stack gap={4} align="flex-end">
          <Tooltip label={`Vinculada por ${oc.vinculada_por_nombre ?? "—"} el ${fechaHora(oc.vinculada_en)}`}>
            <Text size="xs" c="dimmed">
              SAP al {fechaHora(oc.ultimo_sync_en)}
            </Text>
          </Tooltip>
          <Group gap={4}>
            <Button size="compact-xs" variant="subtle" onClick={() => setDetalle(!detalle)}>
              {detalle ? "Ocultar líneas" : "Ver líneas"}
            </Button>
            {puedeAdministrar && (
              <Button
                size="compact-xs"
                variant="subtle"
                color="red"
                loading={desvincular.isPending}
                onClick={() =>
                  modals.openConfirmModal({
                    title: `Desvincular la OC ${oc.doc_num}`,
                    children: (
                      <Text size="sm">
                        La OC deja de asociarse a esta solicitud (queda en el historial). No se
                        borra nada en SAP.
                      </Text>
                    ),
                    labels: { confirm: "Desvincular", cancel: "Cancelar" },
                    confirmProps: { color: "red" },
                    onConfirm: () =>
                      desvincular.mutate(oc.id, {
                        onSuccess: () =>
                          notifications.show({ message: "OC desvinculada", color: "gray" }),
                      }),
                  })
                }
              >
                Desvincular
              </Button>
            )}
          </Group>
        </Stack>
      </Group>
      {oc.ultimo_error && (
        <Alert color="yellow" p="xs" mt="xs">
          {oc.ultimo_error} — se muestra el último dato sincronizado.
        </Alert>
      )}
      <Stack gap={4} mt="xs">
        <CadenaOC oc={oc} />
      </Stack>
      {detalle && <TablaLineasOC oc={oc} />}
    </Paper>
  );
}

/** Sección "Pedido en SAP" del detalle: cards por OC + acciones de compras.
 * Se auto-esconde fuera de CONFIRMADA sin OC. */
export function SeccionPedidoSap({ solicitud }: { solicitud: SolicitudDetailOut }) {
  const { usuario } = useAuth();
  const sincronizar = useSincronizarOCs(solicitud.id);
  if (!usuario) return null;
  const puedeAdministrar = administraOC(usuario.rol) && solicitud.estado === "CONFIRMADA";
  if (solicitud.ocs.length === 0 && !puedeAdministrar) return null;
  return (
    <Stack gap="xs" data-testid="seccion-pedido-sap">
      <Group justify="space-between">
        <Title order={5}>Pedido en SAP</Title>
        {puedeAdministrar && (
          <Group gap="xs">
            {solicitud.ocs.length > 0 && (
              <Button
                size="compact-sm"
                variant="light"
                loading={sincronizar.isPending}
                onClick={() =>
                  sincronizar.mutate(undefined, {
                    onSuccess: () =>
                      notifications.show({ message: "Actualizado desde SAP", color: "green" }),
                    onError: (e) =>
                      notifications.show({
                        message: e instanceof ApiError ? e.detail : "No se pudo consultar SAP",
                        color: "red",
                      }),
                  })
                }
              >
                Actualizar desde SAP
              </Button>
            )}
            <Button size="compact-sm" variant="light" onClick={() => abrirModalOC(solicitud, false)}>
              Agregar OC
            </Button>
          </Group>
        )}
      </Group>
      {solicitud.ocs.length === 0 ? (
        <Text size="sm" c="dimmed">
          Sin OC vinculada.
        </Text>
      ) : (
        solicitud.ocs.map((oc) => (
          <CardOC key={oc.id} oc={oc} solicitudId={solicitud.id} puedeAdministrar={puedeAdministrar} />
        ))
      )}
    </Stack>
  );
}
