/** Catálogos (F8d, solo admin): motivos de rechazo (soft-delete vía activo)
 * y días festivos NACIONALES (v1). */

import {
  Badge,
  Button,
  Group,
  Paper,
  Select,
  Stack,
  Table,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { DatePickerInput } from "@mantine/dates";
import { notifications } from "@mantine/notifications";
import dayjs from "dayjs";
import { useState } from "react";

import {
  useCrearFestivo,
  useCrearMotivo,
  useEditarMotivo,
  useEliminarFestivo,
  useFestivos,
  useMotivosAdmin,
} from "../../api/crmHooks";
import { fecha } from "../../lib/format";

const FAMILIAS = [
  { value: "falta_informacion", label: "Falta información" },
  { value: "no_procede", label: "No procede" },
];

function Motivos() {
  const { data } = useMotivosAdmin();
  const crear = useCrearMotivo();
  const editar = useEditarMotivo();
  const [familia, setFamilia] = useState<string | null>(null);
  const [texto, setTexto] = useState("");

  return (
    <Paper withBorder p="md">
      <Title order={5} mb="sm">
        Motivos de rechazo
      </Title>
      <Group align="flex-end" gap="sm" mb="sm">
        <Select label="Familia" data={FAMILIAS} value={familia} onChange={setFamilia} w={200} />
        <TextInput
          label="Texto"
          value={texto}
          onChange={(e) => setTexto(e.currentTarget.value)}
          w={300}
        />
        <Button
          disabled={familia === null || texto.trim() === ""}
          loading={crear.isPending}
          onClick={() =>
            crear.mutate(
              { familia: familia!, texto: texto.trim() },
              {
                onSuccess: () => {
                  notifications.show({ message: "Motivo creado", color: "green" });
                  setTexto("");
                },
              },
            )
          }
        >
          Agregar
        </Button>
      </Group>
      <Table withTableBorder striped>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Familia</Table.Th>
            <Table.Th>Texto</Table.Th>
            <Table.Th>Estatus</Table.Th>
            <Table.Th />
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {(data ?? []).map((m) => (
            <Table.Tr key={m.id}>
              <Table.Td>{FAMILIAS.find((f) => f.value === m.familia)?.label ?? m.familia}</Table.Td>
              <Table.Td>{m.texto}</Table.Td>
              <Table.Td>
                <Badge color={m.activo ? "green" : "gray"} variant="light">
                  {m.activo ? "Activo" : "Inactivo"}
                </Badge>
              </Table.Td>
              <Table.Td>
                <Button
                  size="compact-xs"
                  variant="subtle"
                  color={m.activo ? "red" : "green"}
                  onClick={() => editar.mutate({ id: m.id, body: { activo: !m.activo } })}
                >
                  {m.activo ? "Desactivar" : "Reactivar"}
                </Button>
              </Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Paper>
  );
}

function Festivos() {
  const { data } = useFestivos();
  const crear = useCrearFestivo();
  const eliminar = useEliminarFestivo();
  const [dia, setDia] = useState<string | null>(null);
  const [descripcion, setDescripcion] = useState("");

  return (
    <Paper withBorder p="md">
      <Title order={5} mb="sm">
        Días festivos (nacionales, v1)
      </Title>
      <Text size="xs" c="dimmed" mb="sm">
        Los festivos NO cuentan como horas hábiles en la medición de bandas.
      </Text>
      <Group align="flex-end" gap="sm" mb="sm">
        <DatePickerInput label="Fecha" value={dia} onChange={setDia} w={180} />
        <TextInput
          label="Descripción"
          value={descripcion}
          onChange={(e) => setDescripcion(e.currentTarget.value)}
          w={260}
        />
        <Button
          disabled={dia === null}
          loading={crear.isPending}
          onClick={() =>
            crear.mutate(
              {
                fecha: dayjs(dia).format("YYYY-MM-DD"),
                descripcion: descripcion.trim() || null,
              },
              {
                onSuccess: () => {
                  notifications.show({ message: "Festivo agregado", color: "green" });
                  setDia(null);
                  setDescripcion("");
                },
              },
            )
          }
        >
          Agregar
        </Button>
      </Group>
      <Table withTableBorder striped>
        <Table.Tbody>
          {(data ?? []).map((f) => (
            <Table.Tr key={f.id}>
              <Table.Td>{fecha(f.fecha)}</Table.Td>
              <Table.Td>{f.descripcion ?? "—"}</Table.Td>
              <Table.Td>
                <Button
                  size="compact-xs"
                  variant="subtle"
                  color="red"
                  onClick={() => eliminar.mutate(f.id)}
                >
                  Eliminar
                </Button>
              </Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Paper>
  );
}

export function CatalogosCrm() {
  return (
    <Stack>
      <Title order={3}>Catálogos</Title>
      <Motivos />
      <Festivos />
    </Stack>
  );
}
