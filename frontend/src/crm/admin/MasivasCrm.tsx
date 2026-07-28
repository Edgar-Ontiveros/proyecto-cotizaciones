/** Reasignaciones masivas (F8d): de comprador (admin, gerente_compras) y de
 * vendedor (admin, director_ventas; gerente_sucursal entre SUS vendedores —
 * el backend valida sucursal). Confirmación con el conteo resultante. */

import { Button, Group, Paper, Select, Stack, Text, Title } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useState } from "react";

import { useReasignacionMasiva, useUsuarios } from "../../api/crmHooks";
import { useAuth } from "../../auth/AuthContext";

function BloqueMasivo({ tipo }: { tipo: "comprador" | "vendedor" }) {
  const [deId, setDeId] = useState<string | null>(null);
  const [aId, setAId] = useState<string | null>(null);
  const masiva = useReasignacionMasiva(tipo);
  // Origen puede estar inactivo (vacaciones/baja); destino debe estar activo.
  const { data: todos } = useUsuarios({ rol: tipo, limit: 100 });
  const { data: activos } = useUsuarios({ rol: tipo, activo: true, limit: 100 });
  const opciones = (lista: typeof todos) =>
    (lista?.items ?? []).map((u) => ({ value: String(u.id), label: u.nombre }));

  const ejecutar = () =>
    masiva.mutate(
      { de_id: Number(deId), a_id: Number(aId) },
      {
        onSuccess: (r) => {
          notifications.show({
            message: `${r.reasignadas} solicitud(es) reasignadas`,
            color: "green",
          });
          setDeId(null);
          setAId(null);
        },
      },
    );

  return (
    <Paper withBorder p="md">
      <Title order={5} mb="sm">
        {tipo === "comprador" ? "De comprador a comprador" : "De vendedor a vendedor"}
      </Title>
      <Group align="flex-end" gap="sm">
        <Select
          label="De"
          placeholder={`${tipo} origen`}
          data={opciones(todos)}
          value={deId}
          onChange={setDeId}
          searchable
          w={220}
        />
        <Select
          label="A"
          placeholder={`${tipo} destino (activo)`}
          data={opciones(activos).filter((o) => o.value !== deId)}
          value={aId}
          onChange={setAId}
          searchable
          w={220}
        />
        <Button
          disabled={deId === null || aId === null}
          loading={masiva.isPending}
          onClick={ejecutar}
        >
          Reasignar todas las abiertas
        </Button>
      </Group>
      <Text size="xs" c="dimmed" mt="xs">
        {tipo === "comprador"
          ? "Reasigna las solicitudes ENVIADA/EN_PROCESO del origen."
          : "Reasigna las solicitudes no terminales del origen (misma sucursal)."}
      </Text>
    </Paper>
  );
}

export function MasivasCrm() {
  const { usuario } = useAuth();
  if (!usuario) return null;
  const veCompras = usuario.rol === "admin" || usuario.rol === "gerente_compras";
  const veVentas = ["admin", "director_ventas", "gerente_sucursal"].includes(usuario.rol);
  return (
    <Stack>
      <Title order={3}>Reasignaciones masivas</Title>
      {veCompras && <BloqueMasivo tipo="comprador" />}
      {veVentas && <BloqueMasivo tipo="vendedor" />}
    </Stack>
  );
}
