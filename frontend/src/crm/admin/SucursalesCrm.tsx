/** Sucursales (F8d, solo admin): CRUD, prefijo de folio, contador (el
 * backend valida que nunca retroceda), timezone IANA de México y activa. */

import { Badge, Button, Group, NumberInput, Select, Stack, TextInput, Title } from "@mantine/core";
import { modals } from "@mantine/modals";
import { notifications } from "@mantine/notifications";
import { DataTable } from "mantine-datatable";
import { useState } from "react";

import {
  useCrearSucursal,
  useEditarFolioCounter,
  useEditarSucursal,
  useSucursales,
} from "../../api/crmHooks";
import type { SucursalOut } from "../../lib/types";

/** Zonas IANA usadas en México (11 sucursales, 5+ zonas). */
const ZONAS_MX = [
  "America/Mexico_City",
  "America/Monterrey",
  "America/Chihuahua",
  "America/Ciudad_Juarez",
  "America/Hermosillo",
  "America/Tijuana",
  "America/Mazatlan",
  "America/Matamoros",
  "America/Ojinaga",
  "America/Cancun",
  "America/Merida",
  "America/Bahia_Banderas",
];

function FormSucursal({
  existente,
  onListo,
}: {
  existente: SucursalOut | null;
  onListo: () => void;
}) {
  const [nombre, setNombre] = useState(existente?.nombre ?? "");
  const [prefijo, setPrefijo] = useState(existente?.prefijo_folio ?? "");
  const [timezone, setTimezone] = useState<string | null>(existente?.timezone ?? null);
  const [contador, setContador] = useState<string | number>(0);
  const [activa, setActiva] = useState(existente?.activa ?? true);
  const crear = useCrearSucursal();
  const editar = useEditarSucursal();
  const valido = nombre.trim() !== "" && prefijo.trim() !== "" && timezone !== null;

  const guardar = () => {
    if (existente === null) {
      crear.mutate(
        {
          nombre: nombre.trim(),
          prefijo_folio: prefijo.trim(),
          timezone: timezone!,
          contador_inicial: Number(contador) || 0,
        },
        {
          onSuccess: () => {
            notifications.show({ message: "Sucursal creada", color: "green" });
            onListo();
          },
        },
      );
    } else {
      editar.mutate(
        {
          id: existente.id,
          body: { nombre: nombre.trim(), prefijo_folio: prefijo.trim(), timezone: timezone!, activa },
        },
        {
          onSuccess: () => {
            notifications.show({ message: "Sucursal actualizada", color: "green" });
            onListo();
          },
        },
      );
    }
  };

  return (
    <Stack gap="sm">
      <TextInput label="Nombre" value={nombre} onChange={(e) => setNombre(e.currentTarget.value)} />
      <TextInput
        label="Prefijo de folio"
        description="Convención real: CCN → CCN-3036"
        value={prefijo}
        onChange={(e) => setPrefijo(e.currentTarget.value.toUpperCase())}
      />
      <Select label="Zona horaria (IANA)" data={ZONAS_MX} value={timezone} onChange={setTimezone} searchable />
      {existente === null && (
        <NumberInput
          label="Contador inicial"
          description="Para continuar la numeración actual sin saltos"
          value={contador}
          onChange={setContador}
          min={0}
        />
      )}
      {existente !== null && (
        <Select
          label="Estatus"
          data={[
            { value: "activa", label: "Activa" },
            { value: "inactiva", label: "Inactiva" },
          ]}
          value={activa ? "activa" : "inactiva"}
          onChange={(v) => setActiva(v === "activa")}
        />
      )}
      <Button disabled={!valido} loading={crear.isPending || editar.isPending} onClick={guardar}>
        {existente === null ? "Crear sucursal" : "Guardar cambios"}
      </Button>
    </Stack>
  );
}

function ModalContador({ sucursal, onListo }: { sucursal: SucursalOut; onListo: () => void }) {
  const [ultimo, setUltimo] = useState<string | number>("");
  const editar = useEditarFolioCounter();
  return (
    <Stack gap="sm">
      <NumberInput
        label={`Nuevo último consecutivo de ${sucursal.prefijo_folio}`}
        description="El backend rechaza cualquier retroceso"
        value={ultimo}
        onChange={setUltimo}
        min={0}
      />
      <Button
        disabled={ultimo === ""}
        loading={editar.isPending}
        onClick={() =>
          editar.mutate(
            { id: sucursal.id, ultimo: Number(ultimo) },
            {
              onSuccess: () => {
                notifications.show({ message: "Contador actualizado", color: "green" });
                onListo();
              },
            },
          )
        }
      >
        Actualizar contador
      </Button>
    </Stack>
  );
}

export function SucursalesCrm() {
  const { data, isFetching } = useSucursales();

  const abrirForm = (existente: SucursalOut | null) =>
    modals.open({
      title: existente === null ? "Nueva sucursal" : `Editar ${existente.nombre}`,
      children: <FormSucursal existente={existente} onListo={() => modals.closeAll()} />,
    });

  return (
    <>
      <Group justify="space-between" mb="md">
        <Title order={3}>Sucursales</Title>
        <Button color="acento.6" onClick={() => abrirForm(null)}>
          Nueva sucursal
        </Button>
      </Group>
      <DataTable<SucursalOut>
        withTableBorder
        highlightOnHover
        minHeight={200}
        records={data ?? []}
        fetching={isFetching}
        noRecordsText="Sin sucursales"
        columns={[
          { accessor: "nombre", title: "Nombre" },
          { accessor: "prefijo_folio", title: "Prefijo" },
          { accessor: "timezone", title: "Zona horaria" },
          {
            accessor: "activa",
            title: "Estatus",
            render: (s) =>
              s.activa ? (
                <Badge color="green" variant="light">
                  Activa
                </Badge>
              ) : (
                <Badge color="gray" variant="light">
                  Inactiva
                </Badge>
              ),
          },
          {
            accessor: "acciones",
            title: "",
            render: (s) => (
              <Group gap={4} justify="flex-end" wrap="nowrap">
                <Button size="compact-xs" variant="subtle" onClick={() => abrirForm(s)}>
                  Editar
                </Button>
                <Button
                  size="compact-xs"
                  variant="subtle"
                  onClick={() =>
                    modals.open({
                      title: `Contador de folios — ${s.nombre}`,
                      children: <ModalContador sucursal={s} onListo={() => modals.closeAll()} />,
                    })
                  }
                >
                  Contador
                </Button>
              </Group>
            ),
          },
        ]}
      />
    </>
  );
}
