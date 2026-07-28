/** Flujo de BAJA SEGURA guiada (F8d): al desactivar, si el backend responde
 * 409 `baja_requiere_reasignacion`, este modal muestra el detalle y pide los
 * destinos que falten; reintenta TODO en un acto. */

import { Alert, Button, Select, Stack, Text } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useState } from "react";

import { type DesactivarBody, useDesactivarUsuario, useUsuarios } from "../../api/crmHooks";
import { ApiError } from "../../lib/api";
import { type RequisitosBaja, parseBajaSegura } from "../../lib/crm";
import type { UsuarioOut } from "../../lib/types";

export function ModalBajaSegura({
  usuario,
  detalle409,
  onListo,
}: {
  usuario: UsuarioOut;
  detalle409: string;
  onListo: () => void;
}) {
  const requisitos: RequisitosBaja = parseBajaSegura(detalle409);
  const [titularidadesA, setTitularidadesA] = useState<string | null>(null);
  const [solicitudesA, setSolicitudesA] = useState<string | null>(null);
  const desactivar = useDesactivarUsuario();

  // Destinos válidos: activos del MISMO rol, distintos del que se va.
  const { data: candidatos } = useUsuarios({ rol: usuario.rol, activo: true, limit: 100 });
  const opciones = (candidatos?.items ?? [])
    .filter((u) => u.id !== usuario.id)
    .map((u) => ({ value: String(u.id), label: u.nombre }));

  const listo =
    (!requisitos.requiereTitularidades || titularidadesA !== null) &&
    (!requisitos.requiereSolicitudes || solicitudesA !== null);

  const reintentar = () => {
    const body: DesactivarBody = {};
    if (titularidadesA !== null) body.titularidades_a = Number(titularidadesA);
    if (solicitudesA !== null) body.solicitudes_a = Number(solicitudesA);
    desactivar.mutate(
      { id: usuario.id, body },
      {
        onSuccess: () => {
          notifications.show({ message: `${usuario.nombre} dado de baja`, color: "gray" });
          onListo();
        },
        onError: (e) => {
          notifications.show({
            message: e instanceof ApiError ? e.detail : "No se pudo desactivar",
            color: "red",
          });
        },
      },
    );
  };

  return (
    <Stack gap="sm">
      <Alert color="yellow" title="El usuario tiene pendientes">
        <Text size="sm">{detalle409}</Text>
      </Alert>
      {requisitos.requiereTitularidades && (
        <Select
          label="Transferir titularidades a"
          placeholder="Comprador destino"
          data={opciones}
          value={titularidadesA}
          onChange={setTitularidadesA}
          searchable
        />
      )}
      {requisitos.requiereSolicitudes && (
        <Select
          label="Reasignar solicitudes abiertas a"
          placeholder={`${usuario.rol === "comprador" ? "Comprador" : "Vendedor"} destino`}
          data={opciones}
          value={solicitudesA}
          onChange={setSolicitudesA}
          searchable
        />
      )}
      <Button
        color="red"
        disabled={!listo}
        loading={desactivar.isPending}
        onClick={reintentar}
      >
        Transferir y dar de baja
      </Button>
    </Stack>
  );
}
