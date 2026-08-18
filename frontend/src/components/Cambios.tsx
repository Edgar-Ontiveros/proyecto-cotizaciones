/** Flujo de cambios de PARTIDAS post-cotización (F8h, ampliado en F13, §4.8b).
 *
 * - ModalSolicitarCambio + BannerCambioVendedor: lado ventas (comparador).
 *   Editor completo sobre las partidas actuales: modificar descripción/
 *   cantidad/unidad en línea, AGREGAR partidas nuevas (precio lo pone compras)
 *   y ELIMINAR con marca reversible; resumen del diff antes de enviar.
 * - BannerCambioComprador: diff campo por campo (modificadas en ámbar, nuevas
 *   en verde, eliminadas tachadas en rojo) + captura obligatoria del precio de
 *   los renglones nuevos y ajuste de los afectados; Aprobar / Rechazar.
 * Cantidades/unidades/descripciones no son dinero; los precios solo aparecen
 * del lado que ya los ve (las opciones del rol).
 */

import {
  Alert,
  Badge,
  Button,
  Checkbox,
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
import { useMemo, useRef, useState } from "react";

import {
  useAprobarCambio,
  useRechazarCambio,
  useRetirarCambio,
  useSolicitarCambio,
  type AjusteBody,
  type NuevoRenglonBody,
} from "../api/hooks";
import { useAuth } from "../auth/AuthContext";
import { ApiError } from "../lib/api";
import {
  altaConDatos,
  construirCambio,
  filaModificada,
  nuevoRenglonBody,
  renglonFormVacio,
  type FilaAltaEditor,
  type FilaPartidaEditor,
} from "../lib/cambios";
import { fechaHora } from "../lib/format";
import { aplicarNoEncontrada, armarAjustes, validarRenglonLocal, type RenglonForm } from "../lib/renglon";
import { ModalCapturaTC } from "../views/comprador/ModalesTC";
import type { CambioPartidaOut, OpcionOut, SolicitudDetailOut, Unidad } from "../lib/types";

const UNIDADES: Unidad[] = ["PZ", "KG", "TON", "MTS", "M2"];

/** Una línea del diff para los banners (texto según el tipo de renglón). */
function DiffLinea({ p }: { p: CambioPartidaOut }) {
  if (p.tipo === "ALTA") {
    return (
      <Text size="sm">
        <Badge size="sm" color="green" variant="light" mr={6}>
          Nueva
        </Badge>
        {p.descripcion}: <b>{p.cantidad_nueva} {p.unidad_nueva}</b>
      </Text>
    );
  }
  if (p.tipo === "BAJA") {
    return (
      <Text size="sm">
        <Badge size="sm" color="red" variant="light" mr={6}>
          Baja
        </Badge>
        <Text span td="line-through" c="dimmed">
          Partida {p.num_partida} ({p.descripcion})
        </Text>
      </Text>
    );
  }
  return (
    <Text size="sm">
      <Badge size="sm" color="yellow" variant="light" mr={6}>
        Modifica
      </Badge>
      <b>Partida {p.num_partida}</b> ({p.descripcion}): {p.cantidad_anterior} {p.unidad_anterior} →{" "}
      <b>
        {p.cantidad_nueva} {p.unidad_nueva}
      </b>
      {p.descripcion_nueva ? (
        <Text span size="xs" c="dimmed">
          {" "}
          · nueva descr.: “{p.descripcion_nueva}”
        </Text>
      ) : null}
    </Text>
  );
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
  const [existentes, setExistentes] = useState<FilaPartidaEditor[]>(
    solicitud.partidas.map((p) => ({
      partida_id: p.id,
      num: p.num_partida,
      descripcionOriginal: p.descripcion,
      cantidadOriginal: p.cantidad,
      unidadOriginal: p.unidad,
      descripcion: p.descripcion,
      cantidad: p.cantidad,
      unidad: p.unidad,
      eliminar: false,
    })),
  );
  const [altas, setAltas] = useState<FilaAltaEditor[]>([]);
  const proximaKey = useRef(1);

  const setExistente = (i: number, campo: "descripcion" | "cantidad" | "unidad", valor: string) =>
    setExistentes((prev) =>
      prev.map((f, j) => (j === i ? { ...f, [campo]: valor } : f)),
    );
  const toggleEliminar = (i: number) =>
    setExistentes((prev) => prev.map((f, j) => (j === i ? { ...f, eliminar: !f.eliminar } : f)));
  const setAlta = (i: number, campo: "descripcion" | "cantidad" | "unidad", valor: string) =>
    setAltas((prev) => prev.map((a, j) => (j === i ? { ...a, [campo]: valor } : a)));
  const agregarAlta = () =>
    setAltas((prev) => [
      ...prev,
      { key: proximaKey.current++, descripcion: "", cantidad: "", unidad: "PZ" },
    ]);
  const quitarAlta = (key: number) => setAltas((prev) => prev.filter((a) => a.key !== key));

  const resumen = useMemo(() => {
    const mod = existentes.filter(filaModificada).length;
    const baja = existentes.filter((f) => f.eliminar).length;
    const alta = altas.filter(altaConDatos).length;
    return { mod, baja, alta };
  }, [existentes, altas]);

  const enviar = () => {
    const { partidas, error: err } = construirCambio(existentes, altas);
    if (err) {
      setError(err);
      return;
    }
    solicitar.mutate(
      { comentario: comentario.trim() || null, partidas },
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
        Modifica descripción, cantidad o unidad en línea; agrega partidas nuevas
        (el precio lo definirá compras) o marca las que quieras eliminar. El
        comprador verá el antes→después y capturará los precios al aprobar.
        Mientras esté pendiente no podrás confirmar.
      </Text>
      <Table withTableBorder withColumnBorders>
        <Table.Thead>
          <Table.Tr>
            <Table.Th w={40}>No.</Table.Th>
            <Table.Th>Descripción</Table.Th>
            <Table.Th w={110}>Cantidad</Table.Th>
            <Table.Th w={90}>Unidad</Table.Th>
            <Table.Th w={110} />
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {existentes.map((f, i) => (
            <Table.Tr
              key={f.partida_id}
              bg={
                f.eliminar
                  ? "var(--mantine-color-red-0)"
                  : filaModificada(f)
                    ? "var(--mantine-color-yellow-0)"
                    : undefined
              }
            >
              <Table.Td>{f.num}</Table.Td>
              <Table.Td>
                <TextInput
                  value={f.descripcion}
                  disabled={f.eliminar}
                  styles={f.eliminar ? { input: { textDecoration: "line-through" } } : undefined}
                  onChange={(e) => setExistente(i, "descripcion", e.currentTarget.value)}
                />
              </Table.Td>
              <Table.Td>
                <TextInput
                  value={f.cantidad}
                  disabled={f.eliminar}
                  onChange={(e) => setExistente(i, "cantidad", e.currentTarget.value)}
                />
              </Table.Td>
              <Table.Td>
                <Select
                  data={UNIDADES}
                  allowDeselect={false}
                  disabled={f.eliminar}
                  value={f.unidad}
                  onChange={(v) => setExistente(i, "unidad", v ?? f.unidad)}
                />
              </Table.Td>
              <Table.Td>
                <Button
                  size="compact-xs"
                  variant="light"
                  color={f.eliminar ? "gray" : "red"}
                  onClick={() => toggleEliminar(i)}
                >
                  {f.eliminar ? "Restaurar" : "Eliminar"}
                </Button>
              </Table.Td>
            </Table.Tr>
          ))}
          {altas.map((a, i) => (
            <Table.Tr key={`alta-${a.key}`} bg="var(--mantine-color-green-0)">
              <Table.Td>
                <Badge size="sm" color="green" variant="light">
                  Nueva
                </Badge>
              </Table.Td>
              <Table.Td>
                <TextInput
                  placeholder="Descripción de la partida nueva"
                  value={a.descripcion}
                  onChange={(e) => setAlta(i, "descripcion", e.currentTarget.value)}
                />
              </Table.Td>
              <Table.Td>
                <TextInput
                  value={a.cantidad}
                  onChange={(e) => setAlta(i, "cantidad", e.currentTarget.value)}
                />
              </Table.Td>
              <Table.Td>
                <Select
                  data={UNIDADES}
                  allowDeselect={false}
                  value={a.unidad}
                  onChange={(v) => setAlta(i, "unidad", (v as Unidad) ?? a.unidad)}
                />
              </Table.Td>
              <Table.Td>
                <Button
                  size="compact-xs"
                  variant="subtle"
                  color="gray"
                  onClick={() => quitarAlta(a.key)}
                >
                  Quitar
                </Button>
              </Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
      <Group justify="space-between">
        <Button size="compact-sm" variant="light" onClick={agregarAlta}>
          + Agregar partida
        </Button>
        <Text size="xs" c="dimmed">
          {resumen.mod} modifica · {resumen.alta} agrega · {resumen.baja} elimina
        </Text>
      </Group>
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
        Solicitar cambio de partidas
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
      <Alert color="yellow" title="Cambio de partidas pendiente de aprobación del comprador">
        <Group justify="space-between" align="flex-start">
          <Stack gap={2}>
            {ultimo.partidas.map((p) => (
              <DiffLinea key={p.id} p={p} />
            ))}
            {ultimo.comentario_solicitante && (
              <Text size="xs" c="dimmed">
                “{ultimo.comentario_solicitante}” — {ultimo.solicitado_por_nombre}
              </Text>
            )}
            <Text size="xs" c="dimmed">
              No se puede confirmar el pedido hasta que el comprador lo resuelva.
            </Text>
          </Stack>
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
      <Stack gap={2}>
        {ultimo.partidas.map((p) => (
          <DiffLinea key={p.id} p={p} />
        ))}
      </Stack>
      {ultimo.comentario_resolucion && (
        <Text size="sm" mt={4}>
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
  num: number | null;
  descripcion: string;
  moneda: string | null;
  cantidadNueva: string | null;
  unidadNueva: string | null;
  precioActual: string | null;
  tiempoActual: string;
  unidadCambia: boolean;
  precio: string;
  tiempo: string;
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

/** Editor compacto de un renglón NUEVO (ALTA) en una opción: precio + moneda +
 * entrega, o un estatus (No encontrada / Alternativa / Con observación). */
function RenglonNuevoEditor({
  form,
  onChange,
}: {
  form: RenglonForm;
  onChange: (r: RenglonForm) => void;
}) {
  const set = (cambio: Partial<RenglonForm>) => onChange({ ...form, ...cambio });
  return (
    <Stack gap={4}>
      <Group gap={6} wrap="nowrap">
        <Select
          size="xs"
          w={80}
          data={["MXN", "USD"]}
          allowDeselect={false}
          disabled={form.noEncontrada}
          value={form.moneda}
          onChange={(v) => set({ moneda: (v as RenglonForm["moneda"]) ?? form.moneda })}
        />
        <TextInput
          size="xs"
          w={100}
          placeholder="Precio"
          disabled={form.noEncontrada}
          value={form.precio}
          onChange={(e) => set({ precio: e.currentTarget.value })}
        />
        <TextInput
          size="xs"
          placeholder="Tiempo entrega"
          disabled={form.noEncontrada}
          value={form.tiempo}
          onChange={(e) => set({ tiempo: e.currentTarget.value })}
        />
        <TextInput
          size="xs"
          placeholder="Proveedor"
          disabled={form.noEncontrada}
          value={form.proveedor}
          onChange={(e) => set({ proveedor: e.currentTarget.value })}
        />
      </Group>
      <Group gap="md">
        <Checkbox
          size="xs"
          label="No encontrada"
          checked={form.noEncontrada}
          onChange={(e) => onChange(aplicarNoEncontrada(form, e.currentTarget.checked))}
        />
        <Checkbox
          size="xs"
          label="Alternativa"
          disabled={form.noEncontrada}
          checked={form.esAlternativa}
          onChange={(e) => set({ esAlternativa: e.currentTarget.checked })}
        />
        <Checkbox
          size="xs"
          label="Con observación"
          disabled={form.noEncontrada}
          checked={form.conObservacion}
          onChange={(e) => set({ conObservacion: e.currentTarget.checked })}
        />
      </Group>
      {form.esAlternativa && (
        <TextInput
          size="xs"
          placeholder="Describe la alternativa"
          value={form.alternativaDescripcion}
          onChange={(e) => set({ alternativaDescripcion: e.currentTarget.value })}
        />
      )}
      {form.conObservacion && (
        <TextInput
          size="xs"
          placeholder="Observación de la partida"
          value={form.observacion}
          onChange={(e) => set({ observacion: e.currentTarget.value })}
        />
      )}
    </Stack>
  );
}

/** Banner del comprador con el diff y el editor de resolución (F13). */
export function BannerCambioComprador({ solicitud }: { solicitud: SolicitudDetailOut }) {
  const pendiente = solicitud.cambios.find((c) => c.estado_cambio === "PENDIENTE");
  const aprobar = useAprobarCambio(solicitud.id);
  const rechazar = useRechazarCambio(solicitud.id);
  const [error, setError] = useState<string | null>(null);
  const [filas, setFilas] = useState<FilaAjuste[] | null>(null);
  // Captura de partidas nuevas: por (cambio_partida_id + letra de opción).
  const [nuevos, setNuevos] = useState<Record<string, RenglonForm> | null>(null);

  const modificaciones = useMemo(
    () => pendiente?.partidas.filter((p) => p.tipo === "MODIFICACION") ?? [],
    [pendiente],
  );
  const altas = useMemo(() => pendiente?.partidas.filter((p) => p.tipo === "ALTA") ?? [], [pendiente]);
  const bajas = useMemo(() => pendiente?.partidas.filter((p) => p.tipo === "BAJA") ?? [], [pendiente]);

  // Filas de ajuste: cada opción × cada partida MODIFICADA con renglón vivo.
  const filasIniciales: FilaAjuste[] = useMemo(
    () =>
      solicitud.opciones.flatMap((o: OpcionOut) =>
        modificaciones.flatMap((p) => {
          const renglon = o.renglones.find((x) => x.partida_id === p.partida_id);
          if (!renglon || renglon.no_encontrada || p.partida_id === null) return [];
          const unidadCambia = (p.unidad_nueva ?? renglon.unidad) !== renglon.unidad;
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
              precio: unidadCambia ? "" : (renglon.precio_unitario ?? ""),
              tiempo: renglon.tiempo_entrega ?? "",
            },
          ];
        }),
      ),
    [solicitud.opciones, modificaciones],
  );

  // Formularios de captura de renglones nuevos (uno por alta × opción).
  const nuevosIniciales: Record<string, RenglonForm> = useMemo(() => {
    const acc: Record<string, RenglonForm> = {};
    for (const alta of altas) {
      for (const o of solicitud.opciones) {
        acc[`${alta.id}-${o.letra}`] = renglonFormVacio();
      }
    }
    return acc;
  }, [altas, solicitud.opciones]);

  if (!pendiente) return null;

  const editor = filas ?? filasIniciales;
  const capturas = nuevos ?? nuevosIniciales;
  const setCampo = (i: number, campo: "precio" | "tiempo", valor: string) =>
    setFilas(editor.map((f, j) => (j === i ? { ...f, [campo]: valor } : f)));
  const setCaptura = (clave: string, r: RenglonForm) =>
    setNuevos({ ...capturas, [clave]: r });

  const importeAjuste = (f: FilaAjuste) => {
    const precio = Number(f.precio);
    if (!(precio > 0) || !f.cantidadNueva) return null;
    return (Number(f.cantidadNueva) * precio).toFixed(2);
  };

  const ejecutarAprobar = () => {
    setError(null);
    for (const f of editor) {
      if (f.unidadCambia && !(Number(f.precio.trim()) > 0)) {
        setError(`Opción ${f.letra}, partida ${f.num}: la unidad cambia — captura el precio nuevo`);
        return;
      }
    }
    // Partidas nuevas: cada opción exige precio o un estatus (RF-7).
    const nuevosBody: NuevoRenglonBody[] = [];
    for (const alta of altas) {
      for (const o of solicitud.opciones) {
        const form = capturas[`${alta.id}-${o.letra}`] ?? renglonFormVacio();
        const err = validarRenglonLocal(form);
        if (err) {
          setError(`Opción ${o.letra}, ${alta.descripcion}: ${err}`);
          return;
        }
        const capturado = form.noEncontrada || form.precio.trim() !== "";
        if (!capturado) {
          setError(
            `Opción ${o.letra}, ${alta.descripcion}: captura el precio o marca un estatus`,
          );
          return;
        }
        nuevosBody.push(nuevoRenglonBody(alta.id, o.letra, form));
      }
    }
    const ajustes: AjusteBody[] = armarAjustes(editor);
    const mutar = (tipoCambio?: string) =>
      aprobar.mutate(
        { cambioId: pendiente.id, comentario: null, ajustes, nuevos: nuevosBody, tipoCambio },
        {
          onSuccess: () => notifications.show({ message: "Cambio aprobado", color: "green" }),
          onError: (e) => {
            if (e instanceof ApiError && e.code === "tipo_cambio_requerido") {
              modals.open({
                title: "Tipo de cambio requerido",
                children: (
                  <ModalCapturaTC
                    mensaje="El cambio introduce renglones en USD sin tipo de cambio: captúralo para autorizarlo."
                    onAceptar={(tc) => {
                      modals.closeAll();
                      mutar(tc);
                    }}
                  />
                ),
              });
              return;
            }
            setError(e instanceof ApiError ? e.detail : "No se pudo aprobar el cambio");
          },
        },
      );
    mutar();
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
    <Alert color="grape" title="Cambio de partidas pendiente de tu aprobación">
      <Stack gap="sm">
        <div>
          <Text size="xs" fw={600} tt="uppercase" c="dimmed" mb={4}>
            Lo que cambia
          </Text>
          <Stack gap={2}>
            {pendiente.partidas.map((p) => (
              <DiffLinea key={p.id} p={p} />
            ))}
          </Stack>
          <Text size="xs" c="dimmed" mt={4}>
            Pidió {pendiente.solicitado_por_nombre} · {fechaHora(pendiente.creado_en)}
            {pendiente.comentario_solicitante ? ` · “${pendiente.comentario_solicitante}”` : ""}
          </Text>
        </div>

        {editor.length > 0 && (
          <div>
            <Text size="xs" fw={600} tt="uppercase" c="dimmed" mb={4}>
              Renglones afectados (modificaciones)
            </Text>
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
                      {importeAjuste(f) !== null ? `${importeAjuste(f)} ${f.moneda ?? ""}` : "—"}
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </div>
        )}

        {altas.length > 0 && (
          <div>
            <Text size="xs" fw={600} tt="uppercase" c="dimmed" mb={4}>
              Precio de las partidas nuevas (obligatorio en cada opción)
            </Text>
            <Stack gap="xs">
              {solicitud.opciones.map((o) => (
                <div key={o.letra}>
                  <Text size="sm" fw={600}>
                    Opción {o.letra}
                  </Text>
                  {altas.map((alta) => (
                    <Group key={`${o.letra}-${alta.id}`} align="flex-start" wrap="nowrap" gap="sm" mt={4}>
                      <Text size="xs" w={160} style={{ flexShrink: 0 }}>
                        {alta.descripcion} · {alta.cantidad_nueva} {alta.unidad_nueva}
                      </Text>
                      <RenglonNuevoEditor
                        form={capturas[`${alta.id}-${o.letra}`] ?? renglonFormVacio()}
                        onChange={(r) => setCaptura(`${alta.id}-${o.letra}`, r)}
                      />
                    </Group>
                  ))}
                </div>
              ))}
            </Stack>
          </div>
        )}

        {bajas.length > 0 && (
          <Text size="xs" c="dimmed">
            Al aprobar se eliminarán {bajas.length} partida(s) y sus renglones en todas las opciones.
          </Text>
        )}

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
