import dayjs from "dayjs";
import "dayjs/locale/es-mx";
import timezone from "dayjs/plugin/timezone";
import utc from "dayjs/plugin/utc";

import type { Banda, Moneda } from "./types";

dayjs.extend(utc);
dayjs.extend(timezone);
dayjs.locale("es-mx");

const numero = new Intl.NumberFormat("es-MX", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

/** "MX$ 28,325.00" / "US$ 351.00" — SIEMPRE con la moneda del dato; las
 * monedas jamás se mezclan ni se suman en UI. */
export function dinero(monto: string | number, moneda: Moneda): string {
  const prefijo = moneda === "MXN" ? "MX$" : "US$";
  return `${prefijo} ${numero.format(typeof monto === "string" ? Number(monto) : monto)}`;
}

/** "CCN-3036 · DINCO"; sin folio (borrador) muestra solo el cliente. */
export function folioCliente(folio: string | null, cliente: string | null): string {
  const partes = [folio ?? "(sin folio)", cliente ?? "(sin cliente)"];
  return partes.join(" · ");
}

export function bandaColor(banda: Banda): string {
  if (banda === "ESPERADA") return "green";
  if (banda === "NORMAL") return "yellow";
  return "red";
}

/** Tooltip del semáforo: "X.X h hábiles · día T". */
export function bandaTooltip(horasHabiles: number, dias: number): string {
  return `${horasHabiles.toFixed(1)} h hábiles · día ${dias}`;
}

export function fecha(iso: string): string {
  return dayjs(iso).format("DD/MMM/YYYY");
}

export function fechaHora(iso: string): string {
  return dayjs(iso).format("DD/MMM/YYYY HH:mm");
}

export function pct(valor: number | null): string {
  return valor === null ? "—" : `${(valor * 100).toFixed(1)}%`;
}

export function horas(valor: number | null): string {
  return valor === null ? "—" : `${valor.toFixed(1)} h`;
}
