/** Detalle de solicitud en el CRM (F8d): REUSA DetalleSolicitud (que ya es
 * consciente de la base /crm y del lado del rol) y agrega la barra de
 * acciones CRM: capturar cotización (compras), reasignar y corregir TC
 * (admin). */

import { Button, Group, NumberInput, Select, Stack, Text } from "@mantine/core";
import { modals } from "@mantine/modals";
import { notifications } from "@mantine/notifications";
import { useState } from "react";
import { useNavigate, useParams } from "react-router";

import { useSolicitud } from "../api/hooks";
import {
  useCorregirTipoCambio,
  useReasignarComprador,
  useReasignarVendedor,
  useUsuarios,
} from "../api/crmHooks";
import { useAuth } from "../auth/AuthContext";
import { dinero } from "../lib/format";
import type { SolicitudDetailOut } from "../lib/types";
import { DetalleSolicitud } from "../views/vendedor/DetalleSolicitud";

function ModalReasignar({
  solicitud,
  tipo,
  onListo,
}: {
  solicitud: SolicitudDetailOut;
  tipo: "comprador" | "vendedor";
  onListo: () => void;
}) {
  const [destino, setDestino] = useState<string | null>(null);
  // Candidatos válidos: activos del rol; el vendedor destino debe ser de LA
  // sucursal de la solicitud (el backend lo valida — aquí ya se filtra).
  const { data } = useUsuarios({
    rol: tipo,
    activo: true,
    sucursal_id: tipo === "vendedor" ? solicitud.sucursal_id : undefined,
    limit: 100,
  });
  const reasignarComprador = useReasignarComprador(solicitud.id);
  const reasignarVendedor = useReasignarVendedor(solicitud.id);
  const mutacion = tipo === "comprador" ? reasignarComprador : reasignarVendedor;
  const actualId = tipo === "comprador" ? solicitud.comprador_id : solicitud.vendedor_id;
  const opciones = (data?.items ?? [])
    .filter((u) => u.id !== actualId)
    .map((u) => ({ value: String(u.id), label: u.nombre }));

  return (
    <Stack gap="sm">
      <Select
        label={`Nuevo ${tipo}`}
        placeholder="Selecciona"
        data={opciones}
        value={destino}
        onChange={setDestino}
        searchable
      />
      <Button
        disabled={destino === null}
        loading={mutacion.isPending}
        onClick={() => {
          mutacion.mutate(Number(destino), {
            onSuccess: () => {
              notifications.show({ message: `Solicitud reasignada`, color: "green" });
              onListo();
            },
          });
        }}
      >
        Reasignar
      </Button>
    </Stack>
  );
}

function ModalCorregirTC({
  solicitud,
  onListo,
}: {
  solicitud: SolicitudDetailOut;
  onListo: () => void;
}) {
  const [tc, setTc] = useState<string | number>("");
  const corregir = useCorregirTipoCambio(solicitud.id);
  const ganadora = solicitud.opciones.find((o) => o.id === solicitud.opcion_seleccionada_id);
  const tcNumero = Number(tc);
  const preview =
    ganadora && tcNumero > 0
      ? Number(ganadora.total_mxn) + Number(ganadora.total_usd) * tcNumero
      : null;

  return (
    <Stack gap="sm">
      <Text size="sm">
        TC actual: <b>{solicitud.tipo_cambio ?? "—"}</b> · Monto oficial:{" "}
        <b>
          {solicitud.monto_confirmado !== null ? dinero(solicitud.monto_confirmado, "MXN") : "—"}
        </b>
      </Text>
      <NumberInput
        label="Nuevo tipo de cambio"
        value={tc}
        onChange={setTc}
        min={0}
        decimalScale={4}
        step={0.05}
      />
      {preview !== null && ganadora && (
        <Text size="sm" c="dimmed">
          Nuevo consolidado: {dinero(ganadora.total_mxn, "MXN")} +{" "}
          {dinero(ganadora.total_usd, "USD")} × {tcNumero} = <b>{dinero(preview, "MXN")}</b>
        </Text>
      )}
      <Button
        disabled={!(tcNumero > 0)}
        loading={corregir.isPending}
        onClick={() => {
          corregir.mutate(String(tc), {
            onSuccess: () => {
              notifications.show({ message: "Tipo de cambio corregido", color: "green" });
              onListo();
            },
          });
        }}
      >
        Corregir TC
      </Button>
    </Stack>
  );
}

function AccionesCrm() {
  const { id } = useParams();
  const solicitudId = Number(id);
  const navigate = useNavigate();
  const { usuario } = useAuth();
  const { data: solicitud } = useSolicitud(solicitudId);
  if (!usuario || !solicitud) return null;

  const esAdmin = usuario.rol === "admin";
  const esCompras = esAdmin || usuario.rol === "gerente_compras";
  const capturable = ["ENVIADA", "EN_PROCESO", "COTIZADA"].includes(solicitud.estado);
  const ganadora = solicitud.opciones.find((o) => o.id === solicitud.opcion_seleccionada_id);
  const corregibleTC =
    esAdmin && solicitud.estado === "CONFIRMADA" && ganadora !== undefined
      ? Number(ganadora.total_usd) > 0
      : false;
  const reasignable = !["CONFIRMADA", "NO_CONFIRMADA", "CANCELADA"].includes(solicitud.estado);

  const abrirReasignar = (tipo: "comprador" | "vendedor") =>
    modals.open({
      title: `Reasignar ${tipo}`,
      children: (
        <ModalReasignar solicitud={solicitud} tipo={tipo} onListo={() => modals.closeAll()} />
      ),
    });

  const botones = [
    esCompras && capturable && (
      <Button
        key="capturar"
        color="acento.6"
        onClick={() => navigate(`/crm/solicitudes/${solicitudId}/capturar`)}
      >
        Capturar cotización
      </Button>
    ),
    esAdmin && reasignable && solicitud.comprador_id !== null && (
      <Button key="rc" variant="light" onClick={() => abrirReasignar("comprador")}>
        Reasignar comprador
      </Button>
    ),
    esAdmin && reasignable && (
      <Button key="rv" variant="light" onClick={() => abrirReasignar("vendedor")}>
        Reasignar vendedor
      </Button>
    ),
    corregibleTC && (
      <Button
        key="tc"
        variant="light"
        color="orange"
        onClick={() =>
          modals.open({
            title: "Corregir tipo de cambio",
            children: <ModalCorregirTC solicitud={solicitud} onListo={() => modals.closeAll()} />,
          })
        }
      >
        Corregir TC
      </Button>
    ),
  ].filter(Boolean);

  if (botones.length === 0) return null;
  return (
    <Group justify="flex-end" mb="xs">
      {botones}
    </Group>
  );
}

export function DetalleCrm() {
  return (
    <>
      <AccionesCrm />
      <DetalleSolicitud />
    </>
  );
}
