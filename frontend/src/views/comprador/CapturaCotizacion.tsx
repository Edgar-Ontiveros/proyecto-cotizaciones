/** Captura del comprador: partidas siempre visibles + editor de opciones A–E
 * (tabs). Importes y totales se muestran calculados en pantalla como
 * referencia, pero tras guardar SIEMPRE se muestran los del servidor. Los 422
 * de cotizar se pintan exactamente en su opción/partida/campo. */

import {
  Alert,
  Badge,
  Button,
  Group,
  Paper,
  Select,
  Stack,
  Table,
  Tabs,
  Text,
  Textarea,
  TextInput,
  Title,
} from "@mantine/core";
import { DatePickerInput } from "@mantine/dates";
import { modals } from "@mantine/modals";
import { notifications } from "@mantine/notifications";
import dayjs from "dayjs";
import { useEffect, useMemo, useState } from "react";
import { useParams } from "react-router";

import {
  useAccionSolicitud,
  useCotizar,
  useEliminarOpcion,
  useGuardarOpcion,
  useMotivosRechazo,
  useRechazar,
  useSolicitud,
} from "../../api/hooks";
import { BadgeEstado, SemaforoBanda } from "../../components/compartidos";
import { ApiError } from "../../lib/api";
import { dinero, folioCliente } from "../../lib/format";
import type { Letra, Moneda, OpcionOut, SolicitudDetailOut } from "../../lib/types";
import { parsearFaltantesCotizacion, type FaltanteCotizacion } from "../../lib/validacion";
import { HistorialComentarios } from "../vendedor/DetalleSolicitud";

const LETRAS: Letra[] = ["A", "B", "C", "D", "E"];

interface RenglonForm {
  precio: string;
  tiempo: string;
}

interface OpcionForm {
  moneda: Moneda | null;
  vigencia: string | null;
  comentarios: string;
  proveedor: string;
  renglones: Record<number, RenglonForm>; // por partida_id
}

function formDesdeServidor(opcion: OpcionOut | undefined, partidaIds: number[]): OpcionForm {
  const renglones: Record<number, RenglonForm> = {};
  for (const pid of partidaIds) renglones[pid] = { precio: "", tiempo: "" };
  for (const r of opcion?.renglones ?? []) {
    renglones[r.partida_id] = { precio: r.precio_unitario ?? "", tiempo: r.tiempo_entrega ?? "" };
  }
  return {
    moneda: opcion?.moneda ?? null,
    vigencia: opcion?.vigencia ?? null,
    comentarios: opcion?.comentarios ?? "",
    proveedor: opcion?.proveedor ?? "",
    renglones,
  };
}

function EditorOpcion({
  solicitud,
  letra,
  errores,
  onGuardado,
}: {
  solicitud: SolicitudDetailOut;
  letra: Letra;
  errores: FaltanteCotizacion[];
  onGuardado: () => void;
}) {
  const opcionServidor = solicitud.opciones.find((o) => o.letra === letra);
  const partidaIds = useMemo(() => solicitud.partidas.map((p) => p.id), [solicitud.partidas]);
  const [form, setForm] = useState<OpcionForm>(() => formDesdeServidor(opcionServidor, partidaIds));
  const guardarOpcion = useGuardarOpcion(solicitud.id);

  // Tras cada guardado, el servidor es la verdad (totales incluidos).
  const serverKey = JSON.stringify(opcionServidor ?? null);
  useEffect(() => {
    setForm(formDesdeServidor(opcionServidor, partidaIds));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [serverKey]);

  const misErrores = errores.filter((e) => e.letra === letra);
  const errorDe = (campo: FaltanteCotizacion["campo"], numPartida?: number) =>
    misErrores.some((e) => e.campo === campo && (e.num_partida ?? undefined) === numPartida)
      ? "Obligatorio para cotizar"
      : undefined;

  // Referencia en pantalla; el total real lo da el servidor tras guardar.
  const totalLocal = solicitud.partidas.reduce((acc, p) => {
    const precio = Number(form.renglones[p.id]?.precio ?? "");
    if (!precio || Number.isNaN(precio)) return acc;
    return acc + precio * Number(p.cantidad);
  }, 0);

  const guardar = () => {
    const body = {
      moneda: form.moneda,
      vigencia: form.vigencia,
      comentarios: form.comentarios.trim() || null,
      proveedor: form.proveedor.trim() || null,
      renglones: solicitud.partidas.map((p) => ({
        partida_id: p.id,
        precio_unitario: form.renglones[p.id]?.precio.trim() || null,
        tiempo_entrega: form.renglones[p.id]?.tiempo.trim() || null,
      })),
    };
    guardarOpcion.mutate(
      { letra, body },
      {
        onSuccess: () => {
          notifications.show({ message: `Opción ${letra} guardada`, color: "green" });
          onGuardado();
        },
        onError: (e) =>
          notifications.show({
            message: e instanceof ApiError ? e.detail : "No se pudo guardar",
            color: "red",
          }),
      },
    );
  };

  const atajoVigencia = (dias: number) =>
    setForm((f) => ({ ...f, vigencia: dayjs().add(dias, "day").format("YYYY-MM-DD") }));

  return (
    <Stack gap="sm" mt="sm">
      <Group align="flex-end" gap="sm">
        <Select
          label="Moneda"
          data={["MXN", "USD"]}
          value={form.moneda}
          onChange={(v) => setForm((f) => ({ ...f, moneda: (v as Moneda) ?? null }))}
          error={errorDe("moneda")}
          w={110}
        />
        <DatePickerInput
          label="Vigencia"
          value={form.vigencia}
          onChange={(v) => setForm((f) => ({ ...f, vigencia: v }))}
          error={errorDe("vigencia")}
          w={170}
          clearable
        />
        <Button.Group>
          <Button variant="default" size="xs" onClick={() => atajoVigencia(7)}>
            +7 días
          </Button>
          <Button variant="default" size="xs" onClick={() => atajoVigencia(15)}>
            +15 días
          </Button>
          <Button variant="default" size="xs" onClick={() => atajoVigencia(30)}>
            +30 días
          </Button>
        </Button.Group>
        <TextInput
          label="Proveedor"
          description="Visible solo para compras"
          value={form.proveedor}
          onChange={(e) => setForm((f) => ({ ...f, proveedor: e.currentTarget.value }))}
          w={220}
        />
      </Group>
      <Table withTableBorder withColumnBorders>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>No.</Table.Th>
            <Table.Th>Descripción</Table.Th>
            <Table.Th>Cantidad</Table.Th>
            <Table.Th w={160}>Precio unitario</Table.Th>
            <Table.Th w={150}>Tiempo de entrega</Table.Th>
            <Table.Th w={130}>Importe</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {solicitud.partidas.map((p) => {
            const renglon = form.renglones[p.id] ?? { precio: "", tiempo: "" };
            const renglonServidor = opcionServidor?.renglones.find((r) => r.partida_id === p.id);
            const precioNum = Number(renglon.precio);
            const importeLocal =
              renglon.precio.trim() && !Number.isNaN(precioNum)
                ? precioNum * Number(p.cantidad)
                : null;
            return (
              <Table.Tr key={p.id}>
                <Table.Td>{p.num_partida}</Table.Td>
                <Table.Td>{p.descripcion}</Table.Td>
                <Table.Td>
                  {p.cantidad} {p.unidad}
                </Table.Td>
                <Table.Td>
                  <TextInput
                    placeholder="0.0000"
                    value={renglon.precio}
                    error={errorDe("precio_unitario", p.num_partida)}
                    onChange={(e) => {
                      const v = e.currentTarget.value;
                      setForm((f) => ({
                        ...f,
                        renglones: { ...f.renglones, [p.id]: { ...renglon, precio: v } },
                      }));
                    }}
                  />
                </Table.Td>
                <Table.Td>
                  <TextInput
                    placeholder="p. ej. 1 semana"
                    value={renglon.tiempo}
                    error={errorDe("tiempo_entrega", p.num_partida)}
                    onChange={(e) => {
                      const v = e.currentTarget.value;
                      setForm((f) => ({
                        ...f,
                        renglones: { ...f.renglones, [p.id]: { ...renglon, tiempo: v } },
                      }));
                    }}
                  />
                </Table.Td>
                <Table.Td>
                  {renglonServidor?.importe !== null &&
                  renglonServidor?.importe !== undefined &&
                  form.moneda ? (
                    <Text size="sm">{dinero(renglonServidor.importe, form.moneda)}</Text>
                  ) : importeLocal !== null && form.moneda ? (
                    <Text size="sm" c="dimmed">
                      ≈ {dinero(importeLocal, form.moneda)}
                    </Text>
                  ) : (
                    "—"
                  )}
                </Table.Td>
              </Table.Tr>
            );
          })}
        </Table.Tbody>
      </Table>
      <Textarea
        label="Comentarios de la opción"
        value={form.comentarios}
        onChange={(e) => setForm((f) => ({ ...f, comentarios: e.currentTarget.value }))}
        autosize
        minRows={1}
      />
      <Group justify="space-between">
        <Group gap="xs">
          <Text fw={600}>Total {opcionServidor ? "(servidor)" : "(referencia)"}:</Text>
          {opcionServidor && form.moneda ? (
            <Text fw={700} c="herinox.7">
              {dinero(opcionServidor.total, form.moneda)}
            </Text>
          ) : form.moneda ? (
            <Text c="dimmed">≈ {dinero(totalLocal, form.moneda)}</Text>
          ) : (
            <Text c="dimmed">captura la moneda</Text>
          )}
        </Group>
        <Button onClick={guardar} loading={guardarOpcion.isPending}>
          Guardar avance
        </Button>
      </Group>
    </Stack>
  );
}

function ModalRechazo({ solicitudId, onListo }: { solicitudId: number; onListo: () => void }) {
  const { data: motivos } = useMotivosRechazo();
  const rechazar = useRechazar(solicitudId);
  const [motivoId, setMotivoId] = useState<string | null>(null);
  const [comentario, setComentario] = useState("");

  const grupos = useMemo(() => {
    const activos = (motivos ?? []).filter((m) => m.activo);
    return [
      {
        group: "Falta información (se espera corrección)",
        items: activos
          .filter((m) => m.familia === "falta_informacion")
          .map((m) => ({ value: String(m.id), label: m.texto })),
      },
      {
        group: "No procede",
        items: activos
          .filter((m) => m.familia === "no_procede")
          .map((m) => ({ value: String(m.id), label: m.texto })),
      },
    ];
  }, [motivos]);

  return (
    <Stack>
      <Select
        label="Motivo del catálogo"
        placeholder="Elige el motivo"
        data={grupos}
        value={motivoId}
        onChange={setMotivoId}
        searchable
      />
      <Textarea
        label="Comentario (opcional)"
        value={comentario}
        onChange={(e) => setComentario(e.currentTarget.value)}
      />
      <Button
        color="red"
        disabled={motivoId === null}
        loading={rechazar.isPending}
        onClick={() => {
          rechazar.mutate(
            { motivo_id: Number(motivoId), comentario: comentario.trim() || null },
            {
              onSuccess: () => {
                notifications.show({ message: "Solicitud rechazada", color: "red" });
                onListo();
              },
              onError: (e) =>
                notifications.show({
                  message: e instanceof ApiError ? e.detail : "No se pudo rechazar",
                  color: "red",
                }),
            },
          );
        }}
      >
        Rechazar solicitud
      </Button>
    </Stack>
  );
}

export function CapturaCotizacion() {
  const { id } = useParams();
  const solicitudId = Number(id);
  const { data: solicitud } = useSolicitud(solicitudId);
  const tomar = useAccionSolicitud("tomar");
  const cotizar = useCotizar(solicitudId);
  const eliminarOpcion = useEliminarOpcion(solicitudId);
  const [letraActiva, setLetraActiva] = useState<string | null>("A");
  const [errores, setErrores] = useState<FaltanteCotizacion[]>([]);
  const [errorGeneral, setErrorGeneral] = useState<string | null>(null);

  if (!solicitud) return null;

  const capturable = ["ENVIADA", "EN_PROCESO", "COTIZADA"].includes(solicitud.estado);
  const correccion = solicitud.estado === "COTIZADA";
  const letrasUsadas = solicitud.opciones.map((o) => o.letra);
  const siguienteLetra = LETRAS.find((l) => !letrasUsadas.includes(l));
  // Tabs visibles: las capturadas + (si cabe) la siguiente para agregar.
  const letrasVisibles = LETRAS.filter(
    (l) => letrasUsadas.includes(l) || l === (letrasUsadas.length === 0 ? "A" : undefined),
  );

  const marcarCompleta = () => {
    setErrores([]);
    setErrorGeneral(null);
    cotizar.mutate(undefined, {
      onSuccess: (s) => notifications.show({ message: `${s.folio} cotizada`, color: "green" }),
      onError: (e) => {
        if (e instanceof ApiError && e.code === "cotizacion_incompleta") {
          const faltantes = parsearFaltantesCotizacion(e.detail);
          setErrores(faltantes);
          const primera = faltantes[0];
          if (primera) setLetraActiva(primera.letra);
          setErrorGeneral("La cotización está incompleta: revisa los campos marcados.");
        } else if (e instanceof ApiError && e.code === "sin_opciones") {
          setErrorGeneral("Captura al menos una opción antes de marcar completa.");
        } else {
          setErrorGeneral(e instanceof ApiError ? e.detail : "No se pudo cotizar");
        }
      },
    });
  };

  const abrirRechazo = () =>
    modals.open({
      title: "Rechazar con motivo",
      children: <ModalRechazo solicitudId={solicitud.id} onListo={() => modals.closeAll()} />,
    });

  const confirmarEliminar = (letra: Letra) =>
    modals.openConfirmModal({
      title: `Eliminar la opción ${letra}`,
      children: <Text size="sm">Se borrará la opción {letra} con todos sus renglones.</Text>,
      labels: { confirm: "Eliminar", cancel: "Volver" },
      confirmProps: { color: "red" },
      onConfirm: () =>
        void eliminarOpcion
          .mutateAsync(letra)
          .then(() => setLetraActiva("A"))
          .catch((e: unknown) =>
            notifications.show({
              message: e instanceof ApiError ? e.detail : "No se pudo eliminar",
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
            <Badge color="acento.6" variant="filled">
              URGENTE
            </Badge>
          )}
        </Group>
        <Group>
          {solicitud.estado === "ENVIADA" && (
            <Button variant="light" onClick={() => tomar.mutate(solicitud.id)}>
              Tomar
            </Button>
          )}
          {(solicitud.estado === "ENVIADA" || solicitud.estado === "EN_PROCESO") && (
            <>
              <Button variant="outline" color="red" onClick={abrirRechazo}>
                Rechazar
              </Button>
              <Button color="acento.6" onClick={marcarCompleta} loading={cotizar.isPending}>
                Marcar cotización completa
              </Button>
            </>
          )}
        </Group>
      </Group>

      {correccion && (
        <Alert color="orange" title="Estás corrigiendo una cotización ya publicada">
          Cada cambio guardado notifica al vendedor.
        </Alert>
      )}
      {errorGeneral && <Alert color="red">{errorGeneral}</Alert>}
      {solicitud.notas && (
        <Paper withBorder p="sm">
          <Text size="sm">
            <b>Notas del vendedor:</b> {solicitud.notas}
          </Text>
        </Paper>
      )}

      <Title order={5}>Partidas solicitadas</Title>
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

      {capturable && (
        <>
          <Group justify="space-between">
            <Title order={5}>Opciones de cotización</Title>
            {siguienteLetra && letrasUsadas.length > 0 && (
              <Button
                variant="light"
                size="compact-sm"
                onClick={() => setLetraActiva(siguienteLetra)}
              >
                + Agregar opción {siguienteLetra}
              </Button>
            )}
          </Group>
          <Tabs value={letraActiva} onChange={setLetraActiva}>
            <Tabs.List>
              {[...new Set([...letrasVisibles, ...(letraActiva ? [letraActiva as Letra] : [])])]
                .sort()
                .map((l) => (
                  <Tabs.Tab key={l} value={l}>
                    Opción {l}
                    {letrasUsadas.includes(l as Letra) ? "" : " (nueva)"}
                  </Tabs.Tab>
                ))}
            </Tabs.List>
            {[...new Set([...letrasVisibles, ...(letraActiva ? [letraActiva as Letra] : [])])].map(
              (l) => (
                <Tabs.Panel key={l} value={l}>
                  <EditorOpcion
                    solicitud={solicitud}
                    letra={l as Letra}
                    errores={errores}
                    onGuardado={() => setErrores([])}
                  />
                  {letrasUsadas.includes(l as Letra) && letrasUsadas.length > 1 && (
                    <Group justify="flex-end" mt="xs">
                      <Button
                        variant="subtle"
                        color="red"
                        size="compact-sm"
                        onClick={() => confirmarEliminar(l as Letra)}
                      >
                        Eliminar opción {l}
                      </Button>
                    </Group>
                  )}
                </Tabs.Panel>
              ),
            )}
          </Tabs>
        </>
      )}

      <HistorialComentarios solicitud={solicitud} />
    </Stack>
  );
}
