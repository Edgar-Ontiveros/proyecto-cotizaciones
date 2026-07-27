import { Alert, Button, Center, Paper, PasswordInput, Stack, Text, Title } from "@mantine/core";
import { useForm } from "@mantine/form";
import { useState } from "react";
import { useNavigate } from "react-router";

import { ApiError } from "../lib/api";
import { useAuth } from "./AuthContext";

/** Cambio OBLIGATORIO: mientras must_change_password sea true el backend
 * responde 403 a todo lo demás — esta pantalla bloquea el sistema entero. */
export function CambioPasswordPage() {
  const { cambiarPassword } = useAuth();
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);
  const [enviando, setEnviando] = useState(false);

  const form = useForm({
    initialValues: { actual: "", nueva: "", confirmacion: "" },
    validate: {
      actual: (v) => (v.length > 0 ? null : "Captura tu contraseña actual"),
      nueva: (v) => (v.length >= 8 ? null : "Mínimo 8 caracteres"),
      confirmacion: (v, values) => (v === values.nueva ? null : "No coincide con la nueva"),
    },
  });

  const onSubmit = form.onSubmit(async (values) => {
    setError(null);
    setEnviando(true);
    try {
      await cambiarPassword(values.actual, values.nueva);
      navigate("/", { replace: true });
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : "No se pudo cambiar la contraseña");
    } finally {
      setEnviando(false);
    }
  });

  return (
    <Center h="100vh" bg="gray.0">
      <Paper withBorder shadow="md" p="xl" w={420}>
        <form onSubmit={onSubmit}>
          <Stack>
            <Title order={3}>Cambia tu contraseña</Title>
            <Text c="dimmed" size="sm">
              Tu contraseña es temporal: debes cambiarla antes de continuar.
            </Text>
            {error && <Alert color="red">{error}</Alert>}
            <PasswordInput label="Contraseña actual" {...form.getInputProps("actual")} />
            <PasswordInput label="Contraseña nueva" {...form.getInputProps("nueva")} />
            <PasswordInput label="Confirma la nueva" {...form.getInputProps("confirmacion")} />
            <Button type="submit" loading={enviando} fullWidth>
              Cambiar y continuar
            </Button>
          </Stack>
        </form>
      </Paper>
    </Center>
  );
}
