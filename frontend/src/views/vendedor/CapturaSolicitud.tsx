/** Captura calcada al formato real (§6): encabezado automático + cliente con
 * alta al vuelo + prioridad + notas + tabla de partidas dinámica. Sirve para
 * nueva (borrador) y para editar (BORRADOR/ENVIADA/EN_PROCESO/RECHAZADA→
 * corregir-y-reenviar). */

import {
  ActionIcon,
  Alert,
  Autocomplete,
  Button,
  Group,
  Paper,
  SegmentedControl,
  Select,
  Stack,
  Table,
  Text,
  Textarea,
  TextInput,
  Title,
} from "@mantine/core";
import { useForm } from "@mantine/form";
import { modals } from "@mantine/modals";
import { notifications } from "@mantine/notifications";
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router";

import {
  useAccionSolicitud,
  useClientes,
  useCrearSolicitud,
  useEditarSolicitud,
  useSolicitud,
} from "../../api/hooks";
import { useAuth } from "../../auth/AuthContext";
import { VolverBoton } from "../../components/Volver";
import { ApiError } from "../../lib/api";
import { fecha } from "../../lib/format";
import { UNIDADES, corregirYReenviar } from "../../lib/renglon";
import {
  parsearFaltantesEnvio,
  resolverZod,
  solicitudSchema,
  type SolicitudForm,
} from "../../lib/validacion";

const PARTIDA_VACIA = {
  codigo_sap: "",
  cantidad: "",
  unidad: "PZ" as const,
  tipo_acero: "",
  descripcion: "",
  medidas: "",
};

function aBody(values: SolicitudForm) {
  return {
    cliente: values.cliente?.trim() ? values.cliente.trim() : null,
    prioridad: values.prioridad,
    notas: values.notas?.trim() ? values.notas.trim() : null,
    partidas: values.partidas.map((p) => ({
      codigo_sap: p.codigo_sap?.trim() ? p.codigo_sap.trim() : null,
      cantidad: p.cantidad.trim(),
      unidad: p.unidad.trim(),
      tipo_acero: p.tipo_acero?.trim() ? p.tipo_acero.trim() : null,
      descripcion: p.descripcion.trim(),
      medidas: p.medidas?.trim() ? p.medidas.trim() : null,
    })),
  };
}

export function CapturaSolicitud({ modo }: { modo: "nueva" | "editar" }) {
  const { id } = useParams();
  const solicitudId = modo === "editar" ? Number(id) : 0;
  const navigate = useNavigate();
  const { usuario } = useAuth();
  const { data: existente } = useSolicitud(solicitudId || 0);
  const crear = useCrearSolicitud();
  const editar = useEditarSolicitud(solicitudId);
  const enviar = useAccionSolicitud("enviar");
  const [errorGeneral, setErrorGeneral] = useState<string | null>(null);
  const [clienteTexto, setClienteTexto] = useState("");
  const { data: sugerencias } = useClientes(clienteTexto);

  const form = useForm<SolicitudForm>({
    initialValues: {
      cliente: "",
      prioridad: "NORMAL",
      notas: "",
      partidas: [{ ...PARTIDA_VACIA }],
    },
    validate: resolverZod(solicitudSchema),
  });

  // Editar: precarga desde el detalle (una sola vez al llegar los datos).
  const cargada = modo === "editar" && existente !== undefined;
  useEffect(() => {
    if (!cargada || !existente) return;
    form.setValues({
      cliente: existente.cliente_nombre ?? "",
      prioridad: existente.prioridad,
      notas: existente.notas ?? "",
      partidas: existente.partidas.map((p) => ({
        codigo_sap: p.codigo_sap ?? "",
        cantidad: p.cantidad,
        unidad: p.unidad,
        tipo_acero: p.tipo_acero ?? "",
        descripcion: p.descripcion,
        medidas: p.medidas ?? "",
      })),
    });
    setClienteTexto(existente.cliente_nombre ?? "");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cargada]);

  const esActiva = existente?.estado === "ENVIADA" || existente?.estado === "EN_PROCESO";

  const guardar = async (values: SolicitudForm, tambienEnviar: boolean) => {
    setErrorGeneral(null);
    try {
      const body = aBody(values);
      let guardadaId: number;
      if (modo === "editar" && existente?.estado === "RECHAZADA") {
        // Corregir-y-reenviar (F8b): PRIMERO la corrección (PATCH sobre la
        // RECHAZADA — evento en historial sin notificación) y DESPUÉS el
        // reenvío (ciclo nuevo, notifica al comprador).
        const reenviada = await corregirYReenviar({
          editar: () => editar.mutateAsync(body),
          enviar: () => enviar.mutateAsync(solicitudId),
        });
        guardadaId = solicitudId;
        notifications.show({ message: `Solicitud ${reenviada.folio} reenviada`, color: "green" });
      } else {
        const guardada =
          modo === "nueva" ? await crear.mutateAsync(body) : await editar.mutateAsync(body);
        guardadaId = guardada.id;
        if (tambienEnviar) {
          const enviada = await enviar.mutateAsync(guardada.id);
          notifications.show({ message: `Solicitud ${enviada.folio} enviada`, color: "green" });
        } else {
          notifications.show({ message: "Solicitud guardada", color: "green" });
        }
      }
      navigate(`/vendedor/solicitudes/${guardadaId}`);
    } catch (e) {
      if (e instanceof ApiError && e.code === "solicitud_incompleta") {
        // 422 de completitud del envío: campo por campo.
        const faltantes = parsearFaltantesEnvio(e.detail);
        if (faltantes.cliente) form.setFieldError("cliente", "El cliente es obligatorio para enviar");
        if (faltantes.partidas) setErrorGeneral("Se requiere al menos una partida para enviar");
        else if (!faltantes.cliente) setErrorGeneral(e.detail);
      } else {
        setErrorGeneral(e instanceof ApiError ? e.detail : "No se pudo guardar la solicitud");
      }
    }
  };

  const onSubmit = (tambienEnviar: boolean) =>
    form.onSubmit((values) => {
      if (modo === "editar" && esActiva) {
        modals.openConfirmModal({
          title: "Editar una solicitud activa",
          children: (
            <Text size="sm">
              Si el comprador ya empezó a capturar, su avance se descartará y se le notificará.
              ¿Continuar?
            </Text>
          ),
          labels: { confirm: "Sí, editar", cancel: "No" },
          confirmProps: { color: "acento.6" },
          onConfirm: () => void guardar(values, tambienEnviar),
        });
      } else {
        void guardar(values, tambienEnviar);
      }
    });

  return (
    <Stack>
      <Group>
        <VolverBoton />
        <Title order={3}>{modo === "nueva" ? "Nueva solicitud" : "Editar solicitud"}</Title>
      </Group>
      {existente?.estado === "RECHAZADA" && (
        <Alert color="red" title="Solicitud rechazada">
          Corrige lo necesario y reenvíala. Motivo:{" "}
          {existente.historial.filter((h) => h.a === "RECHAZADA").at(-1)?.motivo_texto ??
            "(sin motivo)"}
        </Alert>
      )}
      {errorGeneral && <Alert color="red">{errorGeneral}</Alert>}
      <Paper withBorder p="md">
        <Group gap="xl">
          <Text size="sm">
            <b>Folio:</b> {existente?.folio ?? "se asigna al enviar"}
          </Text>
          <Text size="sm">
            <b>Fecha:</b> {fecha(existente?.creado_en ?? new Date().toISOString())}
          </Text>
          <Text size="sm">
            <b>Vendedor:</b> {usuario?.nombre}
          </Text>
        </Group>
      </Paper>
      <Group align="flex-end" gap="md">
        <Autocomplete
          label="Cliente"
          description="Escribe para buscar; si no existe, se dará de alta al guardar"
          data={(sugerencias ?? []).map((c) => c.nombre_normalizado)}
          value={clienteTexto}
          onChange={(v) => {
            setClienteTexto(v);
            form.setFieldValue("cliente", v);
          }}
          error={form.errors.cliente}
          w={320}
        />
        <SegmentedControl
          data={[
            { value: "NORMAL", label: "Normal" },
            { value: "URGENTE", label: "URGENTE" },
          ]}
          {...form.getInputProps("prioridad")}
        />
      </Group>
      <Textarea label="Notas" autosize minRows={2} {...form.getInputProps("notas")} />

      <Title order={5}>Partidas</Title>
      <Table withTableBorder withColumnBorders>
        <Table.Thead>
          <Table.Tr>
            <Table.Th w={48}>No.</Table.Th>
            <Table.Th w={120}>Código SAP</Table.Th>
            <Table.Th w={100}>Cantidad</Table.Th>
            <Table.Th w={100}>Unidad</Table.Th>
            <Table.Th w={110}>Tipo de acero</Table.Th>
            <Table.Th>Descripción</Table.Th>
            <Table.Th w={140}>Medidas</Table.Th>
            <Table.Th w={48} />
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {form.values.partidas.map((_, i) => (
            <Table.Tr key={i}>
              <Table.Td>{i + 1}</Table.Td>
              <Table.Td>
                <TextInput
                  placeholder="SERVICIO si no hay"
                  {...form.getInputProps(`partidas.${i}.codigo_sap`)}
                />
              </Table.Td>
              <Table.Td>
                <TextInput {...form.getInputProps(`partidas.${i}.cantidad`)} />
              </Table.Td>
              <Table.Td>
                <Select
                  data={UNIDADES}
                  allowDeselect={false}
                  {...form.getInputProps(`partidas.${i}.unidad`)}
                />
              </Table.Td>
              <Table.Td>
                <TextInput {...form.getInputProps(`partidas.${i}.tipo_acero`)} />
              </Table.Td>
              <Table.Td>
                <TextInput {...form.getInputProps(`partidas.${i}.descripcion`)} />
              </Table.Td>
              <Table.Td>
                <TextInput {...form.getInputProps(`partidas.${i}.medidas`)} />
              </Table.Td>
              <Table.Td>
                <ActionIcon
                  color="red"
                  variant="subtle"
                  aria-label="Quitar partida"
                  disabled={form.values.partidas.length === 1}
                  onClick={() => form.removeListItem("partidas", i)}
                >
                  ✕
                </ActionIcon>
              </Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
      <Group>
        <Button variant="light" onClick={() => form.insertListItem("partidas", { ...PARTIDA_VACIA })}>
          + Agregar partida
        </Button>
      </Group>

      <Group justify="flex-end" mt="md">
        <Button variant="default" onClick={() => navigate(-1)}>
          Cancelar
        </Button>
        {(modo === "nueva" || existente?.estado === "BORRADOR") && (
          <Button variant="outline" onClick={() => onSubmit(false)()}>
            Guardar borrador
          </Button>
        )}
        {modo === "editar" && esActiva ? (
          <Button color="acento.6" onClick={() => onSubmit(false)()}>
            Guardar cambios
          </Button>
        ) : existente?.estado === "RECHAZADA" ? (
          <Button color="acento.6" onClick={() => onSubmit(true)()}>
            Guardar y reenviar
          </Button>
        ) : (
          <Button color="acento.6" onClick={() => onSubmit(true)()}>
            Guardar y enviar
          </Button>
        )}
      </Group>
    </Stack>
  );
}
