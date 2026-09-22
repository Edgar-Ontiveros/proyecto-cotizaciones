/** Filtros de listado compartidos (F8d): rango de fechas + búsqueda con
 * debounce + paginación PAGE=25. Reemplaza las copias que vivían en
 * ListadoVendedor y PanelComprador. */

import { Group, TextInput } from "@mantine/core";
import { DatePickerInput } from "@mantine/dates";
import { useDebouncedValue } from "@mantine/hooks";
import dayjs from "dayjs";
import { useState } from "react";

export const PAGE = 25;

export interface FiltrosListadoState {
  pagina: number;
  setPagina: (p: number) => void;
  rango: RangoFechasValor;
  setRango: (v: RangoFechasValor) => void;
  buscar: string;
  setBuscar: (v: string) => void;
  /** Listo para el query: desde/hasta en YYYY-MM-DD y buscar con debounce. */
  filtros: { desde?: string; hasta?: string; buscar?: string };
  offset: number;
}

export function useFiltrosListado(): FiltrosListadoState {
  const [pagina, setPagina] = useState(1);
  const [rango, setRangoInterno] = useState<RangoFechasValor>([null, null]);
  const [buscar, setBuscarInterno] = useState("");
  const [buscarDebounced] = useDebouncedValue(buscar, 300);

  // Cualquier cambio de filtro regresa a la página 1.
  const setRango = (v: RangoFechasValor) => {
    setRangoInterno(v);
    setPagina(1);
  };
  const setBuscar = (v: string) => {
    setBuscarInterno(v);
    setPagina(1);
  };

  return {
    pagina,
    setPagina,
    rango,
    setRango,
    buscar,
    setBuscar,
    filtros: {
      desde: rango[0] ? dayjs(rango[0]).format("YYYY-MM-DD") : undefined,
      hasta: rango[1] ? dayjs(rango[1]).format("YYYY-MM-DD") : undefined,
      buscar: buscarDebounced || undefined,
    },
    offset: (pagina - 1) * PAGE,
  };
}

export type RangoFechasValor = [string | null, string | null];

/** El selector de RANGO DE FECHAS del listado de Solicitudes — único en el
 * sistema. F15 p.1: lo reusa Comparativas (sin duplicar el control). */
export function RangoFechas({
  value,
  onChange,
}: {
  value: RangoFechasValor;
  onChange: (v: RangoFechasValor) => void;
}) {
  return (
    <DatePickerInput
      type="range"
      placeholder="Rango de fechas"
      value={value}
      onChange={onChange}
      clearable
      w={240}
    />
  );
}

export function FiltrosRangoBusqueda({ estado }: { estado: FiltrosListadoState }) {
  return (
    <Group mb="sm" gap="sm">
      <RangoFechas value={estado.rango} onChange={estado.setRango} />
      <TextInput
        placeholder="Buscar folio o cliente"
        value={estado.buscar}
        onChange={(e) => estado.setBuscar(e.currentTarget.value)}
        w={220}
      />
    </Group>
  );
}
