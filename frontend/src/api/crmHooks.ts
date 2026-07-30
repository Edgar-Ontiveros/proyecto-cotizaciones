/** Hooks del CRM (F8d) sobre lib/api. Los errores de mutación los muestra el
 * handler GLOBAL del QueryClient (main.tsx): aquí NO se repite
 * notifications.show. */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { API_BASE, ApiError, getAccessToken, refrescarToken } from "../lib/api";
import { api } from "../lib/api";
import type {
  FestivoOut,
  FiltrosCatalogoOut,
  GrupoOut,
  MaterialesOut,
  MotivoOut,
  NoEncontradosOut,
  ReasignacionMasivaOut,
  ResetPasswordOut,
  ResumenOut,
  SerieOut,
  SolicitudOut,
  SucursalOut,
  TerritoriosOut,
  TiemposEtapaOut,
  UsuarioCreadoOut,
  UsuarioListOut,
  UsuarioOut,
} from "../lib/types";

type Params = Record<string, string | number | boolean | undefined>;

// ------------------------------------------------------------------ métricas

export function useResumen(params: Params) {
  return useQuery({
    queryKey: ["metricas", "resumen", params],
    queryFn: () => api<ResumenOut>("/metricas/resumen", { params }),
    placeholderData: (prev) => prev,
  });
}

export function useSerie(params: Params) {
  return useQuery({
    queryKey: ["metricas", "serie", params],
    queryFn: () => api<SerieOut>("/metricas/serie", { params }),
    placeholderData: (prev) => prev,
  });
}

export function useTabla(dimension: string, params: Params, habilitado: boolean) {
  return useQuery({
    queryKey: ["metricas", dimension, params],
    queryFn: () => api<GrupoOut[]>(`/metricas/por-${dimension}`, { params }),
    enabled: habilitado,
    placeholderData: (prev) => prev,
  });
}

export function useNoEncontrados(params: Params, habilitado: boolean) {
  return useQuery({
    queryKey: ["metricas", "no-encontrados", params],
    queryFn: () => api<NoEncontradosOut>("/metricas/no-encontrados", { params }),
    enabled: habilitado,
    placeholderData: (prev) => prev,
  });
}

export function useMateriales(params: Params, habilitado = true) {
  return useQuery({
    queryKey: ["metricas", "materiales", params],
    queryFn: () => api<MaterialesOut>("/metricas/materiales", { params }),
    enabled: habilitado,
    placeholderData: (prev) => prev,
  });
}

export function useTiemposEtapa(params: Params) {
  return useQuery({
    queryKey: ["metricas", "tiempos-etapa", params],
    queryFn: () => api<TiemposEtapaOut>("/metricas/tiempos-etapa", { params }),
    placeholderData: (prev) => prev,
  });
}

export function useFiltrosCatalogo() {
  return useQuery({
    queryKey: ["metricas", "filtros"],
    queryFn: () => api<FiltrosCatalogoOut>("/metricas/filtros"),
    staleTime: 5 * 60_000,
  });
}

// ------------------------------------------------------------------ usuarios

export interface FiltrosUsuarios {
  rol?: string;
  sucursal_id?: number;
  activo?: boolean;
  q?: string;
  limit?: number;
  offset?: number;
}

export function useUsuarios(filtros: FiltrosUsuarios) {
  return useQuery({
    queryKey: ["usuarios", filtros],
    queryFn: () => api<UsuarioListOut>("/usuarios", { params: { ...filtros } }),
    placeholderData: (prev) => prev,
  });
}

function useInvalidarUsuarios() {
  const qc = useQueryClient();
  return () => {
    void qc.invalidateQueries({ queryKey: ["usuarios"] });
    void qc.invalidateQueries({ queryKey: ["territorios"] });
    void qc.invalidateQueries({ queryKey: ["metricas", "filtros"] });
  };
}

export interface UsuarioBody {
  nombre: string;
  email: string;
  rol: string;
  sucursal_id: number | null;
}

export function useCrearUsuario() {
  const invalidar = useInvalidarUsuarios();
  return useMutation({
    mutationFn: (body: UsuarioBody) =>
      api<UsuarioCreadoOut>("/usuarios", { method: "POST", body }),
    onSuccess: invalidar,
  });
}

export function useEditarUsuario() {
  const invalidar = useInvalidarUsuarios();
  return useMutation({
    mutationFn: ({ id, body }: { id: number; body: Partial<UsuarioBody> }) =>
      api<UsuarioOut>(`/usuarios/${id}`, { method: "PATCH", body }),
    onSuccess: invalidar,
  });
}

export function useResetPassword() {
  return useMutation({
    mutationFn: (id: number) =>
      api<ResetPasswordOut>(`/usuarios/${id}/reset-password`, { method: "POST" }),
  });
}

export function useActivarUsuario() {
  const invalidar = useInvalidarUsuarios();
  return useMutation({
    mutationFn: (id: number) => api<UsuarioOut>(`/usuarios/${id}/activar`, { method: "POST" }),
    onSuccess: invalidar,
  });
}

export interface DesactivarBody {
  titularidades_a?: number;
  solicitudes_a?: number;
}

export function useDesactivarUsuario() {
  const invalidar = useInvalidarUsuarios();
  return useMutation({
    // El 409 de baja segura lo maneja el modal (abre el flujo guiado).
    meta: { errorManejado: true },
    mutationFn: ({ id, body }: { id: number; body: DesactivarBody }) =>
      api<UsuarioOut>(`/usuarios/${id}/desactivar`, { method: "POST", body }),
    onSuccess: invalidar,
  });
}

// ---------------------------------------------------------------- sucursales

/** Listado completo de sucursales — SOLO admin (la vista Sucursales); para
 * armar filtros por rol está useFiltrosCatalogo. */
export function useSucursales() {
  return useQuery({
    queryKey: ["sucursales"],
    queryFn: () => api<SucursalOut[]>("/sucursales"),
  });
}

function useInvalidarSucursales() {
  const qc = useQueryClient();
  return () => {
    void qc.invalidateQueries({ queryKey: ["sucursales"] });
    void qc.invalidateQueries({ queryKey: ["territorios"] });
    void qc.invalidateQueries({ queryKey: ["metricas", "filtros"] });
  };
}

export interface SucursalBody {
  nombre: string;
  prefijo_folio: string;
  timezone: string;
  contador_inicial?: number;
}

export function useCrearSucursal() {
  const invalidar = useInvalidarSucursales();
  return useMutation({
    mutationFn: (body: SucursalBody) => api<SucursalOut>("/sucursales", { method: "POST", body }),
    onSuccess: invalidar,
  });
}

export function useEditarSucursal() {
  const invalidar = useInvalidarSucursales();
  return useMutation({
    mutationFn: ({ id, body }: { id: number; body: Partial<SucursalBody> & { activa?: boolean } }) =>
      api<SucursalOut>(`/sucursales/${id}`, { method: "PATCH", body }),
    onSuccess: invalidar,
  });
}

export function useEditarFolioCounter() {
  const invalidar = useInvalidarSucursales();
  return useMutation({
    mutationFn: ({ id, ultimo }: { id: number; ultimo: number }) =>
      api<unknown>(`/sucursales/${id}/folio-counter`, { method: "PATCH", body: { ultimo } }),
    onSuccess: invalidar,
  });
}

// -------------------------------------------------------------- territorios

export function useTerritorios() {
  return useQuery({
    queryKey: ["territorios"],
    queryFn: () => api<TerritoriosOut>("/territorios"),
  });
}

export function useCambiarTitular() {
  const invalidar = useInvalidarSucursales();
  return useMutation({
    mutationFn: ({ sucursalId, compradorId }: { sucursalId: number; compradorId: number }) =>
      api<void>(`/sucursales/${sucursalId}/titular`, {
        method: "PUT",
        body: { comprador_id: compradorId },
      }),
    onSuccess: invalidar,
  });
}

// ------------------------------------------------------------ reasignaciones

function useInvalidarSolicitudesCrm() {
  const qc = useQueryClient();
  return (id?: number) => {
    void qc.invalidateQueries({ queryKey: ["solicitudes"] });
    if (id !== undefined) void qc.invalidateQueries({ queryKey: ["solicitud", id] });
  };
}

export function useReasignarComprador(id: number) {
  const invalidar = useInvalidarSolicitudesCrm();
  return useMutation({
    mutationFn: (compradorId: number) =>
      api<SolicitudOut>(`/solicitudes/${id}/reasignar-comprador`, {
        method: "POST",
        body: { comprador_id: compradorId },
      }),
    onSuccess: () => invalidar(id),
  });
}

export function useReasignarVendedor(id: number) {
  const invalidar = useInvalidarSolicitudesCrm();
  return useMutation({
    mutationFn: (vendedorId: number) =>
      api<SolicitudOut>(`/solicitudes/${id}/reasignar-vendedor`, {
        method: "POST",
        body: { vendedor_id: vendedorId },
      }),
    onSuccess: () => invalidar(id),
  });
}

export function useReasignacionMasiva(tipo: "comprador" | "vendedor") {
  const invalidar = useInvalidarSolicitudesCrm();
  return useMutation({
    mutationFn: (body: { de_id: number; a_id: number }) =>
      api<ReasignacionMasivaOut>(`/reasignaciones/${tipo}`, { method: "POST", body }),
    onSuccess: () => invalidar(),
  });
}

// ------------------------------------------------------- corrección de TC

export function useCorregirTipoCambio(id: number) {
  const invalidar = useInvalidarSolicitudesCrm();
  return useMutation({
    mutationFn: (tipoCambio: string) =>
      api<SolicitudOut>(`/solicitudes/${id}/tipo-cambio`, {
        method: "PATCH",
        body: { tipo_cambio: tipoCambio },
      }),
    onSuccess: () => invalidar(id),
  });
}

// ----------------------------------------------------------------- catálogos

export function useMotivosAdmin() {
  return useQuery({
    queryKey: ["motivos-rechazo", "admin"],
    queryFn: () =>
      api<MotivoOut[]>("/catalogos/motivos-rechazo", { params: { solo_activos: false } }),
  });
}

function useInvalidarCatalogos() {
  const qc = useQueryClient();
  return () => {
    void qc.invalidateQueries({ queryKey: ["motivos-rechazo"] });
    void qc.invalidateQueries({ queryKey: ["festivos"] });
  };
}

export function useCrearMotivo() {
  const invalidar = useInvalidarCatalogos();
  return useMutation({
    mutationFn: (body: { familia: string; texto: string }) =>
      api<MotivoOut>("/catalogos/motivos-rechazo", { method: "POST", body }),
    onSuccess: invalidar,
  });
}

export function useEditarMotivo() {
  const invalidar = useInvalidarCatalogos();
  return useMutation({
    mutationFn: ({ id, body }: { id: number; body: { texto?: string; activo?: boolean } }) =>
      api<MotivoOut>(`/catalogos/motivos-rechazo/${id}`, { method: "PATCH", body }),
    onSuccess: invalidar,
  });
}

export function useFestivos() {
  return useQuery({
    queryKey: ["festivos"],
    queryFn: () => api<FestivoOut[]>("/catalogos/dias-festivos"),
  });
}

export function useCrearFestivo() {
  const invalidar = useInvalidarCatalogos();
  return useMutation({
    mutationFn: (body: { fecha: string; descripcion: string | null }) =>
      api<FestivoOut>("/catalogos/dias-festivos", { method: "POST", body }),
    onSuccess: invalidar,
  });
}

export function useEliminarFestivo() {
  const invalidar = useInvalidarCatalogos();
  return useMutation({
    mutationFn: (id: number) => api<void>(`/catalogos/dias-festivos/${id}`, { method: "DELETE" }),
    onSuccess: invalidar,
  });
}

// ------------------------------------------------------------------- export

/** Descarga el Excel con los filtros ACTUALES. No pasa por api<T> (es un
 * blob), pero respeta el token en memoria y reintenta una vez tras refresh. */
export async function descargarExport(params: Params): Promise<void> {
  const query = new URLSearchParams();
  for (const [clave, valor] of Object.entries(params)) {
    if (valor !== undefined && valor !== null && valor !== "") query.append(clave, String(valor));
  }
  const url = `${API_BASE}/solicitudes/export${query.size ? `?${query.toString()}` : ""}`;
  const pedir = () =>
    fetch(url, {
      headers: getAccessToken() ? { Authorization: `Bearer ${getAccessToken()!}` } : {},
      credentials: "include",
    });
  let respuesta = await pedir();
  if (respuesta.status === 401 && (await refrescarToken())) respuesta = await pedir();
  if (!respuesta.ok) {
    const cuerpo = (await respuesta.json().catch(() => ({}))) as {
      detail?: string;
      code?: string;
    };
    throw new ApiError(
      respuesta.status,
      cuerpo.detail ?? "No se pudo exportar",
      cuerpo.code ?? "export_error",
    );
  }
  const blob = await respuesta.blob();
  const enlace = document.createElement("a");
  enlace.href = URL.createObjectURL(blob);
  enlace.download = "solicitudes.xlsx";
  enlace.click();
  URL.revokeObjectURL(enlace.href);
}
