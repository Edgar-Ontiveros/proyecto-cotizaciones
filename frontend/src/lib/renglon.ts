/** Lógica del renglón RICO del comprador (F8b), separada de la UI para
 * poder probarla: validación local espejo del backend y armado del body. */

import type { Moneda, Unidad } from "./types";

export const UNIDADES: { value: Unidad; label: string }[] = [
  { value: "PZ", label: "PZ — piezas" },
  { value: "KG", label: "KG — kilogramos" },
  { value: "TON", label: "TON — toneladas" },
  { value: "MTS", label: "MTS — metros" },
  { value: "M2", label: "M2 — metros cuadrados" },
];

export interface RenglonForm {
  cantidad: string;
  unidad: Unidad;
  moneda: Moneda;
  precio: string;
  tiempo: string;
  proveedor: string;
  noEncontrada: boolean;
  esAlternativa: boolean;
  alternativaDescripcion: string;
  conObservacion: boolean;
  observacion: string;
}

/** Espejo de `_validar_renglon` del backend; null si el renglón es válido. */
export function validarRenglonLocal(r: RenglonForm): string | null {
  if (r.noEncontrada && r.esAlternativa) {
    return "Un renglón no encontrado no puede ser alternativa";
  }
  if (r.noEncontrada && (r.precio.trim() || r.alternativaDescripcion.trim())) {
    return "Un renglón no encontrado no lleva precio ni alternativa";
  }
  if (r.esAlternativa && !r.alternativaDescripcion.trim()) {
    return "Describe qué alternativa estás ofreciendo";
  }
  if (r.esAlternativa && !r.precio.trim()) {
    return "La alternativa exige precio";
  }
  if (r.conObservacion && (r.noEncontrada || r.esAlternativa)) {
    return "La observación no se combina con otro estatus";
  }
  if (r.conObservacion && !r.observacion.trim()) {
    return "Escribe la observación de esta partida";
  }
  return null;
}

/** Al activar "No encontrada" se limpia y deshabilita el resto del renglón. */
export function aplicarNoEncontrada(r: RenglonForm, activa: boolean): RenglonForm {
  if (!activa) return { ...r, noEncontrada: false };
  return {
    ...r,
    noEncontrada: true,
    esAlternativa: false,
    alternativaDescripcion: "",
    conObservacion: false,
    observacion: "",
    precio: "",
    tiempo: "",
    proveedor: "",
  };
}

export function renglonABody(partidaId: number, r: RenglonForm) {
  return {
    partida_id: partidaId,
    cantidad: r.cantidad.trim() || null,
    unidad: r.unidad,
    moneda: r.noEncontrada ? null : r.moneda,
    precio_unitario: r.precio.trim() || null,
    tiempo_entrega: r.tiempo.trim() || null,
    proveedor: r.proveedor.trim() || null,
    no_encontrada: r.noEncontrada,
    es_alternativa: r.esAlternativa,
    alternativa_descripcion: r.alternativaDescripcion.trim() || null,
    con_observacion: r.conObservacion,
    observacion: r.observacion.trim() || null,
  };
}

/** Orden OBLIGATORIO de corregir-y-reenviar (F8b): PATCH primero (la
 * corrección sobre la RECHAZADA), reenviar después. */
export async function corregirYReenviar<T>(acciones: {
  editar: () => Promise<unknown>;
  enviar: () => Promise<T>;
}): Promise<T> {
  await acciones.editar();
  return acciones.enviar();
}

/** Consolidado MXN al confirmar (F8c): total_mxn + total_usd × TC, redondeo
 * a 2 como el backend. null si falta el TC con USD presente. */
export function consolidadoMXN(
  totalMxn: string,
  totalUsd: string,
  tipoCambio: string,
): number | null {
  const usd = Number(totalUsd);
  const mxn = Number(totalMxn);
  if (usd > 0) {
    const tc = Number(tipoCambio);
    if (!tc || Number.isNaN(tc)) return null;
    return Math.round((mxn + usd * tc) * 100) / 100;
  }
  return mxn;
}

/** F10.2 p.1: decide qué ajustes viajan al aprobar un cambio. El bug de
 * producción: la versión anterior solo enviaba el renglón si cambiaba la
 * unidad o el PRECIO — un ajuste de SOLO tiempo de entrega se descartaba en
 * silencio y jamás llegaba al backend. */
export interface FilaAjusteEditor {
  letra: string;
  partida_id: number;
  unidadCambia: boolean;
  precioActual: string | null;
  tiempoActual: string;
  precio: string;
  tiempo: string;
}

export interface AjusteArmado {
  opcion_letra: string;
  partida_id: number;
  precio_unitario?: string;
  tiempo_entrega?: string;
}

export function armarAjustes(filas: FilaAjusteEditor[]): AjusteArmado[] {
  const ajustes: AjusteArmado[] = [];
  for (const f of filas) {
    const precioEscrito = f.precio.trim();
    const tiempoEscrito = f.tiempo.trim();
    const precioDistinto =
      precioEscrito !== "" && Number(precioEscrito) !== Number(f.precioActual ?? "");
    const tiempoDistinto = tiempoEscrito !== "" && tiempoEscrito !== f.tiempoActual.trim();
    if (!f.unidadCambia && !precioDistinto && !tiempoDistinto) continue;
    ajustes.push({
      opcion_letra: f.letra,
      partida_id: f.partida_id,
      // Con cambio de unidad el precio anterior quedó inválido: SIEMPRE viaja.
      ...(f.unidadCambia || precioDistinto ? { precio_unitario: precioEscrito } : {}),
      ...(tiempoDistinto ? { tiempo_entrega: tiempoEscrito } : {}),
    });
  }
  return ajustes;
}
