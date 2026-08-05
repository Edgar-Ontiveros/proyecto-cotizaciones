/** Flujo de cambios de cantidad/unidad post-cotización (F8h, §4.8b).
 *
 * - ModalSolicitarCambio + BannerCambioVendedor: lado ventas (comparador).
 * - BannerCambioComprador: diff antes→después con editor de ajustes de
 *   precio/tiempo por renglón afectado e importes recalculados EN VIVO;
 *   Aprobar / Rechazar (comentario obligatorio).
 * Cantidades/unidades no son dinero; los precios solo aparecen del lado que
 * ya los ve (las opciones del rol).
 */

import {
  Alert,
  Badge,
  Button,
  Group,
  Select,
  Stack,
  Table,
  Text,
  Textarea,
  TextInput,
} from "@mantine/core";
import { modals } from "@mantine/modals";
import { notifications } from "@mantine/notifications";
import { useState } from "react";

import {
  useAprobarCambio,
  useRechazarCambio,
  useRetirarCambio,
  useSolicitarCambio,
  type AjusteBody,
} from "../api/hooks";
import { useAuth } from "../auth/AuthContext";
import { ApiError } from "../lib/api";
import { fechaHora } from "../lib/format";
import { armarAjustes } from "../lib/renglon";
import type { CambioOut, SolicitudDetailOut, Unidad } from "../lib/types";

const UNIDADES: Unidad[] = ["PZ", "KG", "TON", "MTS", "M2"];

function diffTexto(cambio: CambioOut): string {
  return cambio.partidas
    .map(
      (p) =>
        `partida ${p.num_partida}: ${p.cantidad_anterior} ${p.unidad_anterior} → ` +
        `${p.cantidad_nueva} ${p.unidad_nueva}`,
    )
    .join(" · ");
}

// ------------------------------------------------------------- lado ventas

export function ModalSolicitarCambio({
  solicitud,
  onListo,
}: {
  solicitud: SolicitudDetailOut;
  onListo: () => void;
}) {
  const solicitar = useSolicitarCambio(solicitud.id);
  const [comentario, setComentario] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [filas, setFilas] = useState(
    solicitud.partidas.map((p) => ({
      partida_id: p.id,
      num: p.num_partida,
      descripcion: p.descripcion,
      cantidadOriginal: p.cantidad,
      unidadOriginal: p.unidad as string,
      cantidad: p.cantidad,
      unidad: p.unidad as string,
    })),
  );

  const setFila = (i: number, campo: "cantidad" | "unidad", valor: string) =>
    setFilas((prev) => prev.map((f, j) => (j === i ? { ...f, [campo]: valor } : f)));

  const modificada = (f: (typeof filas)[number]) =>
    Number(f.cantidad) !== Number(f.cantidadOriginal) || f.unidad !== f.unidadOriginal;

  const enviar = () => {
    const cambiadas = filas.filter(modificada);
    if (cambiadas.length === 0) {
      setError("Modifica al menos una cantidad o unidad");
      return;
    }
    if (cambiadas.some((f) => !(Number(f.cantidad) > 0))) {
      setError("Las cantidades deben ser mayores a 0");
      return;
    }
    solicitar.mutate(
      {
        comentario: comentario.trim() || null,
        partidas: cambiadas.map((f) => ({
          partida_id: f.partida_id,
          cantidad_nueva: f.cantidad,
          unidad_nueva: f.unidad,
        })),
      },
      {
        onSuccess: () => {
          notifications.show({
            message: "Cambio solicitado: el comprador debe aprobarlo",
            color: "blue",
          });
          onListo();
        },
        onError: (e) =>
          setError(e instanceof ApiError ? e.detail : "No se pudo solicitar el cambio"),
      },
    );
  };

  return (
    <Stack gap="sm">
      <Text size="sm" c="dimmed">
        Ajusta cantidad y/o unidad; el comprador verá el antes→después y podrá
        ajustar precios al aprobar. Mientras esté pendiente no podrás confirmar.
      </Text>
      <Table withTableBorder withColumnBorders>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>No.</Table.Th>
            <Table.Th>Descripción</Table.Th>
            <Table.Th>Actual</Table.Th>
            <Table.Th w={110}>Cantidad</Table.Th>
            <Table.Th w={90}>Unidad</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {filas.map((f, i) => (
            <Table.Tr key={f.partida_id} bg={modificada(f) ? "var(--mantine-color-yellow-0)" : undefined}>
              <Table.Td>{f.num}</Table.Td>
              <Table.Td>{f.descripcion}</Table.Td>
              <Table.Td>
                {f.cantidadOriginal} {f.unidadOriginal}
              </Table.Td>
              <Table.Td>
                <TextInput
                  value={f.cantidad}
                  onChange={(e) => setFila(i, "cantidad", e.currentTarget.value)}
                />
              </Table.Td>
              <Table.Td>
                <Select
                  data={UNIDADES}
                  allowDeselect={false}
                  value={f.unidad}
                  onChange={(v) => setFila(i, "unidad", v ?? f.unidad)}
                />
              </Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
      <Textarea
        label="Comentario (opcional)"
        placeholder="Por qué cambia el pedido"
        value={comentario}
        onChange={(e) => setComentario(e.currentTarget.value)}
        autosize
        minRows={2}
      />
      {error && <Alert color="red">{error}</Alert>}
      <Button loading={solicitar.isPending} onClick={enviar}>
        Solicitar cambio
      </Button>
    </Stack>
  );
}

/** Banner del lado ventas: pendiente (bloquea confirmar, permite retirar) o
 * desenlace del último cambio resuelto mientras siga en COTIZADA. */
export function BannerCambioVendedor({ solicitud }: { solicitud: SolicitudDetailOut }) {
  const { usuario } = useAuth();
  const retirar = useRetirarCambio(solicitud.id);
  const ultimo = solicitud.cambios.at(-1);
  if (!ultimo) return null;

  if (ultimo.estado_cambio === "PENDIENTE") {
    const puedeRetirar =
      usuario !== null && (usuario.id === ultimo.solicitado_por || usuario.rol === "admin");
    return (
      <Alert color="yellow" title="Cambio pendiente de aprobación del comprador">
        <Group justify="space-between" align="flex-start">
          <div>
            <Text size="sm">{diffTexto(ultimo)}</Text>
            {ultimo.comentario_solicitante && (
              <Text size="xs" c="dimmed">
                “{ultimo.comentario_solicitante}” — {ultimo.solicitado_por_nombre}
              </Text>
            )}
            <Text size="xs" c="dimmed">
              No se puede confirmar el pedido hasta que el comprador lo resuelva.
            </Text>
          </div>
          {puedeRetirar && (
            <Button
              size="compact-sm"
              variant="light"
              color="gray"
              loading={retirar.isPending}
              onClick={() =>
                retirar.mutate(undefined, {
                  onSuccess: () =>
                    notifications.show({ message: "Cambio retirado", color: "gray" }),
                })
              }
            >
              Retirar cambio
            </Button>
          )}
        </Group>
      </Alert>
    );
  }

  if (solicitud.estado !== "COTIZADA" || ultimo.estado_cambio === "RETIRADO") return null;
  const aprobado = ultimo.estado_cambio === "APROBADO";
  return (
    <Alert
      color={aprobado ? "green" : "red"}
      title={aprobado ? "Cambio aprobado por el comprador" : "Cambio rechazado por el comprador"}
    >
      <Text size="sm">{diffTexto(ultimo)}</Text>
      {ultimo.comentario_resolucion && (
        <Text size="sm">
          “{ultimo.comentario_resolucion}” — {ultimo.resuelto_por_nombre}
        </Text>
      )}
      {ultimo.resuelto_en && (
        <Text size="xs" c="dimmed">
          {fechaHora(ultimo.resuelto_en)}
        </Text>
      )}
    </Alert>
  );
}

// ------------------------------------------------------------ lado compras

interface FilaAjuste {
  letra: string;
  partida_id: number;
  num: number;
  descripcion: string;
  moneda: string | null;
  cantidadNueva: string;
  unidadNueva: string;
  precioActual: string | null;
  tiempoActual: string; // F10.2 p.1: base para detectar ajuste de solo-tiempo
  unidadCambia: boolean;
  precio: string; // editable
  tiempo: string; // editable
}

function ModalRechazoCambio({
  onRechazar,
  cargando,
}: {
  onRechazar: (comentario: string) => void;
  cargando: boolean;
}) {
  const [comentario, setComentario] = useState("");
  return (
    <Stack gap="sm">
      <Textarea
        label="Motivo del rechazo (obligatorio)"
        value={comentario}
        onChange={(e) => setComentario(e.currentTarget.value)}
        autosize
        minRows={2}
        data-autofocus
      />
      <Button
        color="red"
        disabled={!comentario.trim()}
        loading={cargando}
        onClick={() => onRechazar(comentario.trim())}
      >
        Rechazar cambio
      </Button>
    </Stack>
  );
}

/** Banner del comprador con el diff y el editor de ajustes por renglón. */
export function BannerCambioComprador({ solicitud }: { solicitud: SolicitudDetailOut }) {
  const pendiente = solicitud.cambios.find((c) => c.estado_cambio === "PENDIENTE");
  const aprobar = useAprobarCambio(solicitud.id);
  const rechazar = useRechazarCambio(solicitud.id);
  const [error, setError] = useState<string | null>(null);
  const [filas, setFilas] = useState<FilaAjuste[] | null>(null);

  if (!pendiente) return null;

  // Filas del editor: cada opción × partida afectada con renglón capturado.
  const iniciales: FilaAjuste[] = solicitud.opciones.flatMap((o) =>
    pendiente.partidas.flatMap((p) => {
      const renglon = o.renglones.find((x) => x.partida_id === p.partida_id);
      if (!renglon || renglon.no_encontrada) return [];
      const unidadCambia = p.unidad_nueva !== renglon.unidad;
      return [
        {
          letra: o.letra,
          partida_id: p.partida_id,
          num: p.num_partida,
          descripcion: p.descripcion,
          moneda: renglon.moneda,
          cantidadNueva: p.cantidad_nueva,
          unidadNueva: p.unidad_nueva,
          precioActual: renglon.precio_unitario,
          tiempoActual: renglon.tiempo_entrega ?? "",
          unidadCambia,
          // Con cambio de unidad el precio anterior queda inválido: vacío.
          precio: unidadCambia ? "" : (renglon.precio_unitario ?? ""),
          tiempo: renglon.tiempo_entrega ?? "",
        },
      ];
    }),
  );
  const editor = filas ?? iniciales;
  const setCampo = (i: number, campo: "precio" | "tiempo", valor: string) =>
    setFilas(editor.map((f, j) => (j === i ? { ...f, [campo]: valor } : f)));

  const importe = (f: FilaAjuste) => {
    const precio = Number(f.precio);
    if (!(precio > 0)) return null;
    return (Number(f.cantidadNueva) * precio).toFixed(2);
  };

  const ejecutarAprobar = () => {
    setError(null);
    for (const f of editor) {
      if (f.unidadCambia && !(Number(f.precio.trim()) > 0)) {
        setError(
          `Opción ${f.letra}, partida ${f.num}: la unidad cambia — captura el precio nuevo`,
        );
        return;
      }
    }
    // F10.2 p.1: la decisión de qué viaja vive en armarAjustes (lib/renglon,
    // testeada) — incluye los ajustes de SOLO tiempo, que antes se perdían.
    const ajustes: AjusteBody[] = armarAjustes(editor);
    aprobar.mutate(
      { cambioId: pendiente.id, comentario: null, ajustes },
      {
        onSuccess: () => notifications.show({ message: "Cambio aprobado", color: "green" }),
        onError: (e) =>
          setError(e instanceof ApiError ? e.detail : "No se pudo aprobar el cambio"),
      },
    );
  };

  const abrirRechazo = () =>
    modals.open({
      title: "Rechazar el cambio",
      children: (
        <ModalRechazoCambio
          cargando={rechazar.isPending}
          onRechazar={(comentario) => {
            rechazar.mutate(
              { cambioId: pendiente.id, comentario },
              {
                onSuccess: () => {
                  modals.closeAll();
                  notifications.show({ message: "Cambio rechazado", color: "orange" });
                },
                onError: (e) => {
                  modals.closeAll();
                  setError(e instanceof ApiError ? e.detail : "No se pudo rechazar");
                },
              },
            );
          }}
        />
      ),
    });

  return (
    <Alert color="grape" title="Cambio de cantidad/unidad pendiente de tu aprobación">
      <Stack gap="sm">
        <div>
          {pendiente.partidas.map((p) => (
            <Text size="sm" key={p.partida_id}>
              <b>Partida {p.num_partida}</b> ({p.descripcion}): {p.cantidad_anterior}{" "}
              {p.unidad_anterior} → <b>{p.cantidad_nueva} {p.unidad_nueva}</b>
            </Text>
          ))}
          <Text size="xs" c="dimmed">
            Pidió {pendiente.solicitado_por_nombre} · {fechaHora(pendiente.creado_en)}
            {pendiente.comentario_solicitante ? ` · “${pendiente.comentario_solicitante}”` : ""}
          </Text>
        </div>
        <Table withTableBorder withColumnBorders fz="xs">
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Opción</Table.Th>
              <Table.Th>Partida</Table.Th>
              <Table.Th>Antes</Table.Th>
              <Table.Th>Después</Table.Th>
              <Table.Th w={120}>Precio unitario</Table.Th>
              <Table.Th w={130}>Tiempo entrega</Table.Th>
              <Table.Th>Importe nuevo</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {editor.map((f, i) => (
              <Table.Tr key={`${f.letra}-${f.partida_id}`}>
                <Table.Td>
                  <Badge size="sm" variant="light">
                    {f.letra}
                  </Badge>
                </Table.Td>
                <Table.Td>
                  {f.num}. {f.descripcion}
                </Table.Td>
                <Table.Td>
                  {f.precioActual ?? "—"} {f.moneda ?? ""}
                  {f.unidadCambia && (
                    <Text span size="xs" c="red">
                      {" "}
                      (inválido: cambia la unidad)
                    </Text>
                  )}
                </Table.Td>
                <Table.Td>
                  {f.cantidadNueva} {f.unidadNueva}
                </Table.Td>
                <Table.Td>
                  <TextInput
                    size="xs"
                    value={f.precio}
                    error={f.unidadCambia && !(Number(f.precio) > 0)}
                    onChange={(e) => setCampo(i, "precio", e.currentTarget.value)}
                  />
                </Table.Td>
                <Table.Td>
                  <TextInput
                    size="xs"
                    value={f.tiempo}
                    onChange={(e) => setCampo(i, "tiempo", e.currentTarget.value)}
                  />
                </Table.Td>
                <Table.Td>
                  {importe(f) !== null ? `${importe(f)} ${f.moneda ?? ""}` : "—"}
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
        {error && <Alert color="red">{error}</Alert>}
        <Group justify="flex-end">
          <Button variant="outline" color="red" onClick={abrirRechazo}>
            Rechazar
          </Button>
          <Button color="acento.6" loading={aprobar.isPending} onClick={ejecutarAprobar}>
            Aprobar con estos ajustes
          </Button>
        </Group>
      </Stack>
    </Alert>
  );
}
