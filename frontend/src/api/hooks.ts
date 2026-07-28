/** Hooks de datos (TanStack Query 5) sobre lib/api. Un archivo por brevedad:
 * routers delgados en el backend, hooks delgados aquí. */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../lib/api";
import type {
  ClienteOut,
  Letra,
  MiPanelOut,
  MotivoNoConfirmada,
  MotivoOut,
  NotificacionListOut,
  NotificacionOut,
  SolicitudDetailOut,
  SolicitudListOut,
  SolicitudOut,
} from "../lib/types";

export interface FiltrosListado {
  estado?: string;
  cliente_id?: number;
  desde?: string;
  hasta?: string;
  buscar?: string;
  limit?: number;
  offset?: number;
}

export function useSolicitudes(filtros: FiltrosListado) {
  return useQuery({
    queryKey: ["solicitudes", filtros],
    queryFn: () => api<SolicitudListOut>("/solicitudes", { params: { ...filtros } }),
    placeholderData: (prev) => prev,
  });
}

export function useSolicitud(id: number) {
  return useQuery({
    queryKey: ["solicitud", id],
    queryFn: () => api<SolicitudDetailOut>(`/solicitudes/${id}`),
    enabled: id > 0,
  });
}

export function useClientes(buscar: string) {
  return useQuery({
    queryKey: ["clientes", buscar],
    queryFn: () => api<ClienteOut[]>("/clientes", { params: { buscar } }),
  });
}

export function useMotivosRechazo() {
  return useQuery({
    queryKey: ["motivos-rechazo"],
    queryFn: () => api<MotivoOut[]>("/catalogos/motivos-rechazo"),
  });
}

export function useMiPanel(habilitado: boolean) {
  return useQuery({
    queryKey: ["mi-panel"],
    queryFn: () => api<MiPanelOut>("/metricas/mi-panel"),
    enabled: habilitado,
  });
}

// ------------------------------------------------------------- notificaciones

export function useNotificaciones() {
  return useQuery({
    queryKey: ["notificaciones"],
    queryFn: () => api<NotificacionListOut>("/notificaciones", { params: { limit: 20 } }),
    // Polling del badge: cada 45 s (nada de websockets).
    refetchInterval: 45_000,
  });
}

export function useMarcarLeida() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api<NotificacionOut>(`/notificaciones/${id}/leer`, { method: "POST" }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["notificaciones"] }),
  });
}

export function useLeerTodas() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api<{ actualizadas: number }>("/notificaciones/leer-todas", { method: "POST" }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["notificaciones"] }),
  });
}

// ------------------------------------------------------------------ mutaciones

export interface SolicitudBody {
  cliente: string | null;
  prioridad: string;
  notas: string | null;
  partidas: {
    codigo_sap: string | null;
    cantidad: string;
    unidad: string;
    tipo_acero: string | null;
    descripcion: string;
    medidas: string | null;
  }[];
}

/** Invalida listado + detalle tras cualquier mutación de una solicitud. */
function useInvalidarSolicitudes() {
  const qc = useQueryClient();
  return (id?: number) => {
    void qc.invalidateQueries({ queryKey: ["solicitudes"] });
    if (id !== undefined) void qc.invalidateQueries({ queryKey: ["solicitud", id] });
    void qc.invalidateQueries({ queryKey: ["notificaciones"] });
  };
}

export function useCrearSolicitud() {
  const invalidar = useInvalidarSolicitudes();
  return useMutation({
    mutationFn: (body: SolicitudBody) => api<SolicitudOut>("/solicitudes", { method: "POST", body }),
    onSuccess: () => invalidar(),
  });
}

export function useEditarSolicitud(id: number) {
  const invalidar = useInvalidarSolicitudes();
  return useMutation({
    mutationFn: (body: SolicitudBody) =>
      api<SolicitudOut>(`/solicitudes/${id}`, { method: "PATCH", body }),
    onSuccess: () => invalidar(id),
  });
}

/** Acciones de transición sin body (enviar/tomar/cancelar). */
export function useAccionSolicitud(accion: "enviar" | "tomar" | "cancelar") {
  const invalidar = useInvalidarSolicitudes();
  return useMutation({
    mutationFn: (id: number) => api<SolicitudOut>(`/solicitudes/${id}/${accion}`, { method: "POST" }),
    onSuccess: (_dato, id) => invalidar(id),
  });
}

export function useRechazar(id: number) {
  const invalidar = useInvalidarSolicitudes();
  return useMutation({
    mutationFn: (body: { motivo_id: number; comentario: string | null }) =>
      api<SolicitudOut>(`/solicitudes/${id}/rechazar`, { method: "POST", body }),
    onSuccess: () => invalidar(id),
  });
}

export interface RenglonBody {
  partida_id: number;
  cantidad: string | null;
  unidad: string | null;
  moneda: string | null;
  precio_unitario: string | null;
  tiempo_entrega: string | null;
  proveedor: string | null;
  no_encontrada: boolean;
  es_alternativa: boolean;
  alternativa_descripcion: string | null;
}

export interface OpcionBody {
  vigencia: string | null;
  comentarios: string | null;
  renglones: RenglonBody[];
}

export function useGuardarOpcion(id: number) {
  const invalidar = useInvalidarSolicitudes();
  return useMutation({
    mutationFn: ({ letra, body }: { letra: Letra; body: OpcionBody }) =>
      api<unknown>(`/solicitudes/${id}/opciones/${letra}`, { method: "PUT", body }),
    onSuccess: () => invalidar(id),
  });
}

export function useEliminarOpcion(id: number) {
  const invalidar = useInvalidarSolicitudes();
  return useMutation({
    mutationFn: (letra: Letra) =>
      api<void>(`/solicitudes/${id}/opciones/${letra}`, { method: "DELETE" }),
    onSuccess: () => invalidar(id),
  });
}

export function useCotizar(id: number) {
  const invalidar = useInvalidarSolicitudes();
  return useMutation({
    mutationFn: () => api<SolicitudOut>(`/solicitudes/${id}/cotizar`, { method: "POST" }),
    onSuccess: () => invalidar(id),
  });
}

export function useSeleccionar(id: number) {
  const invalidar = useInvalidarSolicitudes();
  return useMutation({
    mutationFn: (body: { letra: Letra; tipo_cambio: string | null }) =>
      api<SolicitudOut>(`/solicitudes/${id}/seleccionar`, { method: "POST", body }),
    onSuccess: () => invalidar(id),
  });
}

export function useNoConfirmar(id: number) {
  const invalidar = useInvalidarSolicitudes();
  return useMutation({
    mutationFn: (body: { motivo: MotivoNoConfirmada; comentario: string | null }) =>
      api<SolicitudOut>(`/solicitudes/${id}/no-confirmar`, { method: "POST", body }),
    onSuccess: () => invalidar(id),
  });
}

export function useComentar(id: number) {
  const invalidar = useInvalidarSolicitudes();
  return useMutation({
    mutationFn: (texto: string) =>
      api<unknown>(`/solicitudes/${id}/comentarios`, { method: "POST", body: { texto } }),
    onSuccess: () => invalidar(id),
  });
}
