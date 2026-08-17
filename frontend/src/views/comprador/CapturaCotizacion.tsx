/** Captura del comprador (F8b): partidas siempre visibles + editor de
 * opciones A–E con RENGLÓN RICO — cantidad/unidad cotizadas precargadas de la
 * partida, proveedor POR RENGLÓN, "No encontrada" y "Alternativa". Importes y
 * totales locales solo como referencia: tras guardar mandan los del servidor.
 * Los 422 de cotizar se pintan exactamente en su opción/partida/campo.
 *
 * Nota (bugs F8a): los handlers capturan e.currentTarget.value en una
 * variable ANTES de setState — dentro del updater el evento ya está muerto
 * (currentTarget null): así tronaban proveedor y comentarios. */

import {
  Alert,
  Badge,
  Button,
  Checkbox,
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
import { useAuth } from "../../auth/AuthContext";
import { BannerCambioComprador } from "../../components/Cambios";
import { SeccionComprobante } from "../../components/Comprobante";
import { BotonImprimir, HojaImpresion, ROLES_IMPRIMEN } from "../../components/Impresion";
import { SeccionFincada, VistaPedido } from "../../components/Pedido";
import { BadgeEstado, SemaforoBanda } from "../../components/compartidos";
import { VolverBoton } from "../../components/Volver";
import { ApiError } from "../../lib/api";
import { dinero, folioCliente } from "../../lib/format";
import {
  UNIDADES,
  aplicarNoEncontrada,
  renglonABody,
  validarRenglonLocal,
  type RenglonForm,
} from "../../lib/renglon";
import type { Letra, Moneda, OpcionOut, SolicitudDetailOut, Unidad } from "../../lib/types";
import { parsearFaltantesCotizacion, type FaltanteCotizacion } from "../../lib/validacion";
import { HistorialComentarios } from "../vendedor/DetalleSolicitud";
import { ModalCapturaTC, ModalCorregirTCComprador, ModalCotizarConTC } from "./ModalesTC";

const LETRAS: Letra[] = ["A", "B", "C", "D", "E"];

interface OpcionForm {
  vigencia: string | null;
  comentarios: string;
  renglones: Record<number, RenglonForm>; // por partida_id
}

function formDesdeServidor(
  opcion: OpcionOut | undefined,
  solicitud: SolicitudDetailOut,
): OpcionForm {
  const renglones: Record<number, RenglonForm> = {};
  for (const p of solicitud.partidas) {
    // Cantidad y unidad COTIZADAS precargadas de lo pedido.
    renglones[p.id] = {
      cantidad: p.cantidad,
      unidad: p.unidad as Unidad,
      moneda: "MXN", // default de captura (F8c)
      precio: "",
      tiempo: "",
      proveedor: "",
      noEncontrada: false,
      esAlternativa: false,
      alternativaDescripcion: "",
      conObservacion: false,
      observacion: "",
    };
  }
  for (const r of opcion?.renglones ?? []) {
    renglones[r.partida_id] = {
      cantidad: r.cantidad,
      unidad: r.unidad,
      moneda: r.moneda ?? "MXN",
      precio: r.precio_unitario ?? "",
      tiempo: r.tiempo_entrega ?? "",
      proveedor: r.proveedor ?? "",
      noEncontrada: r.no_encontrada,
      esAlternativa: r.es_alternativa,
      alternativaDescripcion: r.alternativa_descripcion ?? "",
      conObservacion: r.con_observacion,
      observacion: r.observacion ?? "",
    };
  }
  return {
    vigencia: opcion?.vigencia ?? null,
    comentarios: opcion?.comentarios ?? "",
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
  const [form, setForm] = useState<OpcionForm>(() => formDesdeServidor(opcionServidor, solicitud));
  const [erroresLocales, setErroresLocales] = useState<Record<number, string>>({});
  const guardarOpcion = useGuardarOpcion(solicitud.id);

  // Tras cada guardado, el servidor es la verdad (totales incluidos).
  const serverKey = JSON.stringify(opcionServidor ?? null);
  useEffect(() => {
    setForm(formDesdeServidor(opcionServidor, solicitud));
    setErroresLocales({});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [serverKey]);

  const setRenglon = (partidaId: number, cambio: Partial<RenglonForm>) =>
    setForm((f) => ({
      ...f,
      renglones: {
        ...f.renglones,
        [partidaId]: { ...(f.renglones[partidaId] as RenglonForm), ...cambio },
      },
    }));

  const misErrores = errores.filter((e) => e.letra === letra);
  const errorDe = (campo: FaltanteCotizacion["campo"], numPartida?: number) =>
    misErrores.some((e) => e.campo === campo && (e.num_partida ?? undefined) === numPartida)
      ? "Obligatorio para cotizar"
      : undefined;

  // Referencia local POR MONEDA; los totales reales los da el servidor.
  const totalesLocales = solicitud.partidas.reduce(
    (acc, p) => {
      const r = form.renglones[p.id];
      if (!r || r.noEncontrada) return acc;
      const precio = Number(r.precio);
      const cantidad = Number(r.cantidad);
      if (!precio || Number.isNaN(precio) || Number.isNaN(cantidad)) return acc;
      acc[r.moneda] += precio * cantidad;
      return acc;
    },
    { MXN: 0, USD: 0 } as Record<Moneda, number>,
  );

  const guardar = (tipoCambio?: string) => {
    const locales: Record<number, string> = {};
    for (const p of solicitud.partidas) {
      const error = validarRenglonLocal(form.renglones[p.id] as RenglonForm);
      if (error) locales[p.id] = error;
    }
    setErroresLocales(locales);
    if (Object.keys(locales).length > 0) return;
    guardarOpcion.mutate(
      {
        letra,
        body: {
          vigencia: form.vigencia,
          comentarios: form.comentarios.trim() || null,
          renglones: solicitud.partidas.map((p) =>
            renglonABody(p.id, form.renglones[p.id] as RenglonForm),
          ),
          ...(tipoCambio !== undefined ? { tipo_cambio: tipoCambio } : {}),
        },
      },
      {
        onSuccess: () => {
          notifications.show({ message: `Opción ${letra} guardada`, color: "green" });
          onGuardado();
        },
        // F10.3: la corrección que introduce USD sin TC exige capturarlo AQUÍ
        // (el toast global explica el porqué; el modal lo captura y reintenta).
        onError: (e) => {
          if (e instanceof ApiError && e.code === "tipo_cambio_requerido") {
            modals.open({
              title: "Tipo de cambio requerido",
              children: (
                <ModalCapturaTC
                  mensaje="La corrección introduce renglones en USD y la cotización no tiene tipo de cambio: captúralo para aplicar la corrección."
                  onAceptar={(tc) => {
                    modals.closeAll();
                    guardar(tc);
                  }}
                />
              ),
            });
          }
        },
      },
    );
  };

  const atajoVigencia = (dias: number) =>
    setForm((f) => ({ ...f, vigencia: dayjs().add(dias, "day").format("YYYY-MM-DD") }));

  return (
    <Stack gap="sm" mt="sm">
      <Group align="flex-end" gap="sm">
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
      </Group>
      <Table withTableBorder withColumnBorders verticalSpacing="xs">
        <Table.Thead>
          <Table.Tr>
            <Table.Th w={40}>No.</Table.Th>
            <Table.Th>Pedido</Table.Th>
            <Table.Th w={110}>Cantidad</Table.Th>
            <Table.Th w={150}>Unidad</Table.Th>
            <Table.Th w={100}>Moneda</Table.Th>
            <Table.Th w={130}>Precio unit.</Table.Th>
            <Table.Th w={130}>Entrega</Table.Th>
            <Table.Th w={170}>Proveedor</Table.Th>
            <Table.Th w={210}>Estatus</Table.Th>
            <Table.Th w={120}>Importe</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {solicitud.partidas.map((p) => {
            const r = form.renglones[p.id] as RenglonForm;
            const renglonServidor = opcionServidor?.renglones.find((x) => x.partida_id === p.id);
            const precioNum = Number(r.precio);
            const importeLocal =
              r.precio.trim() && !Number.isNaN(precioNum) && !Number.isNaN(Number(r.cantidad))
                ? precioNum * Number(r.cantidad)
                : null;
            const deshabilitado = r.noEncontrada;
            return (
              <Table.Tr
                key={p.id}
                bg={
                  r.noEncontrada
                    ? "var(--mantine-color-gray-1)"
                    : r.esAlternativa
                      ? "var(--mantine-color-orange-0)"
                      : r.conObservacion
                        ? "var(--mantine-color-blue-0)"
                        : undefined
                }
              >
                <Table.Td>{p.num_partida}</Table.Td>
                <Table.Td>
                  <Text size="sm">{p.descripcion}</Text>
                  <Text size="xs" c="dimmed">
                    pedido: {p.cantidad} {p.unidad}
                  </Text>
                </Table.Td>
                <Table.Td>
                  <TextInput
                    value={r.cantidad}
                    disabled={deshabilitado}
                    onChange={(e) => {
                      const v = e.currentTarget.value;
                      setRenglon(p.id, { cantidad: v });
                    }}
                  />
                </Table.Td>
                <Table.Td>
                  <Select
                    data={UNIDADES}
                    value={r.unidad}
                    disabled={deshabilitado}
                    allowDeselect={false}
                    onChange={(v) => setRenglon(p.id, { unidad: (v as Unidad) ?? r.unidad })}
                  />
                </Table.Td>
                <Table.Td>
                  <Select
                    data={["MXN", "USD"]}
                    value={r.moneda}
                    disabled={deshabilitado}
                    allowDeselect={false}
                    error={errorDe("moneda", p.num_partida)}
                    onChange={(v) => setRenglon(p.id, { moneda: (v as Moneda) ?? r.moneda })}
                  />
                </Table.Td>
                <Table.Td>
                  <TextInput
                    placeholder="0.0000"
                    value={r.precio}
                    disabled={deshabilitado}
                    error={errorDe("precio_unitario", p.num_partida)}
                    onChange={(e) => {
                      const v = e.currentTarget.value;
                      setRenglon(p.id, { precio: v });
                    }}
                  />
                </Table.Td>
                <Table.Td>
                  <TextInput
                    placeholder="p. ej. 1 semana"
                    value={r.tiempo}
                    disabled={deshabilitado}
                    error={errorDe("tiempo_entrega", p.num_partida)}
                    onChange={(e) => {
                      const v = e.currentTarget.value;
                      setRenglon(p.id, { tiempo: v });
                    }}
                  />
                </Table.Td>
                <Table.Td>
                  <TextInput
                    value={r.proveedor}
                    disabled={deshabilitado}
                    onChange={(e) => {
                      const v = e.currentTarget.value;
                      setRenglon(p.id, { proveedor: v });
                    }}
                  />
                </Table.Td>
                <Table.Td>
                  <Stack gap={4}>
                    <Checkbox
                      label="No encontrada"
                      size="xs"
                      checked={r.noEncontrada}
                      onChange={(e) => {
                        const activa = e.currentTarget.checked;
                        setRenglon(p.id, aplicarNoEncontrada(r, activa));
                      }}
                    />
                    <Checkbox
                      label="Alternativa"
                      size="xs"
                      checked={r.esAlternativa}
                      disabled={r.noEncontrada || r.conObservacion}
                      onChange={(e) => {
                        const activa = e.currentTarget.checked;
                        setRenglon(p.id, {
                          esAlternativa: activa,
                          ...(activa ? {} : { alternativaDescripcion: "" }),
                        });
                      }}
                    />
                    {r.esAlternativa && (
                      <Textarea
                        placeholder="¿Qué estás ofreciendo en su lugar?"
                        size="xs"
                        autosize
                        minRows={1}
                        value={r.alternativaDescripcion}
                        onChange={(e) => {
                          const v = e.currentTarget.value;
                          setRenglon(p.id, { alternativaDescripcion: v });
                        }}
                      />
                    )}
                    <Checkbox
                      label="Con observación"
                      size="xs"
                      checked={r.conObservacion}
                      disabled={r.noEncontrada || r.esAlternativa}
                      onChange={(e) => {
                        const activa = e.currentTarget.checked;
                        setRenglon(p.id, {
                          conObservacion: activa,
                          ...(activa ? {} : { observacion: "" }),
                        });
                      }}
                    />
                    {r.conObservacion && (
                      <Textarea
                        placeholder="Observación de esta partida (la verá el vendedor)"
                        size="xs"
                        autosize
                        minRows={1}
                        value={r.observacion}
                        onChange={(e) => {
                          const v = e.currentTarget.value;
                          setRenglon(p.id, { observacion: v });
                        }}
                      />
                    )}
                    {erroresLocales[p.id] && (
                      <Text size="xs" c="red">
                        {erroresLocales[p.id]}
                      </Text>
                    )}
                  </Stack>
                </Table.Td>
                <Table.Td>
                  {r.noEncontrada ? (
                    <Text size="sm" c="dimmed">
                      —
                    </Text>
                  ) : renglonServidor?.importe != null && renglonServidor.moneda ? (
                    <Text size="sm">{dinero(renglonServidor.importe, renglonServidor.moneda)}</Text>
                  ) : importeLocal !== null ? (
                    <Text size="sm" c="dimmed">
                      ≈ {dinero(importeLocal, r.moneda)}
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
        onChange={(e) => {
          const v = e.currentTarget.value;
          setForm((f) => ({ ...f, comentarios: v }));
        }}
        autosize
        minRows={1}
      />
      <Group justify="space-between">
        <Group gap="xs">
          <Text fw={600}>Subtotales {opcionServidor ? "(servidor)" : "(referencia)"}:</Text>
          {opcionServidor ? (
            <Text fw={700} c="herinox.7">
              {[
                Number(opcionServidor.total_mxn) > 0 ? dinero(opcionServidor.total_mxn, "MXN") : null,
                Number(opcionServidor.total_usd) > 0 ? dinero(opcionServidor.total_usd, "USD") : null,
              ]
                .filter(Boolean)
                .join(" + ") || dinero("0", "MXN")}
            </Text>
          ) : (
            <Text c="dimmed">
              ≈{" "}
              {[
                totalesLocales.MXN > 0 ? dinero(totalesLocales.MXN, "MXN") : null,
                totalesLocales.USD > 0 ? dinero(totalesLocales.USD, "USD") : null,
              ]
                .filter(Boolean)
                .join(" + ") || dinero(0, "MXN")}
            </Text>
          )}
        </Group>
        <Button onClick={() => guardar()} loading={guardarOpcion.isPending}>
          Guardar avance
        </Button>
      </Group>
    </Stack>
  );
}


// Exportado para el test de regresión F11 (el catálogo de motivos DEBE venir
// de /motivos-rechazo; con la ruta rota el Select queda vacío y el botón
// "Rechazar solicitud" jamás se habilita).
export function ModalRechazo({ solicitudId, onListo }: { solicitudId: number; onListo: () => void }) {
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
              // El error lo muestra el handler global (main.tsx).
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
  const { usuario } = useAuth();
  // F10.1 p.1: imprimir en LA pantalla del comprador (captura y pedido);
  // gcompras/admin también la usan vía /crm. El lado ventas, sin botón.
  const puedeImprimir = usuario !== null && ROLES_IMPRIMEN.includes(usuario.rol);
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
  const letrasVisibles = [
    ...new Set<Letra>([
      ...letrasUsadas,
      ...(letrasUsadas.length === 0 ? (["A"] as Letra[]) : []),
      ...(letraActiva && LETRAS.includes(letraActiva as Letra) ? [letraActiva as Letra] : []),
    ]),
  ].sort();

  const hayUsd = solicitud.opciones.some((o) => Number(o.total_usd) > 0);

  const ejecutarCotizar = (tipoCambio?: string) => {
    setErrores([]);
    setErrorGeneral(null);
    cotizar.mutate(tipoCambio, {
      onSuccess: (s) => {
        modals.closeAll();
        notifications.show({ message: `${s.folio} cotizada`, color: "green" });
      },
      onError: (e) => {
        modals.closeAll();
        if (e instanceof ApiError && e.code === "cotizacion_incompleta") {
          const faltantes = parsearFaltantesCotizacion(e.detail);
          setErrores(faltantes);
          const primera = faltantes[0];
          if (primera) setLetraActiva(primera.letra);
          setErrorGeneral(
            faltantes.length > 0
              ? "La cotización está incompleta: revisa los campos marcados."
              : e.detail,
          );
        } else if (e instanceof ApiError && e.code === "sin_opciones") {
          setErrorGeneral("Captura al menos una opción antes de marcar completa.");
        } else {
          setErrorGeneral(e instanceof ApiError ? e.detail : "No se pudo cotizar");
        }
      },
    });
  };

  const marcarCompleta = () => {
    // v3 (F8e): con renglones USD el TC es obligatorio — modal con el
    // consolidado por opción EN VIVO antes de aceptar.
    if (hayUsd) {
      modals.open({
        title: "Marcar cotización completa — tipo de cambio",
        children: (
          <ModalCotizarConTC
            opciones={solicitud.opciones}
            onAceptar={(tc) => ejecutarCotizar(tc)}
            cargando={cotizar.isPending}
          />
        ),
      });
      return;
    }
    ejecutarCotizar();
  };

  const abrirCorregirTC = () =>
    modals.open({
      title: "Corregir tipo de cambio",
      children: (
        <ModalCorregirTCComprador
          solicitudId={solicitud.id}
          tcActual={solicitud.tipo_cambio ?? null}
          opciones={solicitud.opciones}
          onListo={() => modals.closeAll()}
        />
      ),
    });

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
          // El error lo muestra el handler global (main.tsx).
          .catch(() => undefined),
    });

  return (
    <Stack>
      <Group justify="space-between">
        <Group>
          <VolverBoton />
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
          {puedeImprimir && <BotonImprimir />}
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

      <BannerCambioComprador solicitud={solicitud} />
      {correccion && !solicitud.cambio_pendiente && (
        <Alert color="orange" title="Estás corrigiendo una cotización ya publicada">
          <Group justify="space-between">
            <Text size="sm">Cada cambio guardado notifica al vendedor.</Text>
            {hayUsd && (
              <Button size="compact-sm" variant="light" color="orange" onClick={abrirCorregirTC}>
                Corregir TC (actual: {solicitud.tipo_cambio ?? "—"})
              </Button>
            )}
          </Group>
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
              <Button variant="light" size="compact-sm" onClick={() => setLetraActiva(siguienteLetra)}>
                + Agregar opción {siguienteLetra}
              </Button>
            )}
          </Group>
          <Tabs value={letraActiva} onChange={setLetraActiva}>
            <Tabs.List>
              {letrasVisibles.map((l) => (
                <Tabs.Tab key={l} value={l}>
                  Opción {l}
                  {letrasUsadas.includes(l) ? "" : " (nueva)"}
                </Tabs.Tab>
              ))}
            </Tabs.List>
            {letrasVisibles.map((l) => (
              <Tabs.Panel key={l} value={l}>
                <EditorOpcion
                  solicitud={solicitud}
                  letra={l}
                  errores={errores}
                  onGuardado={() => setErrores([])}
                />
                {letrasUsadas.includes(l) && letrasUsadas.length > 1 && (
                  <Group justify="flex-end" mt="xs">
                    <Button
                      variant="subtle"
                      color="red"
                      size="compact-sm"
                      onClick={() => confirmarEliminar(l)}
                    >
                      Eliminar opción {l}
                    </Button>
                  </Group>
                )}
              </Tabs.Panel>
            ))}
          </Tabs>
        </>
      )}

      {!capturable && solicitud.opciones.length > 0 && (
        <>
          {/* F12 p.5: fincado interno del área compras, sobre el pedido. */}
          <SeccionFincada solicitud={solicitud} />
          <VistaPedido solicitud={solicitud} />
        </>
      )}
      {/* F12 p.1: el comprador asignado SÍ puede descargar los comprobantes
          (el backend lo autoriza desde F8g) — la card faltaba en su vista de
          pedido; es la MISMA que ven gcompras/admin en el CRM. */}
      {!capturable && (
        <SeccionComprobante
          solicitudId={solicitud.id}
          comprobantes={solicitud.comprobantes}
          estado={solicitud.estado}
        />
      )}

      <HistorialComentarios solicitud={solicitud} />
      {/* Hoja de impresión (F10.1 p.1): lo SOLICITADO, como quedó; invisible
          en pantalla, lo único visible al imprimir (impresion.css). */}
      {puedeImprimir && <HojaImpresion solicitud={solicitud} />}
    </Stack>
  );
}
