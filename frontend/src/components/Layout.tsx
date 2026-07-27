import {
  ActionIcon,
  AppShell,
  Badge,
  Button,
  Container,
  Divider,
  Group,
  Indicator,
  Popover,
  ScrollArea,
  Stack,
  Text,
  Title,
  UnstyledButton,
} from "@mantine/core";
import { Outlet, useNavigate } from "react-router";

import { useLeerTodas, useMarcarLeida, useNotificaciones } from "../api/hooks";
import { rutaPorRol, useAuth } from "../auth/AuthContext";
import { fechaHora } from "../lib/format";
import type { NotificacionOut } from "../lib/types";

function Campana() {
  const { data } = useNotificaciones();
  const marcarLeida = useMarcarLeida();
  const leerTodas = useLeerTodas();
  const navigate = useNavigate();
  const { usuario } = useAuth();
  const noLeidas = data?.no_leidas ?? 0;

  const abrir = (n: NotificacionOut) => {
    if (!n.leida) marcarLeida.mutate(n.id);
    if (n.solicitud_id !== null && usuario) {
      const base = usuario.rol === "comprador" ? "/comprador" : "/vendedor";
      navigate(`${base}/solicitudes/${n.solicitud_id}`);
    }
  };

  return (
    <Popover width={380} position="bottom-end" shadow="md">
      <Popover.Target>
        <Indicator label={noLeidas} size={16} disabled={noLeidas === 0} color="acento.6">
          <ActionIcon variant="subtle" color="gray" size="lg" aria-label="Notificaciones">
            {/* campana en SVG inline: sin librerías de iconos fuera del stack */}
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9" />
              <path d="M13.7 21a2 2 0 0 1-3.4 0" />
            </svg>
          </ActionIcon>
        </Indicator>
      </Popover.Target>
      <Popover.Dropdown p="xs">
        <Group justify="space-between" px="xs" py={4}>
          <Text fw={600}>Notificaciones</Text>
          {noLeidas > 0 && (
            <Button variant="subtle" size="compact-xs" onClick={() => leerTodas.mutate()}>
              Leer todas
            </Button>
          )}
        </Group>
        <Divider />
        <ScrollArea.Autosize mah={360}>
          {(data?.items ?? []).length === 0 && (
            <Text c="dimmed" size="sm" p="md">
              Sin notificaciones
            </Text>
          )}
          <Stack gap={0}>
            {(data?.items ?? []).map((n) => (
              <UnstyledButton
                key={n.id}
                onClick={() => abrir(n)}
                p="xs"
                style={{ borderBottom: "1px solid var(--mantine-color-gray-2)" }}
              >
                <Group gap="xs" wrap="nowrap" align="flex-start">
                  {!n.leida && <Badge color="acento.6" size="xs" circle />}
                  <div>
                    <Text size="sm" fw={n.leida ? 400 : 600}>
                      {n.mensaje}
                    </Text>
                    <Text size="xs" c="dimmed">
                      {fechaHora(n.creado_en)}
                    </Text>
                  </div>
                </Group>
              </UnstyledButton>
            ))}
          </Stack>
        </ScrollArea.Autosize>
      </Popover.Dropdown>
    </Popover>
  );
}

export function Layout() {
  const { usuario, logout } = useAuth();
  const navigate = useNavigate();

  return (
    <AppShell header={{ height: 56 }} padding="md">
      <AppShell.Header bg="herinox.6">
        <Group h="100%" px="md" justify="space-between">
          <UnstyledButton onClick={() => navigate(usuario ? rutaPorRol(usuario.rol) : "/")}>
            <Title order={4} c="white">
              Cotizaciones Herinox
            </Title>
          </UnstyledButton>
          <Group gap="sm">
            <Campana />
            <Text c="white" size="sm">
              {usuario?.nombre}
            </Text>
            <Button
              variant="white"
              size="compact-sm"
              onClick={() => {
                void logout().then(() => navigate("/login"));
              }}
            >
              Salir
            </Button>
          </Group>
        </Group>
      </AppShell.Header>
      <AppShell.Main bg="gray.0">
        <Container size="xl">
          <Outlet />
        </Container>
      </AppShell.Main>
    </AppShell>
  );
}
