/** Comprobantes de pedido (F8g; F10 p.6: pueden ser VARIOS).
 *
 * - ListaComprobantes: nombre, quién, cuándo, descargar y eliminar (solo
 *   quien lo subió o admin, solo ANTES de confirmar).
 * - SeccionComprobante: la lista dentro del detalle (solo lectura + borrar
 *   cuando aplica).
 * - DropzoneComprobante: agrega uno o varios mientras la solicitud está en
 *   COTIZADA (lado ventas). La regla dura vive en el backend (422
 *   comprobante_requerido al confirmar con cero); aquí solo se guía el flujo.
 */

import { Alert, Button, Group, Paper, Stack, Text, Title } from "@mantine/core";
import { Dropzone } from "@mantine/dropzone";
import { modals } from "@mantine/modals";
import { notifications } from "@mantine/notifications";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { descargarComprobante, eliminarComprobante, subirComprobante } from "../api/archivos";
import { useAuth } from "../auth/AuthContext";
import { ApiError } from "../lib/api";
import { fechaHora } from "../lib/format";
import type { ComprobanteOut } from "../lib/types";

const FORMATOS = ["application/pdf", "image/jpeg", "image/png", "image/webp"];
const MAX_BYTES = 10 * 1024 * 1024;

function tamano(bytes: number): string {
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

function FilaComprobante({
  solicitudId,
  comprobante,
  puedeEliminar,
}: {
  solicitudId: number;
  comprobante: ComprobanteOut;
  puedeEliminar: boolean;
}) {
  const qc = useQueryClient();
  const [descargando, setDescargando] = useState(false);
  const eliminar = useMutation({
    mutationFn: () => eliminarComprobante(solicitudId, comprobante.id),
    onSuccess: () => {
      notifications.show({ message: "Comprobante eliminado", color: "gray" });
      void qc.invalidateQueries({ queryKey: ["solicitud", solicitudId] });
    },
    onError: (e: unknown) => {
      notifications.show({
        message: e instanceof ApiError ? e.detail : "No se pudo eliminar el comprobante",
        color: "red",
      });
    },
  });

  const confirmarEliminar = () =>
    modals.openConfirmModal({
      title: "Eliminar comprobante",
      children: (
        <Text size="sm">
          Se eliminará <b>{comprobante.nombre_original}</b> de forma definitiva.
        </Text>
      ),
      labels: { confirm: "Eliminar", cancel: "Volver" },
      confirmProps: { color: "red" },
      onConfirm: () => eliminar.mutate(),
    });

  return (
    <Group justify="space-between" wrap="nowrap">
      <div>
        <Text size="sm" fw={600}>
          {comprobante.nombre_original}{" "}
          <Text span size="xs" c="dimmed">
            ({tamano(comprobante.tamano_bytes)})
          </Text>
        </Text>
        <Text size="xs" c="dimmed">
          Subido por {comprobante.subido_por_nombre} · {fechaHora(comprobante.creado_en)}
        </Text>
      </div>
      <Group gap="xs" wrap="nowrap">
        <Button
          variant="light"
          size="compact-sm"
          loading={descargando}
          onClick={() => {
            setDescargando(true);
            descargarComprobante(solicitudId, comprobante.id, comprobante.nombre_original)
              .catch((e: unknown) => {
                notifications.show({
                  message:
                    e instanceof ApiError ? e.detail : "No se pudo descargar el comprobante",
                  color: "red",
                });
              })
              .finally(() => setDescargando(false));
          }}
        >
          Descargar
        </Button>
        {puedeEliminar && (
          <Button
            variant="subtle"
            color="red"
            size="compact-sm"
            loading={eliminar.isPending}
            onClick={confirmarEliminar}
          >
            Eliminar
          </Button>
        )}
      </Group>
    </Group>
  );
}

export function ListaComprobantes({
  solicitudId,
  comprobantes,
  estado,
}: {
  solicitudId: number;
  comprobantes: ComprobanteOut[];
  estado: string;
}) {
  const { usuario } = useAuth();
  // F10 p.6: eliminar SOLO antes de confirmar (COTIZADA) y solo quien lo
  // subió o admin — el backend es la autoridad (403/409); aquí se guía.
  const gestionable = estado === "COTIZADA" && usuario !== null;
  return (
    <Stack gap="xs">
      {comprobantes.map((c) => (
        <FilaComprobante
          key={c.id}
          solicitudId={solicitudId}
          comprobante={c}
          puedeEliminar={
            gestionable && (usuario.id === c.subido_por || usuario.rol === "admin")
          }
        />
      ))}
    </Stack>
  );
}

/** Sección del DETALLE: lista con descarga (y borrar cuando aplica). */
export function SeccionComprobante({
  solicitudId,
  comprobantes,
  estado,
}: {
  solicitudId: number;
  comprobantes: ComprobanteOut[];
  estado: string;
}) {
  if (comprobantes.length === 0) return null;
  return (
    <Paper withBorder p="md">
      <Title order={5} mb="xs">
        Comprobantes del pedido ({comprobantes.length})
      </Title>
      <ListaComprobantes solicitudId={solicitudId} comprobantes={comprobantes} estado={estado} />
    </Paper>
  );
}

/** Dropzone del flujo de confirmación (comparador): sin al menos UN
 * comprobante no se habilita confirmar; se pueden agregar varios. */
export function DropzoneComprobante({
  solicitudId,
  comprobantes,
  estado,
}: {
  solicitudId: number;
  comprobantes: ComprobanteOut[];
  estado: string;
}) {
  const qc = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const subir = useMutation({
    mutationFn: (file: File) => subirComprobante(solicitudId, file),
    onSuccess: (nuevo) => {
      setError(null);
      notifications.show({
        message: `Comprobante cargado: ${nuevo.nombre_original}`,
        color: "green",
      });
      void qc.invalidateQueries({ queryKey: ["solicitud", solicitudId] });
    },
    onError: (e: unknown) => {
      // Errores del backend (formato/tamaño/estado) pintados claros aquí.
      setError(e instanceof ApiError ? e.detail : "No se pudo subir el comprobante");
    },
  });

  return (
    <Paper withBorder p="md">
      <Title order={5} mb="xs">
        Comprobantes del cliente{" "}
        <Text span c="red" size="sm">
          (al menos uno para confirmar)
        </Text>
      </Title>
      {comprobantes.length > 0 && (
        <>
          <ListaComprobantes
            solicitudId={solicitudId}
            comprobantes={comprobantes}
            estado={estado}
          />
          <Text size="xs" c="dimmed" mt={4} mb="xs">
            Puedes agregar más o eliminar los tuyos mientras el pedido no esté confirmado.
          </Text>
        </>
      )}
      <Dropzone
        onDrop={(files) => files.forEach((file) => subir.mutate(file))}
        onReject={() =>
          setError("Archivo no aceptado: PDF, JPG, PNG o WebP de máximo 10 MB")
        }
        accept={FORMATOS}
        maxSize={MAX_BYTES}
        multiple
        loading={subir.isPending}
        data-testid="dropzone-comprobante"
      >
        <Text ta="center" size="sm" c="dimmed" py="md">
          {comprobantes.length > 0
            ? "Arrastra aquí más archivos para AGREGAR comprobantes"
            : "Arrastra aquí el comprobante del cliente o haz clic para elegirlo"}
          <br />
          PDF, JPG, PNG o WebP · máximo 10 MB cada uno
        </Text>
      </Dropzone>
      {error && (
        <Alert color="red" mt="xs">
          {error}
        </Alert>
      )}
    </Paper>
  );
}
