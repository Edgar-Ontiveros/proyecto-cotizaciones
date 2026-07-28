/** Administración de usuarios (F8d). Cada gestor ve/gestiona lo que su
 * matriz permite — el backend acota el listado y las acciones; aquí el
 * formulario se arma con ROLES_GESTIONABLES (espejo testeado). */

import {
  Badge,
  Button,
  CopyButton,
  Group,
  Select,
  Stack,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { modals } from "@mantine/modals";
import { notifications } from "@mantine/notifications";
import { DataTable } from "mantine-datatable";
import { useState } from "react";

import {
  useActivarUsuario,
  useCrearUsuario,
  useDesactivarUsuario,
  useEditarUsuario,
  useFiltrosCatalogo,
  useResetPassword,
  useUsuarios,
} from "../../api/crmHooks";
import { useAuth } from "../../auth/AuthContext";
import { PAGE } from "../../components/filtrosListado";
import { ApiError } from "../../lib/api";
import { ROLES_CON_SUCURSAL, ROLES_GESTIONABLES, etiquetaRol } from "../../lib/crm";
import type { UsuarioOut } from "../../lib/types";
import { opcionesSelect } from "../FiltrosDashboard";
import { ModalBajaSegura } from "./BajaSegura";

function PasswordTemporal({ password }: { password: string }) {
  return (
    <Stack gap="sm">
      <Text size="sm">
        Contraseña temporal (se muestra UNA sola vez; el usuario debe cambiarla al entrar):
      </Text>
      <Group gap="sm">
        <Text ff="monospace" fw={700} fz="lg">
          {password}
        </Text>
        <CopyButton value={password}>
          {({ copied, copy }) => (
            <Button size="compact-sm" variant="light" onClick={copy}>
              {copied ? "Copiada" : "Copiar"}
            </Button>
          )}
        </CopyButton>
      </Group>
    </Stack>
  );
}

function FormUsuario({
  gestorRol,
  existente,
  onListo,
}: {
  gestorRol: string;
  existente: UsuarioOut | null;
  onListo: () => void;
}) {
  const { data: catalogos } = useFiltrosCatalogo();
  const [nombre, setNombre] = useState(existente?.nombre ?? "");
  const [email, setEmail] = useState(existente?.email ?? "");
  const [rol, setRol] = useState<string | null>(existente?.rol ?? null);
  const [sucursalId, setSucursalId] = useState<string | null>(
    existente?.sucursal_id !== null && existente !== null ? String(existente.sucursal_id) : null,
  );
  const crear = useCrearUsuario();
  const editar = useEditarUsuario();
  const rolesPermitidos = ROLES_GESTIONABLES[gestorRol] ?? [];
  const pideSucursal = rol !== null && ROLES_CON_SUCURSAL.includes(rol);
  const valido = nombre.trim() !== "" && email.trim() !== "" && rol !== null;

  const guardar = () => {
    const body = {
      nombre: nombre.trim(),
      email: email.trim(),
      rol: rol!,
      sucursal_id: pideSucursal && sucursalId !== null ? Number(sucursalId) : null,
    };
    if (existente === null) {
      crear.mutate(body, {
        onSuccess: (creado) => {
          onListo();
          if (creado.password_temporal !== null) {
            modals.open({
              title: `${creado.nombre} — acceso inicial`,
              children: <PasswordTemporal password={creado.password_temporal} />,
            });
          }
        },
      });
    } else {
      editar.mutate(
        { id: existente.id, body },
        {
          onSuccess: () => {
            notifications.show({ message: "Usuario actualizado", color: "green" });
            onListo();
          },
        },
      );
    }
  };

  return (
    <Stack gap="sm">
      <TextInput label="Nombre" value={nombre} onChange={(e) => setNombre(e.currentTarget.value)} />
      <TextInput label="Email" value={email} onChange={(e) => setEmail(e.currentTarget.value)} />
      <Select
        label="Rol"
        data={rolesPermitidos.map((r) => ({ value: r, label: etiquetaRol(r) }))}
        value={rol}
        onChange={setRol}
        disabled={existente !== null && gestorRol !== "admin"}
      />
      {pideSucursal && (
        <Select
          label="Sucursal"
          data={opcionesSelect(catalogos?.sucursales)}
          value={sucursalId}
          onChange={setSucursalId}
          searchable
        />
      )}
      <Button disabled={!valido} loading={crear.isPending || editar.isPending} onClick={guardar}>
        {existente === null ? "Crear usuario" : "Guardar cambios"}
      </Button>
    </Stack>
  );
}

export function UsuariosCrm() {
  const { usuario: gestor } = useAuth();
  const [pagina, setPagina] = useState(1);
  const [rol, setRol] = useState<string | null>(null);
  const [activo, setActivo] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const resetPassword = useResetPassword();
  const activar = useActivarUsuario();
  const desactivar = useDesactivarUsuario();

  const { data, isFetching } = useUsuarios({
    rol: rol ?? undefined,
    activo: activo === null ? undefined : activo === "activos",
    q: q || undefined,
    limit: PAGE,
    offset: (pagina - 1) * PAGE,
  });

  if (!gestor) return null;
  const rolesPermitidos = ROLES_GESTIONABLES[gestor.rol] ?? [];

  const abrirForm = (existente: UsuarioOut | null) =>
    modals.open({
      title: existente === null ? "Nuevo usuario" : `Editar a ${existente.nombre}`,
      children: (
        <FormUsuario
          gestorRol={gestor.rol}
          existente={existente}
          onListo={() => modals.closeAll()}
        />
      ),
    });

  const abrirReset = (u: UsuarioOut) =>
    modals.openConfirmModal({
      title: `Reset de contraseña — ${u.nombre}`,
      children: (
        <Text size="sm">Se generará una contraseña temporal de un solo uso. ¿Continuar?</Text>
      ),
      labels: { confirm: "Generar", cancel: "Volver" },
      onConfirm: () =>
        resetPassword.mutate(u.id, {
          onSuccess: (r) =>
            modals.open({
              title: `${u.nombre} — contraseña temporal`,
              children: <PasswordTemporal password={r.password_temporal} />,
            }),
        }),
    });

  const intentarBaja = (u: UsuarioOut) =>
    desactivar.mutate(
      { id: u.id, body: {} },
      {
        onSuccess: () => notifications.show({ message: `${u.nombre} desactivado`, color: "gray" }),
        onError: (e) => {
          if (e instanceof ApiError && e.code === "baja_requiere_reasignacion") {
            // Flujo guiado: modal con el detalle y los destinos requeridos.
            modals.open({
              title: `Baja segura — ${u.nombre}`,
              children: (
                <ModalBajaSegura
                  usuario={u}
                  detalle409={e.detail}
                  onListo={() => modals.closeAll()}
                />
              ),
            });
          } else {
            notifications.show({
              message: e instanceof ApiError ? e.detail : "No se pudo desactivar",
              color: "red",
            });
          }
        },
      },
    );

  return (
    <>
      <Group justify="space-between" mb="md">
        <Title order={3}>Usuarios</Title>
        <Button color="acento.6" onClick={() => abrirForm(null)}>
          Nuevo usuario
        </Button>
      </Group>
      <Group mb="sm" gap="sm">
        {rolesPermitidos.length > 1 && (
          <Select
            placeholder="Rol"
            data={rolesPermitidos.map((r) => ({ value: r, label: etiquetaRol(r) }))}
            value={rol}
            onChange={(v) => {
              setRol(v);
              setPagina(1);
            }}
            clearable
            w={180}
          />
        )}
        <Select
          placeholder="Estatus"
          data={[
            { value: "activos", label: "Activos" },
            { value: "inactivos", label: "Inactivos" },
          ]}
          value={activo}
          onChange={(v) => {
            setActivo(v);
            setPagina(1);
          }}
          clearable
          w={140}
        />
        <TextInput
          placeholder="Buscar nombre o email"
          value={q}
          onChange={(e) => {
            setQ(e.currentTarget.value);
            setPagina(1);
          }}
          w={220}
        />
      </Group>
      <DataTable<UsuarioOut>
        withTableBorder
        highlightOnHover
        minHeight={200}
        records={data?.items ?? []}
        fetching={isFetching}
        totalRecords={data?.total ?? 0}
        recordsPerPage={PAGE}
        page={pagina}
        onPageChange={setPagina}
        noRecordsText="Sin usuarios"
        columns={[
          { accessor: "nombre", title: "Nombre" },
          { accessor: "email", title: "Email" },
          { accessor: "rol", title: "Rol", render: (u) => etiquetaRol(u.rol) },
          {
            accessor: "activo",
            title: "Estatus",
            render: (u) =>
              u.activo ? (
                <Badge color="green" variant="light">
                  Activo
                </Badge>
              ) : (
                <Badge color="gray" variant="light">
                  Inactivo
                </Badge>
              ),
          },
          {
            accessor: "acciones",
            title: "",
            render: (u) => (
              <Group gap={4} justify="flex-end" wrap="nowrap">
                <Button size="compact-xs" variant="subtle" onClick={() => abrirForm(u)}>
                  Editar
                </Button>
                <Button size="compact-xs" variant="subtle" onClick={() => abrirReset(u)}>
                  Reset
                </Button>
                {u.activo ? (
                  <Button
                    size="compact-xs"
                    variant="subtle"
                    color="red"
                    disabled={u.id === gestor.id}
                    onClick={() => intentarBaja(u)}
                  >
                    Baja
                  </Button>
                ) : (
                  <Button
                    size="compact-xs"
                    variant="subtle"
                    color="green"
                    onClick={() => activar.mutate(u.id)}
                  >
                    Activar
                  </Button>
                )}
              </Group>
            ),
          },
        ]}
      />
    </>
  );
}
