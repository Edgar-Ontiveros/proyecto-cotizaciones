/** Hooks de datos (TanStack Query 5) sobre lib/api. Un archivo por brevedad:
 * routers delgados en el backend, hooks delgados aquí. */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../lib/api";
import type {
  CambioOut,
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
  TipoRenglonCambio,
} from "../lib/types";

export interface FiltrosListado {
  estado?: string;
  es_proyecto?: boolean;
  // F10 p.7b: filtro "con cambio pendiente".
  cambio_pendiente?: boolean;
  // F12 p.5: Fincadas / Sin fincar (solo lo aplica el backend para el área
  // compras; para el resto se ignora).
  fincada?: boolean;
  // F10.2 p.4: la pestaña Confirmadas ordena por fecha de confirmación.
  orden?: string;
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

/** F10 p.1: mientras hay un cambio pendiente, la resolución sucede en OTRO
 * navegador (el del comprador) y esta vista no se enteraría jamás — sin
 * websockets y con refetchOnWindowFocus apagado, el botón de confirmar del
 * vendedor quedaba bloqueado hasta un F5. Polling suave SOLO en ese estado. */
export function intervaloDetalle(
  data: { cambio_pendiente?: boolean } | undefined,
): number | false {
  return data?.cambio_pendiente ? 15_000 : false;
}

export function useSolicitud(id: number) {
  return useQuery({
    queryKey: ["solicitud", id],
    queryFn: () => api<SolicitudDetailOut>(`/solicitudes/${id}`),
    enabled: id > 0,
    refetchInterval: (query) => intervaloDetalle(query.state.data),
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
    queryFn: () => api<MotivoOut[]>("/motivos-rechazo"),
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

/** F12 p.5: marca/desmarca FINCADA (interno del área compras, reversible). */
export function useMarcarFincada(solicitudId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (fincada: boolean) =>
      api<SolicitudOut>(`/solicitudes/${solicitudId}/fincada`, {
        method: "PATCH",
        body: { fincada },
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["solicitud", solicitudId] });
      void qc.invalidateQueries({ queryKey: ["solicitudes"] });
    },
  });
}

// ------------------------------------------------------------------ mutaciones

export interface SolicitudBody {
  cliente: string | null;
  prioridad: string;
  notas: string | null;
  // F8f: solo puede cambiar mientras es BORRADOR (el backend responde 422
  // es_proyecto_inmutable después).
  es_proyecto: boolean;
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
  // F10.3: TC capturado al RECOTIZAR cuando la corrección introduce USD.
  tipo_cambio?: string;
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
    // La vista mapea los faltantes al formulario: sin toast global (F8d).
    meta: { errorManejado: true },
    // v3 (F8e): el comprador captura el TC al cotizar cuando hay USD.
    mutationFn: (tipoCambio?: string) =>
      api<SolicitudOut>(`/solicitudes/${id}/cotizar`, {
        method: "POST",
        body: tipoCambio !== undefined ? { tipo_cambio: tipoCambio } : undefined,
      }),
    onSuccess: () => invalidar(id),
  });
}

export function useSeleccionar(id: number) {
  const invalidar = useInvalidarSolicitudes();
  return useMutation({
    // v3 (F8e): selección SIMPLE — sin tipo de cambio.
    mutationFn: (body: { letra: Letra }) =>
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

// ------------------------------------------------ cambios (F8h/F13, §4.8b)

// F13: un renglón de la solicitud de cambio, discriminado por `tipo`.
export interface CambioPartidaBody {
  tipo: TipoRenglonCambio;
  partida_id?: number | null; // MODIFICACION/BAJA
  cantidad_nueva?: string | null; // MODIFICACION/ALTA
  unidad_nueva?: string | null; // MODIFICACION/ALTA
  descripcion_nueva?: string | null; // MODIFICACION (opcional) / ALTA
}

export interface AjusteBody {
  opcion_letra: string;
  partida_id: number;
  precio_unitario?: string;
  tiempo_entrega?: string;
}

// F13: captura de compras para una partida NUEVA (ALTA) en UNA opción.
export interface NuevoRenglonBody {
  cambio_partida_id: number;
  opcion_letra: string;
  moneda: string | null;
  precio_unitario: string | null;
  tiempo_entrega: string | null;
  proveedor: string | null;
  no_encontrada: boolean;
  es_alternativa: boolean;
  alternativa_descripcion: string | null;
  con_observacion: boolean;
  observacion: string | null;
}

export function useSolicitarCambio(id: number) {
  const invalidar = useInvalidarSolicitudes();
  return useMutation({
    meta: { errorManejado: true },
    mutationFn: (body: { comentario: string | null; partidas: CambioPartidaBody[] }) =>
      api<CambioOut>(`/solicitudes/${id}/cambios`, { method: "POST", body }),
    onSuccess: () => invalidar(id),
  });
}

export function useRetirarCambio(id: number) {
  const invalidar = useInvalidarSolicitudes();
  return useMutation({
    mutationFn: () => api<CambioOut>(`/solicitudes/${id}/cambios/pendiente`, { method: "DELETE" }),
    onSuccess: () => invalidar(id),
  });
}

export function useAprobarCambio(solicitudId: number) {
  const invalidar = useInvalidarSolicitudes();
  return useMutation({
    meta: { errorManejado: true },
    mutationFn: ({
      cambioId,
      comentario,
      ajustes,
      nuevos,
      tipoCambio,
    }: {
      cambioId: number;
      comentario: string | null;
      ajustes: AjusteBody[];
      // F13: captura de renglones de partidas nuevas (ALTA) por opción.
      nuevos?: NuevoRenglonBody[];
      // F10.3: TC capturado al AUTORIZAR (422 tipo_cambio_requerido).
      tipoCambio?: string;
    }) =>
      api<CambioOut>(`/cambios/${cambioId}/aprobar`, {
        method: "POST",
        body: { comentario, ajustes, nuevos: nuevos ?? [], tipo_cambio: tipoCambio },
      }),
    onSuccess: () => invalidar(solicitudId),
  });
}

export function useRechazarCambio(solicitudId: number) {
  const invalidar = useInvalidarSolicitudes();
  return useMutation({
    meta: { errorManejado: true },
    mutationFn: ({ cambioId, comentario }: { cambioId: number; comentario: string }) =>
      api<CambioOut>(`/cambios/${cambioId}/rechazar`, { method: "POST", body: { comentario } }),
    onSuccess: () => invalidar(solicitudId),
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
