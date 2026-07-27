import {
  Alert,
  Button,
  Center,
  Paper,
  PasswordInput,
  Stack,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { useForm } from "@mantine/form";
import { useState } from "react";
import { Navigate, useNavigate } from "react-router";

import { ApiError } from "../lib/api";
import { rutaPorRol, useAuth } from "./AuthContext";

export function LoginPage() {
  const { usuario, mustChangePassword, login } = useAuth();
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);
  const [enviando, setEnviando] = useState(false);

  const form = useForm({
    initialValues: { email: "", password: "" },
    validate: {
      email: (v) => (/\S+@\S+/.test(v) ? null : "Correo inválido"),
      password: (v) => (v.length > 0 ? null : "Captura tu contraseña"),
    },
  });

  if (mustChangePassword) return <Navigate to="/cambiar-password" replace />;
  if (usuario) return <Navigate to={rutaPorRol(usuario.rol)} replace />;

  const onSubmit = form.onSubmit(async (values) => {
    setError(null);
    setEnviando(true);
    try {
      const r = await login(values.email, values.password);
      navigate(r.mustChangePassword ? "/cambiar-password" : "/", { replace: true });
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : "No se pudo iniciar sesión");
    } finally {
      setEnviando(false);
    }
  });

  return (
    <Center h="100vh" bg="gray.0">
      <Paper withBorder shadow="md" p="xl" w={380}>
        <form onSubmit={onSubmit}>
          <Stack>
            <Title order={2} c="herinox.6">
              Cotizaciones Herinox
            </Title>
            <Text c="dimmed" size="sm">
              Solicitudes de cotización de pedido especial
            </Text>
            {error && <Alert color="red">{error}</Alert>}
            <TextInput label="Correo" placeholder="tu@herinox.com.mx" {...form.getInputProps("email")} />
            <PasswordInput label="Contraseña" {...form.getInputProps("password")} />
            <Button type="submit" loading={enviando} fullWidth>
              Entrar
            </Button>
          </Stack>
        </form>
      </Paper>
    </Center>
  );
}
