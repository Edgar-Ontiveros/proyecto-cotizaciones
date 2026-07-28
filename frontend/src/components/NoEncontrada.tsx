import { Button, Center, Paper, Stack, Text, Title } from "@mantine/core";
import { useNavigate } from "react-router";

import { rutaPorRol, useAuth } from "../auth/AuthContext";

/** 404 real (F8d): antes cualquier ruta desconocida redirigía a "/". */
export function NoEncontrada() {
  const navigate = useNavigate();
  const { usuario } = useAuth();
  return (
    <Center mt={80}>
      <Paper withBorder p="xl" w={420}>
        <Stack gap="sm">
          <Title order={3}>Página no encontrada</Title>
          <Text c="dimmed">La ruta que buscas no existe o fue movida.</Text>
          <Button onClick={() => navigate(usuario ? rutaPorRol(usuario.rol) : "/")} w="fit-content">
            Ir al inicio
          </Button>
        </Stack>
      </Paper>
    </Center>
  );
}
