/** Territorios y titularidad (F8d, admin y gerente_compras): mapa
 * comprador↔sucursales y cambio de titular por sucursal. */

import { Badge, Button, Group, Paper, Select, Stack, Text, Title } from "@mantine/core";
import { modals } from "@mantine/modals";
import { notifications } from "@mantine/notifications";
import { useState } from "react";

import { useCambiarTitular, useFiltrosCatalogo, useTerritorios } from "../../api/crmHooks";
import type { TerritorioComprador } from "../../lib/types";
import { opcionesSelect } from "../FiltrosDashboard";

function ModalTitular({
  sucursalId,
  sucursalNombre,
  onListo,
}: {
  sucursalId: number;
  sucursalNombre: string;
  onListo: () => void;
}) {
  const { data: catalogos } = useFiltrosCatalogo();
  const [compradorId, setCompradorId] = useState<string | null>(null);
  const cambiar = useCambiarTitular();
  return (
    <Stack gap="sm">
      <Select
        label={`Nuevo titular de ${sucursalNombre}`}
        description="El titular recibe las solicitudes NUEVAS de la sucursal"
        data={opcionesSelect(catalogos?.compradores)}
        value={compradorId}
        onChange={setCompradorId}
        searchable
      />
      <Button
        disabled={compradorId === null}
        loading={cambiar.isPending}
        onClick={() =>
          cambiar.mutate(
            { sucursalId, compradorId: Number(compradorId) },
            {
              onSuccess: () => {
                notifications.show({ message: "Titular actualizado", color: "green" });
                onListo();
              },
            },
          )
        }
      >
        Cambiar titular
      </Button>
    </Stack>
  );
}

function CartaComprador({ comprador }: { comprador: TerritorioComprador }) {
  return (
    <Paper withBorder p="md">
      <Group justify="space-between" mb="xs">
        <Text fw={600}>
          {comprador.comprador_nombre}
          {!comprador.comprador_activo && (
            <Badge ml="xs" color="gray" variant="light">
              Inactivo
            </Badge>
          )}
        </Text>
      </Group>
      {comprador.sucursales.length === 0 ? (
        <Text size="sm" c="dimmed">
          Sin territorio asignado
        </Text>
      ) : (
        <Group gap={6}>
          {comprador.sucursales.map((s) => (
            <Badge
              key={s.sucursal_id}
              color={s.titular ? "herinox.6" : "gray"}
              variant={s.titular ? "filled" : "outline"}
              style={{ cursor: "pointer" }}
              onClick={() =>
                modals.open({
                  title: `Titularidad — ${s.sucursal_nombre}`,
                  children: (
                    <ModalTitular
                      sucursalId={s.sucursal_id}
                      sucursalNombre={s.sucursal_nombre}
                      onListo={() => modals.closeAll()}
                    />
                  ),
                })
              }
            >
              {s.sucursal_nombre}
              {s.titular ? " · titular" : ""}
            </Badge>
          ))}
        </Group>
      )}
    </Paper>
  );
}

export function TerritoriosCrm() {
  const { data } = useTerritorios();
  return (
    <Stack>
      <Title order={3}>Territorios y titularidad</Title>
      <Text size="sm" c="dimmed">
        Cada sucursal tiene UN titular (badge azul). Haz clic en una sucursal para cambiarlo.
      </Text>
      {(data?.items ?? []).map((c) => (
        <CartaComprador key={c.comprador_id} comprador={c} />
      ))}
    </Stack>
  );
}
