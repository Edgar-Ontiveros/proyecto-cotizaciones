/** Comprobante de pedido (F8g).
 *
 * - SeccionComprobante: metadatos + descarga (roles con acceso al detalle).
 * - DropzoneComprobante: subir/reemplazar mientras la solicitud está en
 *   COTIZADA (lado ventas). La regla dura vive en el backend
 *   (422 comprobante_requerido al confirmar); aquí solo se guía el flujo.
 */

import { Alert, Button, Group, Paper, Text, Title } from "@mantine/core";
import { Dropzone } from "@mantine/dropzone";
import { notifications } from "@mantine/notifications";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { descargarComprobante, subirComprobante } from "../api/archivos";
import { ApiError } from "../lib/api";
import { fechaHora } from "../lib/format";
import type { ComprobanteOut } from "../lib/types";

const FORMATOS = ["application/pdf", "image/jpeg", "image/png", "image/webp"];
const MAX_BYTES = 10 * 1024 * 1024;

function tamano(bytes: number): string {
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

export function InfoComprobante({
  solicitudId,
  comprobante,
}: {
  solicitudId: number;
  comprobante: ComprobanteOut;
}) {
  const [descargando, setDescargando] = useState(false);
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
      <Button
        variant="light"
        size="compact-sm"
        loading={descargando}
        onClick={() => {
          setDescargando(true);
          descargarComprobante(solicitudId, comprobante.nombre_original)
            .catch((e: unknown) => {
              notifications.show({
                message: e instanceof ApiError ? e.detail : "No se pudo descargar el comprobante",
                color: "red",
              });
            })
            .finally(() => setDescargando(false));
        }}
      >
        Descargar
      </Button>
    </Group>
  );
}

/** Sección del DETALLE: solo informa (y descarga); sin dropzone. */
export function SeccionComprobante({
  solicitudId,
  comprobante,
}: {
  solicitudId: number;
  comprobante: ComprobanteOut | null;
}) {
  if (comprobante === null) return null;
  return (
    <Paper withBorder p="md">
      <Title order={5} mb="xs">
        Comprobante del pedido
      </Title>
      <InfoComprobante solicitudId={solicitudId} comprobante={comprobante} />
    </Paper>
  );
}

/** Dropzone OBLIGATORIA del flujo de confirmación (comparador): sin
 * comprobante no se habilita confirmar; con él, permite reemplazar. */
export function DropzoneComprobante({
  solicitudId,
  comprobante,
}: {
  solicitudId: number;
  comprobante: ComprobanteOut | null;
}) {
  const qc = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const subir = useMutation({
    mutationFn: (file: File) => subirComprobante(solicitudId, file),
    onSuccess: (nuevo) => {
      setError(null);
      notifications.show({
        message: `Comprobante ${comprobante ? "reemplazado" : "cargado"}: ${nuevo.nombre_original}`,
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
        Comprobante del cliente{" "}
        <Text span c="red" size="sm">
          (obligatorio para confirmar)
        </Text>
      </Title>
      {comprobante !== null && (
        <>
          <InfoComprobante solicitudId={solicitudId} comprobante={comprobante} />
          <Text size="xs" c="dimmed" mt={4} mb="xs">
            Puedes reemplazarlo mientras el pedido no esté confirmado.
          </Text>
        </>
      )}
      <Dropzone
        onDrop={(files) => {
          const file = files[0];
          if (file) subir.mutate(file);
        }}
        onReject={() =>
          setError("Archivo no aceptado: PDF, JPG, PNG o WebP de máximo 10 MB")
        }
        accept={FORMATOS}
        maxSize={MAX_BYTES}
        maxFiles={1}
        multiple={false}
        loading={subir.isPending}
        data-testid="dropzone-comprobante"
      >
        <Text ta="center" size="sm" c="dimmed" py="md">
          {comprobante
            ? "Arrastra aquí un archivo para REEMPLAZAR el comprobante"
            : "Arrastra aquí el comprobante del cliente o haz clic para elegirlo"}
          <br />
          PDF, JPG, PNG o WebP · máximo 10 MB
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
