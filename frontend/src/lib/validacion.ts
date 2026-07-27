/** Validación Zod espejo del backend (PartidaIn / SolicitudCreate) y mapeo de
 * los 422 de negocio a campos concretos del formulario. */

import { z } from "zod";

// Espejo de PartidaIn: cantidad > 0; unidad y descripción obligatorias;
// codigo_sap / tipo_acero / medidas opcionales ("SERVICIO" cuando no hay SAP).
export const partidaSchema = z.object({
  codigo_sap: z.string().trim().max(40).optional().or(z.literal("")),
  cantidad: z
    .string()
    .trim()
    .min(1, "Captura la cantidad")
    .refine((v) => !Number.isNaN(Number(v)) && Number(v) > 0, "La cantidad debe ser mayor a 0"),
  unidad: z.string().trim().min(1, "La unidad es obligatoria"),
  tipo_acero: z.string().trim().optional().or(z.literal("")),
  descripcion: z.string().trim().min(1, "La descripción es obligatoria"),
  medidas: z.string().trim().optional().or(z.literal("")),
});

export const solicitudSchema = z.object({
  cliente: z.string().trim().optional().or(z.literal("")),
  prioridad: z.enum(["NORMAL", "URGENTE"]),
  notas: z.string().trim().optional().or(z.literal("")),
  partidas: z.array(partidaSchema),
});

export type PartidaForm = z.infer<typeof partidaSchema>;
export type SolicitudForm = z.infer<typeof solicitudSchema>;

/** Resolver Zod → @mantine/form (el paquete oficial del resolver no está en
 * el stack; esto son 10 líneas): claves con la ruta "partidas.0.cantidad". */
export function resolverZod<T>(schema: z.ZodType<T>) {
  return (values: T): Record<string, string> => {
    const resultado = schema.safeParse(values);
    if (resultado.success) return {};
    const errores: Record<string, string> = {};
    for (const issue of resultado.error.issues) {
      errores[issue.path.join(".")] ??= issue.message;
    }
    return errores;
  };
}

export interface FaltanteCotizacion {
  letra: string;
  campo: "moneda" | "vigencia" | "precio_unitario" | "tiempo_entrega";
  num_partida: number | null;
}

/** Parsea el detail del 422 `cotizacion_incompleta` del backend a campos.
 *
 * Formato real: "Cotización incompleta: opción A: falta moneda; opción A:
 * falta precio_unitario en la partida 2; opción B: falta tiempo_entrega en la
 * partida 1" — cada pieza se pinta EXACTAMENTE en su opción/partida/campo. */
export function parsearFaltantesCotizacion(detail: string): FaltanteCotizacion[] {
  const piezas = detail.replace(/^[^:]*incompleta:\s*/i, "").split(";");
  const resultado: FaltanteCotizacion[] = [];
  for (const pieza of piezas) {
    const m = pieza.match(
      /opción\s+(\w+):\s+falta\s+(moneda|vigencia|precio_unitario|tiempo_entrega)(?:\s+en la partida\s+(\d+))?/i,
    );
    if (m && m[1] && m[2]) {
      resultado.push({
        letra: m[1],
        campo: m[2] as FaltanteCotizacion["campo"],
        num_partida: m[3] ? Number(m[3]) : null,
      });
    }
  }
  return resultado;
}

/** Mapea el 422 `solicitud_incompleta` del envío a campos del formulario.
 * Formato: "No se puede enviar, faltan: cliente, al menos una partida". */
export function parsearFaltantesEnvio(detail: string): { cliente: boolean; partidas: boolean } {
  return {
    cliente: /cliente/i.test(detail),
    partidas: /partida/i.test(detail),
  };
}
