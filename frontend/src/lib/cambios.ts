/** F13: lógica pura del editor de cambios de partidas, separada de la UI.
 * - Lado ventas: arma el body de la solicitud (MODIFICACION/ALTA/BAJA).
 * - Lado compras: arma un renglón nuevo (ALTA) a partir del RenglonForm. */

import type { CambioPartidaBody, NuevoRenglonBody } from "../api/hooks";
import type { RenglonForm } from "./renglon";
import type { Unidad } from "./types";

export interface FilaPartidaEditor {
  partida_id: number;
  num: number;
  descripcionOriginal: string;
  cantidadOriginal: string;
  unidadOriginal: Unidad;
  descripcion: string;
  cantidad: string;
  unidad: Unidad;
  eliminar: boolean;
}

export interface FilaAltaEditor {
  key: number;
  descripcion: string;
  cantidad: string;
  unidad: Unidad;
}

/** True si una partida existente (no marcada para baja) trae algún cambio. */
export function filaModificada(f: FilaPartidaEditor): boolean {
  if (f.eliminar) return false;
  return (
    f.descripcion.trim() !== f.descripcionOriginal.trim() ||
    Number(f.cantidad) !== Number(f.cantidadOriginal) ||
    f.unidad !== f.unidadOriginal
  );
}

/** True si una fila de alta tiene algún dato (para no ignorarla como vacía). */
export function altaConDatos(a: FilaAltaEditor): boolean {
  return a.descripcion.trim() !== "" || a.cantidad.trim() !== "";
}

export interface CambioArmado {
  partidas: CambioPartidaBody[];
  error: string | null;
}

/** Arma el body de la solicitud de cambio y valida localmente (espejo del
 * backend): al menos un renglón, cantidades > 0 y al menos una partida que
 * sobreviva (no se puede dar de baja todo). */
export function construirCambio(
  existentes: FilaPartidaEditor[],
  altas: FilaAltaEditor[],
): CambioArmado {
  const partidas: CambioPartidaBody[] = [];
  for (const f of existentes) {
    if (f.eliminar) {
      partidas.push({ tipo: "BAJA", partida_id: f.partida_id });
      continue;
    }
    if (filaModificada(f)) {
      if (!(Number(f.cantidad) > 0)) {
        return { partidas: [], error: `Partida ${f.num}: la cantidad debe ser mayor a 0` };
      }
      partidas.push({
        tipo: "MODIFICACION",
        partida_id: f.partida_id,
        cantidad_nueva: f.cantidad,
        unidad_nueva: f.unidad,
        descripcion_nueva: f.descripcion.trim(),
      });
    }
  }
  for (const a of altas) {
    if (!altaConDatos(a)) continue;
    const desc = a.descripcion.trim();
    if (!desc) return { partidas: [], error: "Una partida nueva necesita descripción" };
    if (!(Number(a.cantidad) > 0)) {
      return { partidas: [], error: `Partida nueva "${desc}": la cantidad debe ser mayor a 0` };
    }
    partidas.push({
      tipo: "ALTA",
      descripcion_nueva: desc,
      cantidad_nueva: a.cantidad,
      unidad_nueva: a.unidad,
    });
  }
  if (partidas.length === 0) {
    return { partidas: [], error: "Modifica, agrega o elimina al menos una partida" };
  }
  const sobreviven =
    existentes.filter((f) => !f.eliminar).length + altas.filter(altaConDatos).length;
  if (sobreviven < 1) {
    return { partidas: [], error: "No puedes dar de baja todas las partidas" };
  }
  return { partidas, error: null };
}

/** Renglón nuevo (ALTA) capturado por compras para UNA opción. Espejo de
 * `renglonABody` pero referenciando el ALTA por `cambio_partida_id`. */
export function nuevoRenglonBody(
  cambioPartidaId: number,
  letra: string,
  r: RenglonForm,
): NuevoRenglonBody {
  return {
    cambio_partida_id: cambioPartidaId,
    opcion_letra: letra,
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

export function renglonFormVacio(): RenglonForm {
  return {
    cantidad: "",
    unidad: "PZ",
    moneda: "MXN",
    precio: "",
    tiempo: "",
    proveedor: "",
    noEncontrada: false,
    esAlternativa: false,
    alternativaDescripcion: "",
    conObservacion: false,
    observacion: "",
  };
}
