/** Subida, descarga y eliminación de comprobantes de pedido (F8g; F10 p.6:
 * pueden ser VARIOS). Multipart y blob no pasan por el wrapper JSON
 * (lib/api): mismo patrón de auth + retry único tras refresh que
 * descargarExport. */

import { API_BASE, ApiError, getAccessToken, refrescarToken } from "../lib/api";
import type { ComprobanteOut } from "../lib/types";

function authHeaders(): Record<string, string> {
  const token = getAccessToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function aApiError(respuesta: Response, fallback: string): Promise<ApiError> {
  const cuerpo = (await respuesta.json().catch(() => ({}))) as {
    detail?: string;
    code?: string;
  };
  return new ApiError(respuesta.status, cuerpo.detail ?? fallback, cuerpo.code ?? "unknown_error");
}

export async function subirComprobante(solicitudId: number, file: File): Promise<ComprobanteOut> {
  const pedir = () => {
    const form = new FormData();
    form.append("archivo", file);
    return fetch(`${API_BASE}/solicitudes/${solicitudId}/comprobante`, {
      method: "POST",
      headers: authHeaders(),
      credentials: "include",
      body: form,
    });
  };
  let respuesta = await pedir();
  if (respuesta.status === 401 && (await refrescarToken())) respuesta = await pedir();
  if (!respuesta.ok) throw await aApiError(respuesta, "No se pudo subir el comprobante");
  return (await respuesta.json()) as ComprobanteOut;
}

export async function descargarComprobante(
  solicitudId: number,
  archivoId: string,
  nombre: string,
): Promise<void> {
  const pedir = () =>
    fetch(`${API_BASE}/solicitudes/${solicitudId}/comprobantes/${archivoId}`, {
      headers: authHeaders(),
      credentials: "include",
    });
  let respuesta = await pedir();
  if (respuesta.status === 401 && (await refrescarToken())) respuesta = await pedir();
  if (!respuesta.ok) throw await aApiError(respuesta, "No se pudo descargar el comprobante");
  const blob = await respuesta.blob();
  const enlace = document.createElement("a");
  enlace.href = URL.createObjectURL(blob);
  enlace.download = nombre;
  enlace.click();
  URL.revokeObjectURL(enlace.href);
}

export async function eliminarComprobante(solicitudId: number, archivoId: string): Promise<void> {
  const pedir = () =>
    fetch(`${API_BASE}/solicitudes/${solicitudId}/comprobantes/${archivoId}`, {
      method: "DELETE",
      headers: authHeaders(),
      credentials: "include",
    });
  let respuesta = await pedir();
  if (respuesta.status === 401 && (await refrescarToken())) respuesta = await pedir();
  if (!respuesta.ok) throw await aApiError(respuesta, "No se pudo eliminar el comprobante");
}
